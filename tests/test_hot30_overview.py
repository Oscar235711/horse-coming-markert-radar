from pathlib import Path

from opportunity_radar.hot30_overview import (
    build_evidence_pool,
    extract_item_signals,
    _merge_enriched_pool,
    validate_overview,
)


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def chat_json(self, _messages, **_kwargs):
        return next(self.responses)


POOL = [
    {
        "evidence_id": "reddit:R1",
        "source": "reddit",
        "title_original": "Engine-out upgrades",
        "excerpt_original": "What should I replace while the engine is out?",
        "url": "https://reddit.test/1",
    },
]


def test_build_evidence_pool_works_when_clusters_are_empty():
    report = {
        "ranked_candidates": [],
        "clusters": [],
        "items_by_source": {
            "reddit": [{"item_id": "R1", "title": "Engine-out upgrades", "url": "https://reddit.test/1"}],
            "youtube": [{"item_id": "Y1", "title": "Diesel towing setup", "url": "https://youtube.test/1"}],
        },
    }
    pool = build_evidence_pool(report)
    assert {row["evidence_id"] for row in pool} == {"reddit:R1", "youtube:Y1"}


def test_build_evidence_pool_deduplicates_ranked_and_source_items():
    report = {
        "ranked_candidates": [{"candidate_id": "R1", "source": "reddit", "title": "A", "url": "https://reddit.test/1"}],
        "items_by_source": {"reddit": [{"item_id": "R1", "title": "A longer title", "url": "https://reddit.test/1"}]},
    }
    pool = build_evidence_pool(report)
    assert len(pool) == 1
    assert pool[0]["title_original"] == "A longer title"


def test_item_signal_keeps_original_and_requires_chinese_translation(tmp_path: Path):
    client = FakeClient([{
        "items": [{
            "evidence_id": "reddit:R1",
            "title_zh": "发动机拆出期间的升级项目",
            "excerpt_zh": "用户希望在发动机拆出时一次性完成预防性更换。",
            "discussion_zh": "讨论发动机拆出期间应该同步更换哪些部件。",
            "user_context_zh": "维修或大修柴油皮卡的车主。",
            "pain_need_zh": "担心重新装回后再次拆装，想减少返工。",
            "current_response_zh": "参考其他车主的维修清单。",
            "candidate_topic_zh": "发动机拆出期间的预防性维护",
            "candidate_topic_en": "Preventive maintenance during engine-out work",
        }]
    }])
    rows = extract_item_signals(POOL, client, tmp_path / "items.jsonl")
    assert rows[0]["title_original"] == "Engine-out upgrades"
    assert rows[0]["title_zh"] == "发动机拆出期间的升级项目"
    assert rows[0]["discussion_zh"]


def test_validate_overview_moves_under_supported_topics_to_watchlist():
    document = {
        "topics": [{
            "topic_id": "t1",
            "title_zh": "维修清单",
            "discussion_zh": "讨论拆机时要更换什么。",
            "evidence_ids": ["reddit:R1"],
        }],
        "watchlist": [],
    }
    result = validate_overview(document, POOL)
    assert result["topics"] == []
    assert result["watchlist"][0]["topic_id"] == "t1"
    assert result["data_snapshot"]["evidence_count"] == 1


def test_validate_overview_accepts_gateway_topic_title_alias():
    document = {
        "executive_summary_zh": "过去30天的总体讨论结论。",
        "topics": [{
            "topic_id": "t1",
            "topic_title_zh": "发动机启动故障",
            "topic_title_en": "Engine starting faults",
            "summary_zh": "多名车主讨论难启动和熄火。",
            "evidence_ids": ["reddit:R1", "reddit:R2", "reddit:R3"],
        }],
        "watchlist": [],
    }
    pool = POOL + [
        {"evidence_id": "reddit:R2", "source": "reddit", "url": "https://reddit.test/2", "title_original": "B"},
        {"evidence_id": "reddit:R3", "source": "reddit", "url": "https://reddit.test/3", "title_original": "C"},
    ]
    result = validate_overview(document, pool)
    assert result["topics"][0]["title_zh"] == "发动机启动故障"
    assert result["topics"][0]["title_en"] == "Engine starting faults"
    assert result["topics"][0]["one_line_zh"] == "多名车主讨论难启动和熄火。"


def test_enriched_pool_overlays_chinese_evidence_without_changing_source_count():
    enriched = _merge_enriched_pool(
        POOL,
        [{"evidence_id": "reddit:R1", "title_zh": "发动机升级", "excerpt_zh": "用户寻求预防性更换建议。"}],
    )
    assert len(enriched) == len(POOL)
    assert enriched[0]["title_original"] == POOL[0]["title_original"]
    assert enriched[0]["title_zh"] == "发动机升级"


def test_validate_overview_computes_sample_heat_and_participants():
    document = {
        "topics": [{
            "topic_id": "t1",
            "title_zh": "发动机问题",
            "evidence_ids": ["reddit:R1", "reddit:R2", "reddit:R3"],
        }],
        "watchlist": [],
    }
    pool = [
        {"evidence_id": "reddit:R1", "source": "reddit", "url": "https://reddit.test/1", "author": "alice", "published_at": "2026-09-04", "engagement": 20},
        {"evidence_id": "reddit:R2", "source": "reddit", "url": "https://reddit.test/2", "author": "bob", "published_at": "2026-09-03", "engagement": 5},
        {"evidence_id": "reddit:R3", "source": "reddit", "url": "https://reddit.test/3", "author": "alice", "published_at": "2026-08-30", "engagement": 1},
    ]
    heat = validate_overview(document, pool)["topics"][0]["heat"]
    assert heat["score"] > 0
    assert heat["evidence_count"] == 3
    assert heat["participant_count"] == 2
