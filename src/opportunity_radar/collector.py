"""Injectable OpenCLI collection with resumable, local post checkpoints."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from typing import Any

from .models import CollectionCoverage, CollectionScope, CollectionSettings, Community, ShortlistedPost, WindowedPost
from .normalization import normalize_and_deduplicate
from .scoring import score_shortlist, score_stratified_shortlist
from .storage import RunPaths, append_failure, persist_thread, write_normalized_records
from .windowing import window_posts

CommandRunner = Callable[[tuple[str, ...]], str]
ProgressReporter = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class ThreadComment:
    """One comment retained from a deep-read response."""

    comment_id: str
    body: str
    url: str
    author: str = ""
    parent_id: str = ""
    depth: int = 1
    score: int = 0


@dataclass(frozen=True, slots=True)
class ThreadDocument:
    """The evidence available to a post-level LLM extraction."""

    post: Any
    comments: tuple[ThreadComment, ...]

    @property
    def comment_authors(self) -> tuple[str, ...]:
        """Distinct public commenter names, excluding the original poster."""
        op_author = str(getattr(self.post, "author", "") or "").casefold()
        return tuple(dict.fromkeys(
            comment.author for comment in self.comments
            if comment.author and comment.author.casefold() != op_author
        ))


@dataclass(frozen=True, slots=True)
class CollectionFailure:
    """Secret-free structured failure information for a resumable target."""

    community: str
    post_id: str | None
    stage: str
    message: str


class CollectionCancelled(RuntimeError):
    """Raised when the caller cancels an external Reddit operation."""


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Artifacts and normalized candidates produced by one collection pass."""

    candidates: tuple[WindowedPost, ...]
    shortlisted: tuple[ShortlistedPost, ...]
    deep_reads: tuple[ThreadDocument, ...]
    failures: tuple[CollectionFailure, ...]
    coverage: Mapping[str, CollectionCoverage] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoundTwoCollectionResult:
    """Keyword-search records, resumable independently from community collection."""

    candidates: tuple[WindowedPost, ...]
    failures: tuple[CollectionFailure, ...]
    selected_terms: tuple[str, ...]
    deep_reads: tuple[ThreadDocument, ...] = ()
    coverage: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


