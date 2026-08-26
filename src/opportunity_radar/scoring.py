"""Reproducible prioritization for the per-community deep-read shortlist."""

from collections import defaultdict
from collections.abc import Iterable

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


def _priority_score(windowed: WindowedPost) -> float:
    post = windowed.post
    recency = 60.0 if windowed.window is PostWindow.CURRENT else 0.0
    upvotes = min(post.score, 100) * 0.30
    comments = min(post.comment_count, 100) * 0.10
    return round(recency + upvotes + comments, 2)
