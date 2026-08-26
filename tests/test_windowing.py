from datetime import UTC, datetime

import opportunity_radar


def _post(post_id: str, created_at: datetime) -> object:
    return opportunity_radar.NormalizedPost(
        post_id=post_id,
        url=f"https://www.reddit.com/r/powerstroke/comments/{post_id}/example",
        subreddit="powerstroke",
        title="Example",
        body="Body",
        author="owner",
        created_at=created_at,
        score=0,
        comment_count=0,
        source_surfaces=("hot",),
    )


def test_windowing_labels_current_and_baseline_and_drops_posts_older_than_90_days() -> None:
    """An off-by-one window or retained old post corrupts trend comparisons."""
    as_of = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    windowed = opportunity_radar.window_posts(
        (
            _post("current", datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
            _post("baseline", datetime(2026, 7, 31, 12, 0, tzinfo=UTC)),
            _post("edge", datetime(2026, 6, 2, 12, 0, tzinfo=UTC)),
            _post("old", datetime(2026, 6, 1, 12, 0, tzinfo=UTC)),
        ),
        as_of=as_of,
    )

    assert [(entry.post.post_id, entry.window) for entry in windowed] == [
        ("current", opportunity_radar.PostWindow.CURRENT),
        ("baseline", opportunity_radar.PostWindow.BASELINE),
        ("edge", opportunity_radar.PostWindow.BASELINE),
    ]


def test_windowing_excludes_future_timestamps() -> None:
    """Treating a future-dated listing as current introduces invalid evidence."""
    as_of = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    windowed = opportunity_radar.window_posts(
        (_post("future", datetime(2026, 9, 1, 12, 0, tzinfo=UTC)),), as_of=as_of
    )

    assert windowed == ()
