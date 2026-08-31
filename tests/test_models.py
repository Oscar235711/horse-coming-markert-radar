"""Tests for the public typed core models.

Each test targets a consumer-visible model contract rather than a private
implementation detail.
"""

from datetime import UTC, datetime

import opportunity_radar
import pytest


def test_normalized_post_retains_the_evidence_fields_consumers_need() -> None:
    """Removing an evidence field or allowing mutable post records breaks Task 2/3."""
    post_type = opportunity_radar.NormalizedPost
    created_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    post = post_type(
        post_id="t3_abc",
        url="https://www.reddit.com/r/powerstroke/comments/abc/example/",
        subreddit="powerstroke",
        title="DPF question",
        body="Looking for a legal replacement.",
        author="diesel-owner",
        created_at=created_at,
        score=17,
        comment_count=4,
        source_surfaces=("hot", "new"),
    )

    assert post.post_id == "t3_abc"
    assert post.created_at == created_at
    assert post.source_surfaces == ("hot", "new")
    assert post.score == 17


def test_yaml_configuration_uses_subreddits_and_safe_window_defaults(tmp_path) -> None:
    """Dropping legacy subreddit support or changing the 30/90 defaults breaks runs."""
    config_path = tmp_path / "radar.yaml"
    config_path.write_text(
        "project: community-radar\nsubreddits:\n  - powerstroke\n  - Cummins\n",
        encoding="utf-8",
    )

    config = opportunity_radar.load_config(config_path)

    assert config.project == "community-radar"
    assert tuple(community.name for community in config.communities) == (
        "powerstroke",
        "Cummins",
    )
    assert config.current_window_days == 30
    assert config.baseline_window_days == 60
    assert config.shortlist_per_community == 30


def test_yaml_configuration_rejects_a_window_that_violates_the_fixed_30_90_policy(tmp_path) -> None:
    """Allowing arbitrary windows makes current-vs-baseline trend labels incomparable."""
    config_path = tmp_path / "invalid-window.yaml"
    config_path.write_text(
        "communities:\n  - name: powerstroke\nwindows:\n  current_days: 14\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="30/90"):
        opportunity_radar.load_config(config_path)


def test_yaml_configuration_exposes_typed_collection_options(tmp_path) -> None:
    """Ignoring collection controls makes the configured request policy impossible to honor."""
    config_path = tmp_path / "collection.yaml"
    config_path.write_text(
        "communities:\n  - powerstroke\ncollection:\n  request_interval_seconds: 1.5\n  comments_per_post: 50\n  comment_depth: 2\n",
        encoding="utf-8",
    )

    config = opportunity_radar.load_config(config_path)

    assert config.collection.request_interval_seconds == 1.5
    assert config.collection.comments_per_post == 50
    assert config.collection.comment_depth == 2
    assert config.collection.expand_more is True
