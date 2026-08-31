"""Fixed 30-day current and 31-90-day baseline windows."""

from collections.abc import Iterable
from datetime import date, datetime

from .models import NormalizedPost, PostWindow, WindowedPost

CURRENT_WINDOW_DAYS = 30
TOTAL_WINDOW_DAYS = 90


def window_posts(
    posts: Iterable[NormalizedPost], *, as_of: datetime,
    start_date: date | None = None, end_date: date | None = None,
) -> tuple[WindowedPost, ...]:
    """Label posts in either the legacy 90-day or an exact selected date range."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    windowed: list[WindowedPost] = []
    selected_end = end_date or as_of.date()
    for post in posts:
        if post.created_at.tzinfo is None:
            raise ValueError("post timestamps must be timezone-aware")
        post_date = post.created_at.date()
        if start_date is not None and post_date < start_date:
            continue
        if end_date is not None and post_date > end_date:
            continue
        age_days = (as_of - post.created_at).total_seconds() / 86_400
        if age_days < 0:
            continue
        if start_date is not None or end_date is not None:
            days_from_selected_end = (selected_end - post_date).days
            if days_from_selected_end < 0:
                continue
            window = PostWindow.CURRENT if days_from_selected_end <= CURRENT_WINDOW_DAYS else PostWindow.BASELINE
            windowed.append(WindowedPost(post=post, window=window))
        elif age_days <= CURRENT_WINDOW_DAYS:
            windowed.append(WindowedPost(post=post, window=PostWindow.CURRENT))
        elif age_days <= TOTAL_WINDOW_DAYS:
            windowed.append(WindowedPost(post=post, window=PostWindow.BASELINE))
    return tuple(windowed)