class OpenCliCollector:
    """Collect Reddit listings through a caller-supplied OpenCLI process boundary."""

    def __init__(
        self,
        *,
        runner: CommandRunner,
        settings: CollectionSettings | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._runner = runner
        self._settings = settings or CollectionSettings()
        self._sleeper = sleeper or time.sleep
        self._successful_checkpoints: dict[Path, Mapping[str, Any]] = {}

    def _prefetch_complete_batches(
        self,
        targets: Sequence[tuple[str, Any]],
        *,
        paths: RunPaths,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Populate per-post checkpoints with one browser lease per ten posts."""
        pending: list[tuple[str, Any]] = []
        for community, entry in targets:
            checkpoint_path = paths.checkpoints_dir / f"{entry.post.post_id}.json"
            checkpoint = _read_checkpoint(checkpoint_path) or {}
            if checkpoint.get("status") != "success":
                pending.append((community, entry))
        for offset in range(0, len(pending), 3):
            batch = pending[offset:offset + 3]
            ids = tuple(entry.post.post_id for _community, entry in batch)
            try:
                response = _parse_json(self._runner(_batch_read_command(ids, self._settings)))
            except CollectionCancelled:
                raise
            except Exception:
                # The normal per-post loop below remains the resumable fallback.
                if progress is not None:
                    progress({
                        "stage": "deep_read",
                        "completed": min(offset + len(batch), len(pending)),
                        "total": len(pending),
                        "message": (
                            f"批量读取超时或失败，已尝试 {min(offset + len(batch), len(pending))}/{len(pending)}；"
                            "稍后自动按单帖重试。"
                        ),
                    })
                continue
            rows = response if isinstance(response, list) else []
            by_id = {
                str(row.get("post_id", "")).removeprefix("t3_"): row
                for row in rows if isinstance(row, Mapping)
            }
            for _community, entry in batch:
                row = by_id.get(entry.post.post_id.removeprefix("t3_"))
                if not isinstance(row, Mapping) or row.get("status") != "success" or not isinstance(row.get("comments"), list):
                    continue
                raw_thread = row["comments"]
                persist_thread(paths, entry.post.post_id, raw_thread)
                checkpoint_path = paths.checkpoints_dir / f"{entry.post.post_id}.json"
                document = {"status": "success", "thread": raw_thread}
                _write_checkpoint(checkpoint_path, document)
                self._successful_checkpoints[checkpoint_path] = document
            if progress is not None:
                saved = sum(
                    1 for _community, entry in pending[:offset + len(batch)]
                    if (paths.checkpoints_dir / f"{entry.post.post_id}.json").exists()
                )
                progress({
                    "stage": "deep_read",
                    "completed": min(offset + len(batch), len(pending)),
                    "total": len(pending),
                    "message": f"完整评论批量读取已尝试 {min(offset + len(batch), len(pending))}/{len(pending)}，已成功保存 {saved} 篇。",
                })

    def collect(
        self,
        communities: Iterable[Community],
        *,
        paths: RunPaths,
        as_of: datetime,
        deep_read: bool = False,
        shortlist_limit: int = 30,
        scope: CollectionScope | None = None,
        progress: ProgressReporter | None = None,
    ) -> CollectionResult:
        """Preserve all list surfaces, then optionally deep-read up to 30 posts/community."""
        if shortlist_limit < 1:
            raise ValueError("shortlist_limit must be at least one")
        communities = tuple(communities)
        if progress is not None:
            progress({
                "stage": "collecting",
                "completed": 0,
                "total": len(communities),
                "message": "正在采集社区帖子列表。",
            })
        records_by_community: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        failures: list[CollectionFailure] = []
        for community_index, community in enumerate(communities):
            commands = (
                (("range", _range_command(community.name, scope)),)
                if scope is not None else _listing_commands(community.name)
            )
            for surface, arguments in commands:
                try:
                    cached_listing = paths.raw_listings_dir / f"{_safe_path_component(community.name)}__{surface}.json"
                    if cached_listing.exists():
                        raw_text = cached_listing.read_text(encoding="utf-8")
                    else:
                        raw_text = self._runner(arguments)
                        _write_raw_listing(paths.raw_dir, community.name, surface, raw_text)
                    records = _parse_records(raw_text)
                    for record in records:
                        item = dict(record)
                        row_surfaces = item.pop("source_surfaces", ())
                        if isinstance(row_surfaces, list) and row_surfaces:
                            for row_surface in row_surfaces:
                                records_by_community[community.name].append({**item, "source_surface": str(row_surface)})
                        else:
                            item["source_surface"] = str(item.get("source_surface") or surface)
                            records_by_community[community.name].append(item)
                except CollectionCancelled:
                    raise
                except Exception as error:
                    failure = CollectionFailure(
                        community=community.name,
                        post_id=None,
                        stage=f"listing:{community.name}:{surface}",
                        message=_safe_error(error),
                    )
                    failures.append(failure)
                    append_failure(paths, {
                        "community": failure.community,
                        "post_id": failure.post_id,
                        "stage": failure.stage,
                        "error_type": type(error).__name__,
                        "retryable": True,
                    })
            if progress is not None:
                progress({
                    "stage": "collecting",
                    "completed": community_index + 1,
                    "total": len(communities),
                    "community": community.name,
                    "message": f"已完成 r/{community.name} 帖子列表采集。",
                })

        candidates: list[WindowedPost] = []
        shortlisted_targets: list[tuple[str, ShortlistedPost]] = []
        coverage: dict[str, CollectionCoverage] = {}
        for community in communities:
            normalized = normalize_and_deduplicate(records_by_community.get(community.name, ()))
            community_candidates = window_posts(
                normalized,
                as_of=as_of,
                start_date=scope.start_date if scope else None,
                end_date=scope.end_date if scope else None,
            )
            candidates.extend(community_candidates)
            if scope is not None:
                dates = sorted(item.post.created_at.date() for item in community_candidates)
                actual_start = dates[0] if dates else None
                actual_end = dates[-1] if dates else None
                hints = {
                    str(record.get("coverage_status", "")).strip().casefold()
                    for record in records_by_community.get(community.name, ())
                    if str(record.get("coverage_status", "")).strip()
                }
                if "partial" in hints:
                    coverage_status = "partial"
                elif "complete" in hints:
                    coverage_status = "complete"
                else:
                    coverage_status = "complete" if actual_start is not None and actual_start <= scope.start_date else "partial"
                coverage[community.name] = CollectionCoverage(
                    community=community.name,
                    requested_start=scope.start_date,
                    requested_end=scope.end_date,
                    actual_start=actual_start,
                    actual_end=actual_end,
                    status=coverage_status,
                    scanned_posts=len(community_candidates),
                )
            effective_limit = scope.deep_read_limit_per_community if scope else min(shortlist_limit, 30)
            if effective_limit is None:
                shortlist = score_stratified_shortlist(
                    community_candidates, limit=max(1, len(community_candidates))
                ) if community_candidates else ()
            else:
                shortlist = (
                    score_stratified_shortlist(community_candidates, limit=effective_limit)
                    if scope else score_shortlist(community_candidates, limit=effective_limit)
                )
            shortlisted_targets.extend(
                (community.name, entry)
                for entry in shortlist
            )
        shortlisted = [entry for _, entry in shortlisted_targets]
        if not deep_read:
            if progress is not None:
                progress({
                    "stage": "collected",
                    "completed": len(communities),
                    "total": len(communities),
                    "message": "帖子列表采集完成。",
                })
            return CollectionResult(tuple(candidates), tuple(shortlisted), (), tuple(failures), coverage)

        deep_reads: list[ThreadDocument] = []
        if progress is not None:
            progress({
                "stage": "deep_read",
                "completed": 0,
                "total": len(shortlisted_targets),
                "message": "正在获取高信号帖子的正文和评论。",
            })
        if scope is not None and scope.depth == "complete":
            self._prefetch_complete_batches(shortlisted_targets, paths=paths, progress=progress)
        for position, (community_name, entry) in enumerate(shortlisted_targets):
            checkpoint = paths.checkpoints_dir / f"{entry.post.post_id}.json"
            prior = self._successful_checkpoints.get(checkpoint)
            if prior is None:
                prior = _read_checkpoint(checkpoint)
                if prior is not None and prior.get("status") == "success":
                    self._successful_checkpoints[checkpoint] = prior
            if prior is not None and prior.get("status") == "success":
                if isinstance(prior.get("thread"), (Mapping, list)):
                    persist_thread(paths, entry.post.post_id, prior["thread"])
                deep_reads.append(_thread_from_checkpoint(prior, entry.post))
                if progress is not None:
                    progress({
                        "stage": "deep_read",
                        "completed": position + 1,
                        "total": len(shortlisted_targets),
                        "community": community_name,
                        "message": f"已完成 {position + 1}/{len(shortlisted_targets)} 篇深读。",
                    })
                continue
            if position:
                self._sleeper(self._settings.request_interval_seconds)
            try:
                raw_text = self._runner(_read_command(
                    entry.post.post_id, self._settings,
                    complete=bool(scope and scope.depth == "complete"),
                ))
                raw_thread = _parse_json(raw_text)
                thread = _thread_from_raw(raw_thread, entry.post)
                persist_thread(paths, entry.post.post_id, raw_thread)
                success_document = {"status": "success", "thread": raw_thread}
                _write_checkpoint(checkpoint, success_document)
                self._successful_checkpoints[checkpoint] = success_document
                deep_reads.append(thread)
            except CollectionCancelled:
                raise
            except Exception as error:
                failure = CollectionFailure(
                    community=community_name,
                    post_id=entry.post.post_id,
                    stage="deep_read",
                    message=_safe_error(error),
                )
                self._successful_checkpoints.pop(checkpoint, None)
                _write_checkpoint(
                    checkpoint,
                    {
                        "community": failure.community,
                        "status": "failed",
                        "post_id": entry.post.post_id,
                        "stage": failure.stage,
                        "message": failure.message,
                    },
                )
                failures.append(failure)
                append_failure(paths, {
                    "community": failure.community,
                    "post_id": failure.post_id,
                    "stage": failure.stage,
                    "error_type": type(error).__name__,
                    "retryable": True,
                })
            if progress is not None:
                progress({
                    "stage": "deep_read",
                    "completed": position + 1,
                    "total": len(shortlisted_targets),
                    "community": community_name,
                    "message": f"已完成 {position + 1}/{len(shortlisted_targets)} 篇深读。",
                })
        write_normalized_records(
            paths,
            [thread.post for thread in deep_reads],
            [
                {"post_id": thread.post.post_id, "parent_id": "", "depth": 1, **asdict(comment)}
                for thread in deep_reads for comment in thread.comments
            ],
        )
        return CollectionResult(tuple(candidates), tuple(shortlisted), tuple(deep_reads), tuple(failures), coverage)

    def load_from_raw(
        self,
        communities: Iterable[Community],
        *,
        paths: RunPaths,
        as_of: datetime,
        shortlist_limit: int = 30,
        scope: CollectionScope | None = None,
    ) -> CollectionResult:
        """Rebuild a collection result from already saved raw files.

        Resume must not call Chrome again after the collection stage has
        completed. This also lets a long-running analysis survive a terminal
        or browser interruption without replacing valid evidence with an
        empty collection result.
        """
        communities = tuple(communities)
        records_by_community: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        failures: list[CollectionFailure] = []
        for community in communities:
            listing_paths = sorted(paths.raw_listings_dir.glob(f"{_safe_path_component(community.name)}__*.json"))
            if not listing_paths:
                failures.append(CollectionFailure(community.name, None, "listing:raw", "已完成采集但找不到原始列表文件"))
                continue
            for listing_path in listing_paths:
                surface = listing_path.stem.split("__", 1)[-1]
                try:
                    records = _parse_records(listing_path.read_text(encoding="utf-8"))
                    for record in records:
                        item = dict(record)
                        row_surfaces = item.pop("source_surfaces", ())
                        if isinstance(row_surfaces, list) and row_surfaces:
                            for row_surface in row_surfaces:
                                records_by_community[community.name].append({**item, "source_surface": str(row_surface)})
                        else:
                            item["source_surface"] = str(item.get("source_surface") or surface)
                            records_by_community[community.name].append(item)
                except Exception as error:
                    failures.append(CollectionFailure(community.name, None, f"listing:raw:{surface}", _safe_error(error)))

        candidates: list[WindowedPost] = []
        shortlisted_targets: list[tuple[str, ShortlistedPost]] = []
        coverage: dict[str, CollectionCoverage] = {}
        for community in communities:
            normalized = normalize_and_deduplicate(records_by_community.get(community.name, ()))
            community_candidates = window_posts(
                normalized,
                as_of=as_of,
                start_date=scope.start_date if scope else None,
                end_date=scope.end_date if scope else None,
            )
            candidates.extend(community_candidates)
            if scope is not None:
                dates = sorted(item.post.created_at.date() for item in community_candidates)
                coverage[community.name] = CollectionCoverage(
                    community=community.name,
                    requested_start=scope.start_date,
                    requested_end=scope.end_date,
                    actual_start=dates[0] if dates else None,
                    actual_end=dates[-1] if dates else None,
                    status="complete" if dates and dates[0] <= scope.start_date else "partial",
                    scanned_posts=len(community_candidates),
                )
            effective_limit = scope.deep_read_limit_per_community if scope else min(shortlist_limit, 30)
            if effective_limit is None:
                shortlist = score_stratified_shortlist(
                    community_candidates, limit=max(1, len(community_candidates))
                ) if community_candidates else ()
            else:
                shortlist = score_stratified_shortlist(community_candidates, limit=effective_limit) if scope else score_shortlist(community_candidates, limit=effective_limit)
            shortlisted_targets.extend((community.name, entry) for entry in shortlist)

        shortlisted = [entry for _, entry in shortlisted_targets]
        deep_reads: list[ThreadDocument] = []
        for community_name, entry in shortlisted_targets:
            thread_path = paths.raw_threads_dir / f"{entry.post.post_id.removeprefix('t3_')}.json"
            if not thread_path.exists():
                failures.append(CollectionFailure(community_name, entry.post.post_id, "deep_read:raw", "已完成采集但找不到原始帖子文件"))
                continue
            try:
                deep_reads.append(_thread_from_raw(json.loads(thread_path.read_text(encoding="utf-8")), entry.post))
            except Exception as error:
                failures.append(CollectionFailure(community_name, entry.post.post_id, "deep_read:raw", _safe_error(error)))
        write_normalized_records(
            paths,
            [thread.post for thread in deep_reads],
            [{"post_id": thread.post.post_id, "parent_id": "", "depth": 1, **asdict(comment)} for thread in deep_reads for comment in thread.comments],
        )
        return CollectionResult(tuple(candidates), tuple(shortlisted), tuple(deep_reads), tuple(failures), coverage)

    def collect_round_two(
        self,
        terms: Iterable[str], *, paths: RunPaths, as_of: datetime,
        existing_candidates: Iterable[WindowedPost] = (), max_posts_per_term: int | None = None,
        max_terms: int | None = None, scope: CollectionScope | None = None,
        deep_read: bool = False, existing_deep_reads: Iterable[ThreadDocument] = (),
        progress: ProgressReporter | None = None,
        post_filter: Callable[[WindowedPost], bool] | None = None,
        allowed_communities: Sequence[str] | None = None,
    ) -> RoundTwoCollectionResult:
        """Search exploratory terms through the exact window and optionally deep-read every addition."""
        selected_terms = tuple(dict.fromkeys(term.strip() for term in terms if isinstance(term, str) and term.strip()))
        if max_terms is not None:
            selected_terms = selected_terms[:max_terms]
        if max_posts_per_term is not None and max_posts_per_term < 1:
            raise ValueError("max_posts_per_term must be at least one")
        checkpoint_path = paths.checkpoints_dir / "round_two.json"
        signature = json.dumps({
            "selected_terms": selected_terms,
            "max_posts_per_term": max_posts_per_term,
            "start_date": scope.start_date.isoformat() if scope else None,
            "end_date": scope.end_date.isoformat() if scope else None,
        }, sort_keys=True)
        checkpoint = _read_checkpoint(checkpoint_path) or {}
        # Query checkpoints are keyed by normalized term, so adding newly
        # promoted terms in the same run must not re-run prior successful
        # searches merely because the overall signature grew.
        reusable = checkpoint
        queries = reusable.get("queries") if isinstance(reusable.get("queries"), Mapping) else {}
        stored_records = reusable.get("records") if isinstance(reusable.get("records"), list) else []
        stored_coverage = reusable.get("coverage") if isinstance(reusable.get("coverage"), Mapping) else {}
        records: list[Mapping[str, Any]] = [item for item in stored_records if isinstance(item, Mapping)]
        terms_to_run = tuple(
            term for term in selected_terms
            if not isinstance(queries.get(term), Mapping) or queries[term].get("status") != "success"
        )
        failures: list[CollectionFailure] = []
        current_queries: dict[str, dict[str, str]] = {
            term: {"status": "success"} for term in selected_terms
            if isinstance(queries.get(term), Mapping) and queries[term].get("status") == "success"
        }
        coverage: dict[str, dict[str, Any]] = {
            str(term): dict(value)
            for term, value in stored_coverage.items()
            if isinstance(value, Mapping) and str(term) in selected_terms
        }
        for term in current_queries:
            if term not in coverage:
                prior_rows = [item for item in records if str(item.get("source_surface") or "") == f"keyword:{term}"]
                coverage[term] = _keyword_coverage(prior_rows, scope)
        failed_terms = 0
        for position, term in enumerate(terms_to_run):
            if position:
                self._sleeper(self._settings.request_interval_seconds)
            try:
                cached_search = paths.raw_searches_dir / f"keyword__{_safe_path_component(term)}.json"
                if cached_search.exists():
                    raw_text = cached_search.read_text(encoding="utf-8")
                else:
                    raw_text = self._runner(_keyword_search_command(term, max_posts_per_term, scope=scope))
                    _write_raw_listing(paths.raw_searches_dir, "keyword", _safe_path_component(term), raw_text)
                parsed = _parse_records(raw_text)
                records.extend({**dict(record), "source_surface": f"keyword:{term}"} for record in parsed)
                current_queries[term] = {"status": "success"}
                coverage[term] = _keyword_coverage(parsed, scope)
            except CollectionCancelled:
                raise
            except Exception as error:
                failed_terms += 1
                failure = CollectionFailure("", None, f"keyword:{term}", _safe_error(error))
                failures.append(failure)
                append_failure(paths, {
                    "community": failure.community,
                    "post_id": failure.post_id,
                    "stage": failure.stage,
                    "error_type": type(error).__name__,
                    "retryable": True,
                })
                current_queries[term] = {"status": "failed", "message": failure.message}
                coverage[term] = {
                    "status": "incomplete",
                    "requested_start": scope.start_date.isoformat() if scope else None,
                    "requested_end": scope.end_date.isoformat() if scope else None,
                    "actual_start": None,
                    "actual_end": None,
                    "pages_scanned": 0,
                    "hit_count": 0,
                    "stop_reason": "provider_error",
                }
            _write_checkpoint(checkpoint_path, {
                "candidate_signature": signature, "selected_terms": list(selected_terms),
                "queries": current_queries, "coverage": coverage, "records": records,
            })
            if progress is not None:
                progress({
                    "stage": "keyword_search",
                    "completed": position + 1,
                    "total": len(terms_to_run),
                    "message": f"已完成 {position + 1}/{len(terms_to_run)} 个全站关键词检索" + (f"，其中 {failed_terms} 个待重试。" if failed_terms else "。"),
                })
        _write_checkpoint(checkpoint_path, {
            "candidate_signature": signature, "selected_terms": list(selected_terms),
            "queries": current_queries, "coverage": coverage, "records": records,
        })
        normalized = normalize_and_deduplicate(records)
        additions = window_posts(
            normalized, as_of=as_of,
            start_date=scope.start_date if scope else None,
            end_date=scope.end_date if scope else None,
        )
        merged: dict[str, WindowedPost] = {item.post.post_id: item for item in existing_candidates}
        for item in additions:
            merged.setdefault(item.post.post_id, item)
        ordered = tuple(merged[key] for key in merged)
        deep_reads_by_id = {item.post.post_id: item for item in existing_deep_reads}
        if deep_read:
            allowed = {str(name).strip().casefold() for name in (allowed_communities or ()) if str(name).strip()}
            targets = [
                item for item in ordered
                if item.post.post_id not in deep_reads_by_id
                and (post_filter is None or post_filter(item))
                and (not allowed or item.post.subreddit.casefold() in allowed)
            ]
            # Keyword discovery can return hundreds of rows. Honour the
            # user's selected depth for normal runs instead of attempting a
            # full thread read for every search hit. Complete mode remains
            # date-bounded and intentionally has no business-side cap.
            if scope is not None and scope.deep_read_limit_per_community is not None:
                limit = scope.deep_read_limit_per_community
                existing_by_community = defaultdict(int)
                for item in deep_reads_by_id.values():
                    existing_by_community[item.post.subreddit.casefold()] += 1
                selected_targets: list[WindowedPost] = []
                for item in targets:
                    key = item.post.subreddit.casefold()
                    if existing_by_community[key] >= limit:
                        continue
                    selected_targets.append(item)
                    existing_by_community[key] += 1
                targets = selected_targets
            if scope is not None and scope.depth == "complete":
                self._prefetch_complete_batches(
                    tuple((item.post.subreddit, item) for item in targets),
                    paths=paths,
                    progress=progress,
                )
            for position, item in enumerate(targets):
                checkpoint_path = paths.checkpoints_dir / f"{item.post.post_id}.json"
                checkpoint = _read_checkpoint(checkpoint_path) or {}
                try:
                    if checkpoint.get("status") == "success" and isinstance(checkpoint.get("thread"), (Mapping, list)):
                        raw_thread = checkpoint["thread"]
                    else:
                        if position:
                            self._sleeper(self._settings.request_interval_seconds)
                        raw_thread = _parse_json(self._runner(_read_command(
                            item.post.post_id, self._settings,
                            complete=bool(scope and scope.depth == "complete"),
                        )))
                        persist_thread(paths, item.post.post_id, raw_thread)
                        _write_checkpoint(checkpoint_path, {"status": "success", "thread": raw_thread})
                    deep_reads_by_id[item.post.post_id] = _thread_from_raw(raw_thread, item.post)
                except CollectionCancelled:
                    raise
                except Exception as error:
                    failure = CollectionFailure(item.post.subreddit, item.post.post_id, "deep_read", _safe_error(error))
                    failures.append(failure)
                    _write_checkpoint(checkpoint_path, {
                        "status": "failed", "community": item.post.subreddit,
                        "post_id": item.post.post_id, "stage": "deep_read", "message": failure.message,
                    })
                if progress is not None:
                    progress({
                        "stage": "keyword_deep_read",
                        "completed": position + 1,
                        "total": len(targets),
                        "message": f"已完成 {position + 1}/{len(targets)} 篇全站搜索帖子深读。",
                    })
        deep_reads = tuple(deep_reads_by_id.values())
        if deep_read:
            write_normalized_records(
                paths,
                [thread.post for thread in deep_reads],
                [{"post_id": thread.post.post_id, "parent_id": "", "depth": 1, **asdict(comment)} for thread in deep_reads for comment in thread.comments],
            )
        return RoundTwoCollectionResult(ordered, tuple(failures), selected_terms, deep_reads, coverage)


def _keyword_coverage(records: Sequence[Mapping[str, Any]], scope: CollectionScope | None) -> dict[str, Any]:
    """Summarise a single global-search query without claiming full Reddit coverage."""
    dates: list[Any] = []
    pages = 0
    hints: set[str] = set()
    for record in records:
        try:
            timestamp = float(record.get("created_utc"))
        except (TypeError, ValueError):
            continue
        dates.append(datetime.fromtimestamp(timestamp, tz=UTC).date())
        try:
            pages = max(pages, int(record.get("pages_scanned") or 0))
        except (TypeError, ValueError):
            pass
        hint = str(record.get("coverage_status") or "").strip().casefold()
        if hint:
            hints.add(hint)
    actual_start = min(dates).isoformat() if dates else None
    actual_end = max(dates).isoformat() if dates else None
    if "partial" in hints:
        status = "partial"
    elif "complete" in hints or (scope is not None and dates and min(dates) <= scope.start_date):
        status = "complete"
    else:
        status = "partial"
    return {
        "status": status,
        "requested_start": scope.start_date.isoformat() if scope else None,
        "requested_end": scope.end_date.isoformat() if scope else None,
        "actual_start": actual_start,
        "actual_end": actual_end,
        "pages_scanned": pages,
        "hit_count": len(records),
        "stop_reason": "date_boundary_or_exhausted" if status == "complete" else "coverage_boundary_not_reached",
    }


def _listing_commands(community: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    common = ("-f", "json", "--window", "foreground", "--site-session", "persistent")
    return (
        ("hot", ("opencli", "reddit", "subreddit", community, "--sort", "hot", "--limit", "50", *common)),
        ("top_month", ("opencli", "reddit", "subreddit", community, "--sort", "top", "--time", "month", "--limit", "50", *common)),
        ("top_year", ("opencli", "reddit", "subreddit", community, "--sort", "top", "--time", "year", "--limit", "100", *common)),
        ("new", ("opencli", "reddit", "subreddit", community, "--sort", "new", "--limit", "50", *common)),
    )


def _range_command(community: str, scope: CollectionScope) -> tuple[str, ...]:
    command = (
        "opencli", "opportunity-reddit", "range", community,
        "--start-date", scope.start_date.isoformat(), "--end-date", scope.end_date.isoformat(),
    )
    if scope.listing_limit_per_community is not None:
        command += ("--limit", str(scope.listing_limit_per_community))
    return command + ("-f", "json", "--window", "foreground", "--site-session", "persistent")


def _keyword_search_command(term: str, limit: int | None, *, scope: CollectionScope | None = None) -> tuple[str, ...]:
    if scope is not None:
        command = (
            "opencli", "opportunity-reddit", "search-range", term,
            "--start-date", scope.start_date.isoformat(), "--end-date", scope.end_date.isoformat(),
        )
        if limit is not None:
            command += ("--max-pages", str(max(1, (limit + 99) // 100)),)
        return command + ("-f", "json", "--window", "foreground", "--site-session", "persistent")
    command = ("opencli", "reddit", "search", term)
    if limit is not None:
        command += ("--limit", str(limit))
    return command + ("-f", "json", "--window", "foreground", "--site-session", "persistent")


def _read_command(post_id: str, settings: CollectionSettings, *, complete: bool = False) -> tuple[str, ...]:
    command = (
        "opencli", "opportunity-reddit", "read", post_id.removeprefix("t3_"), "-f", "json",
        "--window", "foreground", "--site-session", "persistent", "--sort", "best",
    )
    if complete:
        return command + ("--complete", "true", "--max-length", str(settings.max_comment_length))
    return command + (
        "--limit", str(settings.comments_per_post), "--depth", str(settings.comment_depth),
        "--replies", str(settings.replies_per_comment),
        "--expand-rounds", str(settings.expand_rounds), "--max-length", str(settings.max_comment_length),
    )


def _batch_read_command(post_ids: Sequence[str], settings: CollectionSettings) -> tuple[str, ...]:
    return (
        "opencli", "opportunity-reddit", "batch-read",
        ",".join(str(post_id).removeprefix("t3_") for post_id in post_ids),
        "-f", "json", "--window", "foreground", "--site-session", "persistent",
        "--max-length", str(settings.max_comment_length),
    )


def _parse_records(raw_text: str) -> list[Mapping[str, Any]]:
    document = _parse_json(raw_text)
    if isinstance(document, list) and all(isinstance(item, Mapping) for item in document):
        return list(document)
    if isinstance(document, Mapping):
        children = document.get("data", {}).get("children", []) if isinstance(document.get("data"), Mapping) else []
        if isinstance(children, list) and all(isinstance(item, Mapping) and isinstance(item.get("data"), Mapping) for item in children):
            return [item["data"] for item in children]
    raise ValueError("OpenCLI listing response must be a JSON list")


def _parse_json(raw_text: str) -> Any:
    if not isinstance(raw_text, str):
        raise ValueError("OpenCLI response must be text")
    return json.loads(raw_text)


def _write_raw_listing(raw_dir: Path, community: str, surface: str, raw_text: str) -> None:
    directory = raw_dir if raw_dir.name == "searches" else raw_dir / "listings"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_path_component(community)}__{surface}.json"
    (directory / filename).write_text(raw_text, encoding="utf-8")
    # Keep the legacy raw/listings projection for existing users and fixtures.
    if raw_dir.name == "searches":
        legacy = raw_dir.parent / "listings"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / filename).write_text(raw_text, encoding="utf-8")


def _read_checkpoint(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        return None
    return value


def _write_checkpoint(path: Path, document: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _thread_from_checkpoint(document: Mapping[str, Any], post: Any) -> ThreadDocument:
    return _thread_from_raw(document.get("thread", []), post)


def _thread_from_raw(document: Any, post: Any) -> ThreadDocument:
    records = document if isinstance(document, list) else document.get("comments", []) if isinstance(document, Mapping) else []
    if not isinstance(records, list):
        raise ValueError("OpenCLI deep-read response must contain comments")
    comments: list[ThreadComment] = []
    for position, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body", record.get("text"))
        if not isinstance(body, str) or not body.strip():
            continue
        identifier = record.get("id")
        comment_id = identifier.strip() if isinstance(identifier, str) and identifier.strip() else f"comment_{position + 1}"
        url = record.get("url", record.get("permalink"))
        comment_url = url if isinstance(url, str) and url.strip() else f"{post.url}?comment={comment_id}"
        author = record.get("author")
        comment_author = author.strip() if isinstance(author, str) else ""
        parent_id = str(record.get("parent_id", "") or "")
        try:
            depth = max(1, int(record.get("depth", 1) or 1))
            score = int(record.get("score", 0) or 0)
        except (TypeError, ValueError):
            depth, score = 1, 0
        comments.append(ThreadComment(comment_id, body.strip(), comment_url, comment_author, parent_id, depth, score))
    return ThreadDocument(post=post, comments=tuple(comments))


def _safe_path_component(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def _safe_error(error: BaseException) -> str:
    return f"{type(error).__name__}: external operation failed"
