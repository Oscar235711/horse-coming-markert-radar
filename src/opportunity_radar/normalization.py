"""Canonicalize external Reddit listings before analysis."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import NormalizedPost


def normalize_and_deduplicate(records: Iterable[Mapping[str, Any]]) -> tuple[NormalizedPost, ...]:
    """Normalize listing records and merge repeated posts deterministically."""
    grouped_by_id: dict[str, list[NormalizedPost]] = {}
    for record in records:
        post = _normalize_post(record)
        grouped_by_id.setdefault(post.post_id, []).append(post)

    grouped_by_url: dict[str, list[NormalizedPost]] = {}
    for posts_with_id in grouped_by_id.values():
        merged_by_id = _merge_posts(posts_with_id)
        grouped_by_url.setdefault(merged_by_id.url, []).append(merged_by_id)

    merged = (_merge_posts(posts) for posts in grouped_by_url.values())
    return tuple(sorted(merged, key=lambda post: (post.created_at, post.post_id), reverse=True))


def _normalize_post(record: Mapping[str, Any]) -> NormalizedPost:
    raw_id = _required_text(record, "name", fallback="id")
    post_id = raw_id if raw_id.startswith("t3_") else f"t3_{raw_id}"
    raw_url = _required_text(record, "permalink", fallback="url")
    url = _canonical_url(raw_url)
    subreddit = _required_text(record, "subreddit", fallback="subreddit_name_prefixed")
    subreddit = subreddit.removeprefix("r/")
    author = _optional_text(record.get("author"))
    return NormalizedPost(
        post_id=post_id,
        url=url,
        subreddit=subreddit,
        title=_clean_text(_required_text(record, "title")),
        body=_clean_text(str(record.get("selftext", record.get("body", "")))),
        author=author,
        created_at=_parse_timestamp(record.get("created_utc", record.get("created_at"))),
        score=_as_non_negative_int(record.get("score", record.get("ups", 0))),
        comment_count=_as_non_negative_int(record.get("num_comments", record.get("comment_count", 0))),
        source_surfaces=(_required_text(record, "source_surface"),),
    )


def _merge_posts(posts: list[NormalizedPost]) -> NormalizedPost:
    selected = max(
        posts,
        key=lambda post: (
            len(post.body),
            post.body,
            post.score,
            post.comment_count,
            post.url,
            post.post_id,
            post.title,
            post.author or "",
            post.created_at,
            post.subreddit,
        ),
    )
    return NormalizedPost(
        post_id=selected.post_id,
        url=selected.url,
        subreddit=selected.subreddit,
        title=selected.title,
        body=selected.body,
        author=selected.author,
        created_at=selected.created_at,
        score=max(post.score for post in posts),
        comment_count=max(post.comment_count for post in posts),
        source_surfaces=tuple(sorted({surface for post in posts for surface in post.source_surfaces})),
    )


def _required_text(record: Mapping[str, Any], key: str, *, fallback: str | None = None) -> str:
    value = record.get(key, record.get(fallback) if fallback else None)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"post record requires {key}")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme:
        parsed = urlsplit(f"https://www.reddit.com{value}")
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", parsed.netloc.lower(), path, "", ""))


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise ValueError("post record requires created_utc or created_at")


def _as_non_negative_int(value: object) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("post scores and comment counts must be numeric") from error
    return max(converted, 0)
