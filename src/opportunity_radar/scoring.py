"""Reproducible prioritization for the per-community deep-read shortlist."""

from collections import defaultdict
from collections.abc import Iterable
import re

from .models import PostWindow, ShortlistedPost, WindowedPost


def score_shortlist(
    posts: Iterable[WindowedPost], *, limit: int = 30
) -> tuple[ShortlistedPost, ...]:
    """Return up to ``limit`` highest-priority posts for every community."""
    if limit < 1:
        raise ValueError("shortlist limit must be at least one")

    by_community: dict[str, list[ShortlistedPost]] = defaultdict(list)
    for windowed in posts:
        by_community[windowed.post.subreddit.casefold()].append(
            ShortlistedPost(
                post=windowed.post,
                window=windowed.window,
                priority_score=_priority_score(windowed),
            )
        )

    selected: list[ShortlistedPost] = []
    for community in sorted(by_community):
        ranked = sorted(
            by_community[community],
            key=lambda entry: (
                -entry.priority_score,
                -entry.post.score,
                -entry.post.comment_count,
                entry.post.post_id,
            ),
        )
        selected.extend(ranked[:limit])
    return tuple(selected)


def score_stratified_shortlist(
    posts: Iterable[WindowedPost], *, limit: int
) -> tuple[ShortlistedPost, ...]:
    """Mix strong, monthly, specific, and controversial evidence deterministically."""
    if limit < 1:
        raise ValueError("shortlist limit must be at least one")
    by_community: dict[str, list[ShortlistedPost]] = defaultdict(list)
    for item in posts:
        by_community[item.post.subreddit.casefold()].append(
            ShortlistedPost(item.post, item.window, _priority_score(item))
        )

    selected: list[ShortlistedPost] = []
    for community in sorted(by_community):
        candidates = by_community[community]
        ranked = sorted(candidates, key=_rank_key)
        chosen: dict[str, ShortlistedPost] = {}

        def take(entries: Iterable[ShortlistedPost], count: int) -> None:
            for entry in entries:
                if len(chosen) >= limit or count <= 0:
                    break
                if entry.post.post_id in chosen:
                    continue
                chosen[entry.post.post_id] = entry
                count -= 1

        controversial_quota = max(1, round(limit * 0.10))
        specific_quota = max(1, round(limit * 0.15))
        monthly_quota = max(1, round(limit * 0.25))
        take((entry for entry in ranked if "controversial" in entry.post.source_surfaces), controversial_quota)

        by_month: dict[tuple[int, int], list[ShortlistedPost]] = defaultdict(list)
        for entry in ranked:
            by_month[(entry.post.created_at.year, entry.post.created_at.month)].append(entry)
        monthly_round_robin: list[ShortlistedPost] = []
        month_keys = sorted(by_month, reverse=True)
        offset = 0
        while month_keys:
            remaining = []
            for key in month_keys:
                entries = by_month[key]
                if offset < len(entries):
                    monthly_round_robin.append(entries[offset])
                if offset + 1 < len(entries):
                    remaining.append(key)
            month_keys = remaining
            offset += 1
        take(monthly_round_robin, monthly_quota)
        take(sorted(ranked, key=lambda entry: (-_specificity_score(entry), *_rank_key(entry))), specific_quota)
        take(ranked, max(0, round(limit * 0.50)))
        take(ranked, limit)
        selected.extend(chosen.values())
    return tuple(selected)


def _rank_key(entry: ShortlistedPost) -> tuple[float, int, int, str]:
    return (-entry.priority_score, -entry.post.score, -entry.post.comment_count, entry.post.post_id)


def _specificity_score(entry: ShortlistedPost) -> int:
    text = f"{entry.post.title} {entry.post.body}".casefold()
    signals = re.findall(
        r"\b(?:fail(?:ed|ure)?|broken|leak|fitment|install|replace|repair|towing|haul|price|cost|which|help|problem|issue)\b",
        text,
    )
    return len(signals)


def _priority_score(windowed: WindowedPost) -> float:
    post = windowed.post
    recency = 60.0 if windowed.window is PostWindow.CURRENT else 0.0
    upvotes = min(post.score, 100) * 0.30
    comments = min(post.comment_count, 100) * 0.10
    return round(recency + upvotes + comments, 2)
