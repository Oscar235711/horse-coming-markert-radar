"""Injectable OpenCLI collection with resumable, local post checkpoints."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

from .models import CollectionSettings, Community, ShortlistedPost, WindowedPost
from .normalization import normalize_and_deduplicate
from .scoring import score_shortlist
from .storage import RunPaths
from .windowing import window_posts

CommandRunner = Callable[[tuple[str, ...]], str]


@dataclass(frozen=True, slots=True)
class ThreadComment:
    """One comment retained from a deep-read response."""

    comment_id: str
    body: str
    url: str
    author: str = ""


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
    ) -> CollectionResult:
        """Preserve all list surfaces, then optionally deep-read up to 30 posts/community."""
        if shortlist_limit < 1:
            raise ValueError("shortlist_limit must be at least one")
        communities = tuple(communities)
        records_by_community: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        failures: list[CollectionFailure] = []
        for community in communities:
            for surface, arguments in _listing_commands(community.name):
                try:
                    raw_text = self._runner(arguments)
                    _write_raw_listing(paths.raw_dir, community.name, surface, raw_text)
                    records = _parse_records(raw_text)
                    for record in records:
                        item = dict(record)
                        item["source_surface"] = surface
                        records_by_community[community.name].append(item)
                except Exception as error:
                    failures.append(
                        CollectionFailure(
                            community=community.name,
                            post_id=None,
                            stage=f"listing:{community.name}:{surface}",
                            message=_safe_error(error),
                        )
                    )

        candidates: list[WindowedPost] = []
        shortlisted_targets: list[tuple[str, ShortlistedPost]] = []
        for community in communities:
            normalized = normalize_and_deduplicate(records_by_community.get(community.name, ()))
            community_candidates = window_posts(normalized, as_of=as_of)
            candidates.extend(community_candidates)
            shortlisted_targets.extend(
                (community.name, entry)
                for entry in score_shortlist(community_candidates, limit=min(shortlist_limit, 30))
            )
        shortlisted = [entry for _, entry in shortlisted_targets]
        if not deep_read:
            return CollectionResult(tuple(candidates), tuple(shortlisted), (), tuple(failures))

        deep_reads: list[ThreadDocument] = []
        for position, (community_name, entry) in enumerate(shortlisted_targets):
            if position:
                self._sleeper(self._settings.request_interval_seconds)
            checkpoint = paths.checkpoints_dir / f"{entry.post.post_id}.json"
            prior = self._successful_checkpoints.get(checkpoint)
            if prior is None:
                prior = _read_checkpoint(checkpoint)
                if prior is not None and prior.get("status") == "success":
                    self._successful_checkpoints[checkpoint] = prior
            if prior is not None and prior.get("status") == "success":
                deep_reads.append(_thread_from_checkpoint(prior, entry.post))
                continue
            try:
                raw_text = self._runner(_read_command(entry.post.post_id, self._settings))
                raw_thread = _parse_json(raw_text)
                thread = _thread_from_raw(raw_thread, entry.post)
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
        return CollectionResult(tuple(candidates), tuple(shortlisted), tuple(deep_reads), tuple(failures))


def _listing_commands(community: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    common = ("-f", "json", "--window", "foreground", "--site-session", "persistent")
    return (
        ("hot", ("opencli", "reddit", "hot", community, "--limit", "50", *common)),
        ("top_month", ("opencli", "reddit", "top", community, "--time", "month", "--limit", "50", *common)),
        ("top_year", ("opencli", "reddit", "top", community, "--time", "year", "--limit", "100", *common)),
        ("new", ("opencli", "reddit", "new", community, "--limit", "50", *common)),
    )


def _read_command(post_id: str, settings: CollectionSettings) -> tuple[str, ...]:
    return (
        "opencli", "reddit", "read", post_id.removeprefix("t3_"), "-f", "json",
        "--window", "foreground", "--site-session", "persistent", "--sort", "best",
        "--limit", str(settings.comments_per_post), "--depth", str(settings.comment_depth),
        "--replies", str(settings.replies_per_comment), "--expand-more", str(settings.expand_more).lower(),
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
    directory = raw_dir / "listings"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{_safe_path_component(community)}__{surface}.json").write_text(raw_text, encoding="utf-8")


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
        body = record.get("body")
        if not isinstance(body, str) or not body.strip():
            continue
        identifier = record.get("id")
        comment_id = identifier.strip() if isinstance(identifier, str) and identifier.strip() else f"comment_{position + 1}"
        url = record.get("permalink")
        comment_url = url if isinstance(url, str) and url.strip() else f"{post.url}?comment={comment_id}"
        author = record.get("author")
        comment_author = author.strip() if isinstance(author, str) else ""
        comments.append(ThreadComment(comment_id, body.strip(), comment_url, comment_author))
    return ThreadDocument(post=post, comments=tuple(comments))


def _safe_path_component(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def _safe_error(error: BaseException) -> str:
    return f"{type(error).__name__}: external operation failed"
