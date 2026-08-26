from datetime import UTC, datetime

import opportunity_radar


def test_normalization_deduplicates_a_post_seen_on_multiple_listing_surfaces() -> None:
    """Ignoring a listing surface or retaining duplicate evidence inflates topic counts."""
    raw_posts = [
        {
            "id": "abc",
            "permalink": "/r/powerstroke/comments/abc/dpf_question/?utm_source=share",
            "subreddit": "powerstroke",
            "title": "  DPF question  ",
            "selftext": "Need a legal replacement.",
            "author": "owner",
            "created_utc": 1_754_049_600,
            "score": 3,
            "num_comments": 1,
            "source_surface": "hot",
        },
        {
            "name": "t3_abc",
            "url": "https://www.reddit.com/r/powerstroke/comments/abc/dpf_question/",
            "subreddit_name_prefixed": "r/powerstroke",
            "title": "DPF question",
            "selftext": "Need a legal replacement with a warranty.",
            "author": "owner",
            "created_utc": 1_754_049_600,
            "score": 8,
            "num_comments": 4,
            "source_surface": "new",
        },
    ]

    posts = opportunity_radar.normalize_and_deduplicate(raw_posts)

    assert posts == (
        opportunity_radar.NormalizedPost(
            post_id="t3_abc",
            url="https://www.reddit.com/r/powerstroke/comments/abc/dpf_question",
            subreddit="powerstroke",
            title="DPF question",
            body="Need a legal replacement with a warranty.",
            author="owner",
            created_at=datetime(2025, 8, 1, 12, 0, tzinfo=UTC),
            score=8,
            comment_count=4,
            source_surfaces=("hot", "new"),
        ),
    )


def test_normalization_uses_canonical_url_when_duplicate_records_have_different_ids() -> None:
    """Keeping aliases for the same permalink double-counts one discussion as two posts."""
    shared = {
        "subreddit": "powerstroke",
        "title": "Question",
        "selftext": "Same discussion",
        "author": "owner",
        "created_utc": 1_754_049_600,
        "num_comments": 1,
    }

    posts = opportunity_radar.normalize_and_deduplicate(
        (
            {**shared, "id": "first", "permalink": "/r/powerstroke/comments/shared/x/", "score": 1, "source_surface": "hot"},
            {**shared, "id": "alias", "url": "https://www.reddit.com/r/powerstroke/comments/shared/x/?ref=duplicate", "score": 2, "source_surface": "new"},
        )
    )

    assert len(posts) == 1
    assert posts[0].post_id == "t3_alias"
    assert posts[0].source_surfaces == ("hot", "new")
