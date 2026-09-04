"""Regression coverage for Chinese broad-topic relevance handling."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDORED_SCRIPTS = PROJECT_ROOT / "vendor" / "last30days" / "scripts"
if str(VENDORED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VENDORED_SCRIPTS))

from lib import rerank, schema  # noqa: E402


def test_chinese_broad_topic_does_not_hide_relevant_english_candidate() -> None:
    candidate = schema.Candidate(
        candidate_id="reddit-1",
        item_id="reddit-1",
        source="reddit",
        title="Duramax transmission cooler pipe leak",
        url="https://www.reddit.com/r/Duramax/comments/abc/example",
        snippet="Owner describes a recurring repair problem on a diesel pickup.",
        subquery_labels=["primary"],
        native_ranks={"reddit": 1},
        local_relevance=0.2,
        freshness=80,
        engagement=20,
        source_quality=0.8,
        rrf_score=0.5,
    )
    topic = "\u5317\u7f8e\u67f4\u6cb9\u76ae\u5361\u6539\u88c5"
    ranked = rerank.rerank_candidates(
        topic=topic,
        plan=schema.QueryPlan(
            intent="how_to",
            freshness_mode="evergreen_ok",
            cluster_mode="workflow",
            raw_topic=topic,
            subqueries=[],
            source_weights={},
            notes=[],
        ),
        candidates=[candidate],
        provider=None,
        model=None,
        shortlist_size=10,
    )

    visible = rerank.prune_fallback_entity_misses(ranked, topic=topic)

    assert [item.candidate_id for item in visible] == ["reddit-1"]
