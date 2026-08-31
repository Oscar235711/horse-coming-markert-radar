"""Contracts for read-only, evidence-grounded Codex analysis."""

from datetime import UTC, datetime
import json
from pathlib import Path

import opportunity_radar
from opportunity_radar.codex_analysis import CodexAnalysisClient, CodexTopicConsolidator


def _thread() -> opportunity_radar.ThreadDocument:
    post = opportunity_radar.NormalizedPost(
        post_id="t3_tow",
        url="https://www.reddit.com/r/Cummins/comments/tow/example",
        subreddit="Cummins",
        title="High EGT while towing",
        body="When towing my fifth wheel uphill I want to keep EGT under control.",
        author="owner",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        score=12,
        comment_count=2,
        source_surfaces=("new",),
    )
    return opportunity_radar.ThreadDocument(
        post,
        (
            opportunity_radar.ThreadComment(
                "c1", "I added a gauge but still see 1250F on grades.", post.url + "/c1", "helper"
            ),
        ),
    )


def test_codex_post_analysis_runs_read_only_and_drops_unknown_evidence(tmp_path) -> None:
    """A model must not turn an invented evidence id into a supported user claim."""
    calls = []
    document = {
        "topics": [{"label": "Towing EGT control", "evidence_ids": ["post", "invented"]}],
        "claims": [
            {
                "claim": "Owner sees 1250F on grades.",
                "evidence_ids": ["c1"],
                "urls": ["https://www.reddit.com/r/Cummins/comments/tow/example/c1"],
            },
            {"claim": "Invented market fact", "evidence_ids": ["invented"], "urls": ["https://fake"]},
        ],
        "platform": {"value": "Cummins", "evidence_ids": ["post"], "status": "fact"},
        "vehicle": {"value": "unknown", "evidence_ids": [], "status": "unknown"},
        "year": {"value": "unknown", "evidence_ids": [], "status": "unknown"},
        "scenario": {"value": "Towing uphill to control EGT", "evidence_ids": ["post"], "status": "fact"},
        "goal": {"value": "Keep EGT controlled", "evidence_ids": ["post"], "status": "fact"},
        "user_type": {"value": "Fifth-wheel tow owner", "evidence_ids": ["post"], "status": "fact"},
        "sentiment": {"value": "negative", "evidence_ids": ["post"], "status": "inference"},
        "pain_points": [{"value": "1250F on grades", "evidence_ids": ["c1"], "status": "fact"}],
        "pain_severity": [{"value": "Reliability concern", "evidence_ids": ["post"], "status": "inference"}],
        "consequences": [{"value": "Must slow on grades", "evidence_ids": ["post"], "status": "fact"}],
        "supporting_views": [{"value": "Gauge confirms the issue", "evidence_ids": ["c1"], "status": "fact"}],
        "opposing_views": [],
        "needs": [], "current_solutions": [], "gaps": [], "opportunity_hypotheses": [],
        "products": [], "brands": [], "competitors": [], "purchase_intent": [],
        "keyword_candidates": [], "topic_candidates": [],
    }

    def runner(arguments, prompt):
        calls.append((arguments, prompt))
        return json.dumps(document)

    analysis = CodexAnalysisClient(
        runner=runner, workspace=tmp_path, schema_root=tmp_path
    ).extract_post(_thread())

    arguments, prompt = calls[0]
    assert arguments[:4] == ("codex", "exec", "--ephemeral", "--sandbox")
    assert "read-only" in arguments
    assert "--output-schema" in arguments
    assert "untrusted" in prompt.casefold()
    assert analysis.topics[0].evidence_ids == ("post",)
    assert analysis.claims[0].status == "supported"
    assert analysis.claims[1].status == "unknown"
    assert analysis.user_type.value == "Fifth-wheel tow owner"
    assert analysis.consequences[0].value == "Must slow on grades"


def test_codex_topic_consolidator_keeps_rich_cited_fields_and_never_rule_falls_back(tmp_path) -> None:
    """An empty/invalid model result must not recreate generic rule topics."""
    thread = _thread()
    analysis = opportunity_radar.PostAnalysis(
        topics=(opportunity_radar.TopicCandidate("Towing EGT control", ("post",)),),
        claims=(opportunity_radar.EvidenceClaim("High EGT while towing", ("post",), (thread.post.url,)),),
    )
    signal = opportunity_radar.PostSignal.from_thread(thread, analysis)
    valid = {
        "topics": [{
            "canonical_key": "towing-egt-control",
            "label_en": "Towing EGT control",
            "label_zh": "拖挂排温控制",
            "post_ids": ["t3_tow"],
            "summary": {"text": "车主在拖挂爬坡时需要控制排温。", "evidence": [{"post_id": "t3_tow", "evidence_id": "post"}]},
            "evidence": [{"post_id": "t3_tow", "evidence_id": "post", "claim": "Towing uphill creates an EGT-control need.", "stance": "supporting", "translation_zh": "拖挂爬坡产生排温控制需求。"}],
            "vehicles": [], "platforms": ["Cummins"], "scenarios": ["拖挂爬坡"],
            "pains": [{"text": "高排温带来可靠性担忧", "evidence": [{"post_id": "t3_tow", "evidence_id": "post"}]}],
            "needs": [{"text": "可验证的排温控制", "evidence": [{"post_id": "t3_tow", "evidence_id": "post"}]}],
            "current_solutions": [], "gaps": [], "opportunity_hypotheses": [],
            "category_tags": [], "brand_tags": [], "competitor_tags": [],
            "confidence": 0.82, "validation_questions": ["不同负载下是否重复出现？"]
        }]
    }
    responses = [json.dumps(valid), json.dumps({"topics": []})]
    consolidator = CodexTopicConsolidator(
        client=CodexAnalysisClient(runner=lambda *_: responses.pop(0), workspace=tmp_path, schema_root=tmp_path)
    )

    proposals = consolidator.consolidate("Cummins", (signal,))
    empty = consolidator.consolidate("Cummins", (signal,))

    assert proposals[0].canonical_key == "towing-egt-control"
    assert proposals[0].pains[0].text == "高排温带来可靠性担忧"
    assert proposals[0].pains[0].evidence[0].evidence_id == "post"
    assert empty == ()
    assert consolidator.mode == "codex"


