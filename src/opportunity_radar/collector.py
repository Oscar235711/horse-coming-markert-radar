"""Injectable OpenCLI collection with resumable, local post checkpoints."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
    """Bounded keyword-search records, resumable independently from community collection."""

    candidates: tuple[WindowedPost, ...]
    failures: tuple[CollectionFailure, ...]
    selected_terms: tuple[str, ...]


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

    def collect(
        self,
        communities: Iterable[Community],
        *,
        paths: RunPaths,
        as_of: datetime,
        deep_read: bool = False,
        shortlist_limit: int = 30,
        scope: CollectionScope | None = None,
    ) -> CollectionResult:
        """Preserve all list surfaces, then optionally deep-read up to 30 posts/community."""
        if shortlist_limit < 1:
            raise ValueError("shortlist_limit must be at least one")
        communities = tuple(communities)
        records_by_community: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        failures: list[CollectionFailure] = []
        for community in communities:
            commands = (
                (("range", _range_command(community.name, scope)),)
                if scope is not None else _listing_commands(community.name)
            )
            for surface, arguments in commands:
                try:
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
            return CollectionResult(tuple(candidates), tuple(shortlisted), (), tuple(failures), coverage)

        deep_reads: list[ThreadDocument] = []
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
                continue
            if position:
                self._sleeper(self._settings.request_interval_seconds)
            try:
                raw_text = self._runner(_read_command(entry.post.post_id, self._settings))
                raw_thread = _parse_json(raw_text)
                thread = _thread_from_raw(raw_thread, entry.post)
                persist_thread(paths, entry.post.post_id, raw_thread)
                success_document = {"status": "success", "thread": raw_thread}
                _write_checkpoint(checkpoint, success_document)
                self._successful_checkpoints[checkpoint] = success_document
                deep_reads.append(thread)
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
        write_normalized_records(
            paths,
            [thread.post for thread in deep_reads],
            [
                {"post_id": thread.post.post_id, "parent_id": "", "depth": 1, **asdict(comment)}
                for thread in deep_reads for comment in thread.comments
            ],
        )
        return CollectionResult(tuple(candidates), tuple(shortlisted), tuple(deep_reads), tuple(failures), coverage)

    def collect_round_two(
        self,
        terms: Iterable[str], *, paths: RunPaths, as_of: datetime,
        existing_candidates: Iterable[WindowedPost] = (), max_posts_per_term: int = 10,
    ) -> RoundTwoCollectionResult:
        """Search approved exploratory terms once, retrying only failed checkpoint queries on resume."""
        selected_terms = tuple(dict.fromkeys(term.strip() for term in terms if isinstance(term, str) and term.strip()))[:20]
        if max_posts_per_term < 1:
            raise ValueError("max_posts_per_term must be at least one")
        checkpoint_path = paths.checkpoints_dir / "round_two.json"
        signature = json.dumps({"selected_terms": selected_terms, "max_posts_per_term": max_posts_per_term}, sort_keys=True)
        checkpoint = _read_checkpoint(checkpoint_path) or {}
        reusable = checkpoint if checkpoint.get("candidate_signature") == signature else {}
        queries = reusable.get("queries") if isinstance(reusable.get("queries"), Mapping) else {}
        stored_records = reusable.get("records") if isinstance(reusable.get("records"), list) else []
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
        for position, term in enumerate(terms_to_run):
            if position:
                self._sleeper(self._settings.request_interval_seconds)
            try:
                raw_text = self._runner(_keyword_search_command(term, max_posts_per_term))
                _write_raw_listing(paths.raw_searches_dir, "keyword", _safe_path_component(term), raw_text)
                parsed = _parse_records(raw_text)
                records.extend({**dict(record), "source_surface": f"keyword:{term}"} for record in parsed)
                current_queries[term] = {"status": "success"}
            except Exception as error:
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
        _write_checkpoint(checkpoint_path, {
            "candidate_signature": signature, "selected_terms": list(selected_terms),
            "queries": current_queries, "records": records,
        })
        normalized = normalize_and_deduplicate(records)
        additions = window_posts(normalized, as_of=as_of)
        merged: dict[str, WindowedPost] = {item.post.post_id: item for item in existing_candidates}
        for item in additions:
            merged.setdefault(item.post.post_id, item)
        ordered = tuple(merged[key] for key in merged)
        return RoundTwoCollectionResult(ordered, tuple(failures), selected_terms)


def _listing_commands(community: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    common = ("-f", "json", "--window", "foreground", "--site-session", "persistent")
    return (
        ("hot", ("opencli", "reddit", "subreddit", community, "--sort", "hot", "--limit", "50", *common)),
        ("top_month", ("opencli", "reddit", "subreddit", community, "--sort", "top", "--time", "month", "--limit", "50", *common)),
        ("top_year", ("opencli", "reddit", "subreddit", community, "--sort", "top", "--time", "year", "--limit", "100", *common)),
        ("new", ("opencli", "reddit", "subreddit", community, "--sort", "new", "--limit", "50", *common)),
    )


def _range_command(community: str, scope: CollectionScope) -> tuple[str, ...]:
    return (
        "opencli", "opportunity-reddit", "range", community,
        "--start-date", scope.start_date.isoformat(), "--end-date", scope.end_date.isoformat(),
        "--limit", str(scope.listing_limit_per_community), "-f", "json",
        "--window", "foreground", "--site-session", "persistent",
    )


def _keyword_search_command(term: str, limit: int) -> tuple[str, ...]:
    return (
        "opencli", "reddit", "search", term, "--limit", str(limit), "-f", "json",
        "--window", "foreground", "--site-session", "persistent",
    )


def _read_command(post_id: str, settings: CollectionSettings) -> tuple[str, ...]:
    return (
        "opencli", "opportunity-reddit", "read", post_id.removeprefix("t3_"), "-f", "json",
        "--window", "foreground", "--site-session", "persistent", "--sort", "best",
        "--limit", str(settings.comments_per_post), "--depth", str(settings.comment_depth),
        "--replies", str(settings.replies_per_comment),
        "--expand-rounds", str(settings.expand_rounds), "--max-length", str(settings.max_comment_length),
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
