from __future__ import annotations

from datetime import UTC, datetime

import opportunity_radar


NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _post(post_id: str, community: str, author: str) -> opportunity_radar.NormalizedPost:
    return opportunity_radar.NormalizedPost(
        post_id=post_id,
        url=f"https://www.reddit.com/r/{community}/comments/{post_id}",
        subreddit=community,
        title="Concrete fitment problem",
        body="The part does not fit while towing.",
        author=author,
        created_at=NOW,
        score=12,
        comment_count=2,
        source_surfaces=("new",),
    )


def test_report_metrics_are_unique_and_shared_across_outputs():
    p1 = _post("p1", "Cummins", "owner-1")
    p2 = _post("p2", "Cummins", "owner-2")
    p3 = _post("p3", "Duramax", "owner-3")
    candidates = tuple(
        opportunity_radar.WindowedPost(post, opportunity_radar.PostWindow.CURRENT)
        for post in (p1, p2, p3)
    )
    deep_reads = (
        opportunity_radar.ThreadDocument(p1, (
            opportunity_radar.ThreadComment("c1", "same commenter", p1.url + "?comment=c1", "reader-1"),
            opportunity_radar.ThreadComment("c2", "op reply", p1.url + "?comment=c2", "owner-1"),
        )),
        opportunity_radar.ThreadDocument(p2, (
            opportunity_radar.ThreadComment("c3", "same commenter again", p2.url + "?comment=c3", "reader-1"),
            opportunity_radar.ThreadComment("c4", "new commenter", p2.url + "?comment=c4", "reader-2"),
        )),
    )
    collection = opportunity_radar.CollectionResult(
        candidates=candidates,
        shortlisted=(),
        deep_reads=deep_reads,
        failures=(),
    )
    topics = [
        {
            "topic_id": "t1", "community": "Cummins", "status": "formal",
            "post_ids": ["p1", "p2"],
            "evidence": [
                {"post_id": "p1", "evidence_id": "post", "url": p1.url},
                {"post_id": "p1", "evidence_id": "post", "url": p1.url},
            ],
        },
        {
            "topic_id": "t2", "community": "Cummins", "status": "weak_signal",
            "post_ids": ["p1"],
            "evidence": [{"post_id": "p2", "evidence_id": "c3", "url": p2.url + "?comment=c3"}],
        },
    ]

    metrics = opportunity_radar.build_report_metrics(
        communities=("Cummins", "Duramax"),
        collection=collection,
        analyzed_threads=deep_reads,
        topics=topics,
    )

    assert metrics["community_count"] == 2
    assert metrics["topic_count"] == 2
    assert metrics["formal_topic_count"] == 1
    assert metrics["scanned_post_count"] == 3
    assert metrics["deep_read_post_count"] == 2
    assert metrics["analyzed_post_count"] == 2
    assert metrics["topic_post_count"] == 2
    assert metrics["post_author_count"] == 2
    assert metrics["commenter_count"] == 2
    assert metrics["participant_count"] == 4
    assert metrics["collected_comment_count"] == 4
    assert metrics["evidence_count"] == 2
    assert metrics["communities"]["Cummins"]["scanned_post_count"] == 2
    assert metrics["communities"]["Duramax"]["scanned_post_count"] == 1