def test_radar_run_uses_codex_for_both_analysis_stages_without_rule_topics(tmp_path) -> None:
    """Selecting the Codex engine must bypass both DeepSeek and the old static topic rules."""
    now = datetime(2026, 8, 31, 12, tzinfo=UTC)
    threads = []
    for index in range(3):
        base = _thread()
        post = opportunity_radar.NormalizedPost(
            post_id=f"t3_tow{index}", url=base.post.url.replace("tow", f"tow{index}"),
            subreddit="Cummins", title=f"6.7 Cummins towing EGT failure {index}",
            body="6.7 Cummins diesel owner towing uphill needs EGT control and tuner fitment help.",
            author=f"owner-{index}", created_at=now, score=12, comment_count=2,
            source_surfaces=("new",),
        )
        threads.append(opportunity_radar.ThreadDocument(post, (
            opportunity_radar.ThreadComment(f"c{index}", "Gauge still shows high EGT while towing.", post.url + f"/c{index}", f"helper-{index}"),
        )))

    class Collector:
        def collect(self, communities, **_kwargs):
            candidates = tuple(opportunity_radar.WindowedPost(item.post, opportunity_radar.PostWindow.CURRENT) for item in threads)
            shortlist = tuple(opportunity_radar.ShortlistedPost(item.post, opportunity_radar.PostWindow.CURRENT, 90) for item in threads)
            return opportunity_radar.CollectionResult(candidates, shortlist, tuple(threads), ())

    class Client:
        def __init__(self):
            self.post_calls = []
            self.topic_calls = []

        def extract_post(self, thread):
            self.post_calls.append(thread.post.post_id)
            return opportunity_radar.PostAnalysis(
                topics=(opportunity_radar.TopicCandidate("Towing EGT control", ("post",)),),
                claims=(opportunity_radar.EvidenceClaim("High EGT while towing", ("post",), (thread.post.url,)),),
                scenario=opportunity_radar.AnalysisField("拖挂爬坡时控制排温", ("post",), "fact"),
                goal=opportunity_radar.AnalysisField("保持可靠排温", ("post",), "fact"),
            )

        def consolidate_topics(self, community, signals):
            self.topic_calls.append((community, len(signals)))
            evidence = [
                {"post_id": signal.post.post_id, "evidence_id": "post", "claim": "Towing uphill creates an EGT need.", "stance": "supporting", "translation_zh": "拖挂爬坡产生排温需求。"}
                for signal in signals
            ]
            refs = [{"post_id": item["post_id"], "evidence_id": "post"} for item in evidence]
            return {"topics": [{
                "canonical_key": "towing-egt-control", "label_en": "Towing EGT control", "label_zh": "拖挂排温控制",
                "post_ids": [signal.post.post_id for signal in signals],
                "summary": {"text": "拖挂爬坡时需要控制排温。", "evidence": refs}, "evidence": evidence,
                "vehicles": [], "platforms": ["Cummins"], "scenarios": ["拖挂爬坡"],
                "pains": [{"text": "高排温导致可靠性担忧", "evidence": refs}],
                "needs": [{"text": "可靠的排温控制", "evidence": refs}], "current_solutions": [], "gaps": [],
                "opportunity_hypotheses": [], "category_tags": [], "brand_tags": [], "competitor_tags": [],
                "confidence": 0.8, "validation_questions": []
            }]}

    def exporter(output_dir, analysis, formats):
        output_dir.mkdir(parents=True, exist_ok=True)
        analysis_path = output_dir / "analysis.json"
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        community_path = output_dir / "community_topics.json"
        community_path.write_text(json.dumps(analysis.get("topics", []), ensure_ascii=False), encoding="utf-8")
        workbook_path = output_dir / "opportunity_radar.xlsx"
        workbook_path.write_bytes(b"xlsx")
        return opportunity_radar.TopicExportArtifacts(analysis_path, community_path, workbook_path)

    client = Client()
    app = opportunity_radar.RadarCliApp(
        runs_root=tmp_path / "runs", library_root=tmp_path / "library",
        collector=Collector(), codex_client=client, exporter=exporter, now=lambda: now,
    )
    config_path = Path(__file__).resolve().parents[1] / "configs" / "diesel_90d.yaml"
    state = app.run(
        config_path, run_id="codex-run", analysis_engine="codex", selected_communities=("Cummins",)
    )

    analysis = json.loads(Path(state["artifacts"]["analysis_json"]).read_text(encoding="utf-8"))
    assert client.post_calls == ["t3_tow0", "t3_tow1", "t3_tow2"]
    assert client.topic_calls == [("Cummins", 3)]
    assert analysis["model_mode"] == "codex"
    assert [topic["canonical_key"] for topic in analysis["topics"]] == ["towing-egt-control"]
