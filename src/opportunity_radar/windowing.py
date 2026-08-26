"""Fixed 30-day current and 31-90-day baseline windows."""

from collections.abc import Iterable
from datetime import datetime

from .models import NormalizedPost, PostWindow, WindowedPost

CURRENT_WINDOW_DAYS = 30
TOTAL_WINDOW_DAYS = 90


def window_posts(
    posts: Iterable[NormalizedPost], *, as_of: datetime
) -> tuple[WindowedPost, ...]:
    """Label eligible posts using inclusive calendar-duration boundaries."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    windowed: list[WindowedPost] = []
    for post in posts:
        if post.created_at.tzinfo is None:
            raise ValueError("post timestamps must be timezone-aware")
        age_days = (as_of - post.created_at).total_seconds() / 86_400
        if age_days < 0:
            continue
        if age_days <= CURRENT_WINDOW_DAYS:
            windowed.append(WindowedPost(post=post, window=PostWindow.CURRENT))
        elif age_days <= TOTAL_WINDOW_DAYS:
            windowed.append(WindowedPost(post=post, window=PostWindow.BASELINE))
    return tuple(windowed)
