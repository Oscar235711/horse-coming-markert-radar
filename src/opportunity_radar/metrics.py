"""Canonical report counts shared by JSON, HTML, and Excel projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .collector import CollectionResult, ThreadDocument


def _name(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"[deleted]", "deleted", "none"} else text


def _topic_post_ids(topic: Mapping[str, Any]) -> set[str]:
    ids = {str(value) for value in topic.get("post_ids", []) if value}
    for evidence in topic.get("evidence", []):
        if isinstance(evidence, Mapping) and evidence.get("post_id"):
            ids.add(str(evidence["post_id"]))
    return ids


def _evidence_keys(topics: Sequence[Mapping[str, Any]]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for topic in topics:
        for evidence in topic.get("evidence", []):
            if not isinstance(evidence, Mapping):
                continue
            key = (
                str(evidence.get("post_id", "")),
                str(evidence.get("evidence_id", "")),
                str(evidence.get("url", "")),
            )
            if any(key):
                result.add(key)
    return result


def _counts_for(
    community: str | None,
    *,
    collection: CollectionResult,
    analyzed_threads: Sequence[ThreadDocument],
    topics: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    target = community.casefold() if community else None

    def matches(value: Any) -> bool:
        return target is None or str(value or "").casefold() == target

    candidate_posts = {
        item.post.post_id: item.post
        for item in collection.candidates
        if matches(item.post.subreddit)
    }
    deep_threads = {
        thread.post.post_id: thread
        for thread in collection.deep_reads
        if matches(thread.post.subreddit)
    }
    analyzed = {
        thread.post.post_id: thread
        for thread in analyzed_threads
        if matches(thread.post.subreddit)
    }
    scoped_topics = [topic for topic in topics if matches(topic.get("community"))]
    topic_posts: set[str] = set()
    for topic in scoped_topics:
        topic_posts.update(_topic_post_ids(topic))

    post_authors = {
        author.casefold()
        for thread in analyzed.values()
        if (author := _name(thread.post.author))
    }
    commenters = {
        author.casefold()
        for thread in analyzed.values()
        for author in thread.comment_authors
        if _name(author)
    }
    return {
        "topic_count": len(scoped_topics),
        "formal_topic_count": sum(topic.get("status") == "formal" for topic in scoped_topics),
        "weak_topic_count": sum(topic.get("status") == "weak_signal" for topic in scoped_topics),
        "scanned_post_count": len(candidate_posts),
        "deep_read_post_count": len(deep_threads),
        "analyzed_post_count": len(analyzed),
        "topic_post_count": len(topic_posts),
        "post_author_count": len(post_authors),
        "commenter_count": len(commenters),
        "participant_count": len(post_authors | commenters),
        "collected_comment_count": sum(len(thread.comments) for thread in deep_threads.values()),
        "evidence_count": len(_evidence_keys(scoped_topics)),
    }


def build_report_metrics(
    *,
    communities: Sequence[str],
    collection: CollectionResult,
    analyzed_threads: Sequence[ThreadDocument],
    topics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one deduplicated metrics object consumed by every output format."""
    community_names = tuple(dict.fromkeys(str(name) for name in communities if name))
    metrics: dict[str, Any] = _counts_for(
        None,
        collection=collection,
        analyzed_threads=analyzed_threads,
        topics=topics,
    )
    metrics["community_count"] = len(community_names)
    metrics["communities"] = {
        name: _counts_for(
            name,
            collection=collection,
            analyzed_threads=analyzed_threads,
            topics=topics,
        )
        for name in community_names
    }
    return metrics

