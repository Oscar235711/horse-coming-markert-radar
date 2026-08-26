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


def test_naive_iso_timestamps_are_utc_at_the_30_and_90_day_boundaries() -> None:
    """Treating naive Reddit timestamps as local time shifts fixed window membership."""
    posts = opportunity_radar.normalize_and_deduplicate(
        (
            {
                "id": "current",
                "permalink": "/r/powerstroke/comments/current/example/",
                "subreddit": "powerstroke",
                "title": "Current",
                "selftext": "Body",
                "author": "owner",
                "created_at": "2026-08-01T12:00:00",
                "score": 0,
                "num_comments": 0,
                "source_surface": "hot",
            },
            {
                "id": "baseline",
                "permalink": "/r/powerstroke/comments/baseline/example/",
                "subreddit": "powerstroke",
                "title": "Baseline",
                "selftext": "Body",
                "author": "owner",
                "created_at": "2026-06-02T12:00:00",
                "score": 0,
                "num_comments": 0,
                "source_surface": "hot",
            },
        )
    )

    windowed = opportunity_radar.window_posts(
        posts, as_of=datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    )

    assert [(item.post.post_id, item.window) for item in windowed] == [
        ("t3_current", opportunity_radar.PostWindow.CURRENT),
        ("t3_baseline", opportunity_radar.PostWindow.BASELINE),
    ]


def test_deduplication_is_identical_when_same_url_tie_records_are_permuted() -> None:
    """Input ordering must not select a different evidence identity or metadata."""
    first = {
        "id": "zeta",
        "permalink": "/r/powerstroke/comments/shared/example/",
        "subreddit": "PowerStroke",
        "title": "Zulu title",
        "selftext": "Same",
        "author": "zed",
        "created_at": "2026-08-01T12:00:00+00:00",
        "score": 5,
        "num_comments": 2,
        "source_surface": "hot",
    }
    second = {
        "id": "alpha",
        "url": "https://www.reddit.com/r/powerstroke/comments/shared/example/?ref=alias",
        "subreddit": "powerstroke",
        "title": "Alpha title",
        "selftext": "Same",
        "author": "ann",
        "created_at": "2026-08-02T12:00:00+00:00",
        "score": 5,
        "num_comments": 2,
        "source_surface": "new",
    }

    forward = opportunity_radar.normalize_and_deduplicate((first, second))
    reverse = opportunity_radar.normalize_and_deduplicate((second, first))

    assert forward == reverse
    assert forward[0].post_id == "t3_zeta"
    assert forward[0].title == "Zulu title"
    assert forward[0].author == "zed"
    assert forward[0].created_at == datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
