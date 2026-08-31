from datetime import UTC, datetime

import opportunity_radar


def _windowed(
    post_id: str, *, window: object, score: int, comment_count: int
) -> object:
    return opportunity_radar.WindowedPost(
        post=opportunity_radar.NormalizedPost(
            post_id=post_id,
            url=f"https://www.reddit.com/r/powerstroke/comments/{post_id}/example",
            subreddit="powerstroke",
            title="Example",
            body="Body",
            author="owner",
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
            score=score,
            comment_count=comment_count,
            source_surfaces=("hot",),
        ),
        window=window,
    )


def test_shortlist_prioritizes_current_discussion_and_breaks_score_ties_by_post_id() -> None:
    """Nondeterministic ordering changes deep-read evidence between identical runs."""
    shortlisted = opportunity_radar.score_shortlist(
        (
            _windowed(
                "t3_z", window=opportunity_radar.PostWindow.BASELINE, score=100, comment_count=100
            ),
            _windowed(
                "t3_b", window=opportunity_radar.PostWindow.CURRENT, score=0, comment_count=0
            ),
            _windowed(
                "t3_a", window=opportunity_radar.PostWindow.CURRENT, score=0, comment_count=0
            ),
            _windowed(
                "t3_current", window=opportunity_radar.PostWindow.CURRENT, score=10, comment_count=5
            ),
        ),
        limit=3,
    )

    assert [entry.post.post_id for entry in shortlisted] == [
        "t3_current",
        "t3_a",
        "t3_b",
    ]
    assert shortlisted[0].priority_score > shortlisted[1].priority_score
