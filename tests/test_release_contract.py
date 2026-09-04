"""Release regressions reproduced from the report and workbook handoff."""

from __future__ import annotations

import json
from pathlib import Path

import opportunity_radar


def _analysis() -> dict:
    return {
        "communities": ["Cummins", "Duramax", "NoTopics"],
        "topics": [
            {
                "topic_id": "topic-cummins-fitment",
                "community": "r/Cummins",
                "status": "formal",
                "label_zh": "下降管适配",
                "label_en": "Downpipe fitment",
                "summary_zh": "车主正在讨论下降管的车型适配和安装返工。",
                "post_count": 3,
                "author_count": 3,
                "commenter_count": 2,
                "collected_comment_count": 4,
                "evidence": [],
            },
            {
                "topic_id": "topic-duramax-weak",
                "community": "Duramax",
                "status": "weak_signal",
                "label_zh": "待验证弱信号",
                "label_en": "Unverified weak signal",
                "post_count": 1,
                "author_count": 1,
                "evidence": [],
            },
        ],
        "research_scope": {
            "start_date": "2026-01-01",
            "end_date": "2026-08-31",
            "coverage": {
                "Cummins": {"status": "complete"},
                "Duramax": {"status": "partial", "stop_reason": "date_boundary_not_reached"},
                "NoTopics": {"status": "complete", "stop_reason": "no_formal_topic"},
            },
        },
        "report_metrics": {
            "community_count": 3,
            "topic_count": 2,
            "formal_topic_count": 1,
            "weak_topic_count": 1,
            "scanned_post_count": 20,
            "deep_read_post_count": 6,
            "analyzed_post_count": 5,
            "participant_count": 5,
            "evidence_count": 0,
            "communities": {"Cummins": {"scanned_post_count": 8}},
        },
    }


def test_graph_projection_excludes_weak_only_and_empty_communities() -> None:
    """A map node must always own a formal topic, never only coverage data."""
    analysis = _analysis()

    assert hasattr(opportunity_radar, "build_visible_topic_map")
    visible = opportunity_radar.build_visible_topic_map(analysis)

    assert visible["communities"] == ["Cummins"]
    assert [topic["topic_id"] for topic in visible["topics"]] == ["topic-cummins-fitment"]
    graph = opportunity_radar.build_topic_map(analysis)
    assert [node["label"] for node in graph["nodes"] if node["type"] == "community"] == ["Cummins"]


def test_report_community_preview_uses_visible_formal_topics_only(tmp_path: Path) -> None:
    """Opening a community hash cannot call a missing function or reveal weak topics."""
    report_path = opportunity_radar.render_html(_analysis(), tmp_path / "report.html")
    html = report_path.read_text(encoding="utf-8")
    projection = json.loads((tmp_path / "community_topic_map.json").read_text(encoding="utf-8"))

    assert "function showCommunityDetail(name)" in html
    assert "const TOPICS=formalTopics;" in html
    assert "formalTopics.length?formalTopics:ALL_TOPICS" not in html
    assert "Duramax" not in [node["label"] for node in projection["nodes"] if node["type"] == "community"]
    assert "NoTopics" not in [node["label"] for node in projection["nodes"] if node["type"] == "community"]

