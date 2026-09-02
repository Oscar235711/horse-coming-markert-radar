"""Contracts for the research-question-driven search entry point."""

from datetime import UTC, datetime
import json
from pathlib import Path

from opportunity_radar.dashboard import dashboard_html
from opportunity_radar.deepseek import DeepSeekClient, HttpResponse
from opportunity_radar.keywords import clean_keyword_term, is_searchable_keyword
from opportunity_radar.query_planner import build_research_brief
from opportunity_radar.server import RunManager
from opportunity_radar.cli import main
from opportunity_radar.library import active_keywords


def test_research_brief_turns_a_question_into_searchable_concepts() -> None:
    brief = build_research_brief("我想了解 Duramax 拖挂时的高温和排气改装痛点")

    assert brief.question == "我想了解 Duramax 拖挂时的高温和排气改装痛点"
    assert "duramax" in brief.query_terms
    assert "towing high egt" in brief.query_terms
    assert "exhaust gas temperature" in brief.query_terms
    assert brief.exclusions


def test_grammar_fragments_are_not_searchable_keywords() -> None:
    assert clean_keyword_term("just got") is None
    assert clean_keyword_term("because im") is None
    assert is_searchable_keyword("EGR cooler leak") is True
    assert is_searchable_keyword("towing high EGT") is True


def test_dashboard_asks_for_question_instead_of_community_or_keyword_checkboxes() -> None:
    html = dashboard_html(("Cummins", "Duramax"), ("just got", "EGR cooler leak"))

    assert 'id="research-question"' in html
    assert "你想了解什么" in html
    assert 'name="community"' not in html
    assert 'name="keyword"' not in html
    assert "just got" not in html
    assert "EGR cooler leak" not in html
    assert "research_question:question" in html
    assert "社区与词库自动沉淀" in html


def test_run_manager_accepts_question_without_user_selected_communities(tmp_path: Path) -> None:
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")

    class App:
        def run(self, config, **kwargs):
            return {"run_id": kwargs["run_id"], "status": "completed", "artifacts": {"report_html": str(report)}}

    manager = RunManager(
        app=App(), config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    state = manager.create_run({
        "research_question": "拖挂时的高温问题",
        "start_date": "2026-01-01",
        "end_date": "2026-08-31",
        "depth": "standard",
        "analysis_engine": "deepseek",
    })
    manager.wait(state["run_id"], timeout=2)

    assert state["research_question"] == "拖挂时的高温问题"


def test_deepseek_planner_returns_clean_query_terms() -> None:
    def transport(method, url, headers, payload):
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "query_terms": ["Duramax", "towing high EGT", "just got", "because im"],
                "exclusions": ["gasoline vehicle"],
            })}}]
        })
        return HttpResponse(200, body)

    client = DeepSeekClient(transport=transport, environment={"DEEPSEEK_API_KEY": "test"})
    result = client.plan_research("拖挂时的高温问题")

    assert result["query_terms"] == ["duramax", "towing high egt"]
    assert result["exclusions"] == ["gasoline vehicle"]


def test_cli_run_accepts_a_research_question() -> None:
    calls = []

    class App:
        def run(self, config, **kwargs):
            calls.append(kwargs)
            return {"run_id": "question-run", "status": "completed"}

    assert main([
        "run", "--config", "configs/diesel_90d.yaml",
        "--research-question", "拖挂时的高温问题",
    ], app=App()) == 0
    assert calls[0]["research_question"] == "拖挂时的高温问题"


def test_active_library_terms_exclude_historical_grammar_noise(tmp_path: Path) -> None:
    (tmp_path / "keywords.json").write_text(json.dumps({"keywords": [
        {"normalized_term": "just got", "status": "active"},
        {"normalized_term": "because im", "status": "active"},
        {"normalized_term": "egr cooler leak", "status": "active"},
    ]}), encoding="utf-8")
    (tmp_path / "communities.json").write_text('{"communities": []}', encoding="utf-8")
    (tmp_path / "topics.json").write_text('{"topics": []}', encoding="utf-8")

    assert active_keywords(tmp_path) == ("egr cooler leak",)
