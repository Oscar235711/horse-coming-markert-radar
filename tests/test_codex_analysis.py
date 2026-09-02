"""Contracts for read-only, evidence-grounded Codex analysis."""

from datetime import UTC, datetime
import json
from pathlib import Path

import opportunity_radar
import pytest
from opportunity_radar.codex_analysis import CodexAnalysisClient, CodexTopicConsolidator, ChunkedCodexTopicConsolidator
from opportunity_radar.cli_app import DeepSeekTopicConsolidator


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
    assert "简体中文" in prompt
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


def test_chunked_consolidator_runs_model_merge_for_semantic_duplicates() -> None:
    """Exact-key merging alone creates many one-post topics with no business value."""
    threads = [_thread(), _thread(), _thread(), _thread()]
    analyses = [opportunity_radar.PostAnalysis((), ()) for _ in threads]
    signals = tuple(opportunity_radar.PostSignal.from_thread(t, a) for t, a in zip(threads, analyses))

    def topic(key: str, label: str) -> dict:
        return {
            "canonical_key": key, "label_en": label, "label_zh": "拖挂排温问题",
            "post_ids": ["t3_tow"],
            "summary": {"text": "拖挂爬坡时排温偏高。", "evidence": [{"post_id": "t3_tow", "evidence_id": "post"}]},
            "evidence": [{"post_id": "t3_tow", "evidence_id": "post", "claim": "High EGT while towing.", "stance": "supporting", "translation_zh": "拖挂时排温偏高。"}],
            "vehicles": [], "platforms": ["Cummins"], "scenarios": ["拖挂爬坡"], "user_types": ["拖挂用户"],
            "pains": [], "consequences": [], "needs": [], "current_solutions": [], "gaps": [],
            "opportunity_hypotheses": [], "risks": [], "product_decision": "no_product",
            "category_tags": [], "brand_tags": [], "competitor_tags": [], "confidence": 0.7,
            "validation_questions": [],
        }

    class Client:
        def __init__(self):
            self.calls = 0
            self.merge_calls = 0

        def consolidate_topics(self, _community, _signals):
            self.calls += 1
            return {"topics": [topic(f"egt-{self.calls}", f"EGT variant {self.calls}")]}

        def merge_topic_proposals(self, _community, proposals):
            self.merge_calls += 1
            assert len(proposals) == 2
            return {"topics": [topic("towing-egt", "Towing EGT")]}

    client = Client()
    proposals = ChunkedCodexTopicConsolidator(client=client, chunk_size=1).consolidate("Cummins", signals)

    assert client.merge_calls == 1
    assert [item.canonical_key for item in proposals] == ["towing-egt"]


def test_deepseek_topic_consolidator_accepts_gateway_mapping_evidence_and_rich_voc() -> None:
    """Higress may return evidence as an id->url map; keep the rich Chinese VOC fields."""
    thread = _thread()
    analysis = opportunity_radar.PostAnalysis(
        topics=(opportunity_radar.TopicCandidate("Towing EGT control", ("post",)),),
        claims=(),
        scenario=opportunity_radar.AnalysisField("拖挂爬坡时控制排温", ("post",), "fact"),
        goal=opportunity_radar.AnalysisField("保持动力稳定并避免过热", ("post",), "fact"),
    )
    signal = opportunity_radar.PostSignal.from_thread(thread, analysis)

    class Client:
        def chat_json(self, *_args, **_kwargs):
            return {
                "topics": [{
                    "canonical_key": "towing-egt-control",
                    "label_en": "Towing EGT control",
                    "label_zh": "拖挂排温控制",
                    "post_ids": ["t3_tow"],
                    "summary": "拖挂爬坡时车主需要控制排温，避免被迫降速。",
                    "seller_insight": "用户愿意为可验证的排温控制方案付费，但现有方案需要自行组合。",
                    "scene_cards": [{"text": "拖挂第五轮上坡时，持续高负载导致排温升高。", "evidence": ["post"]}],
                    "user_tasks": [{"text": "在不牺牲拖挂动力的情况下把排温控制在可接受范围。", "evidence": ["post"]}],
                    "pains": [{"text": "爬坡时排温过高，用户只能降速。", "status": "fact", "severity": "high", "consequence": "拖挂效率下降", "evidence": ["post"]}],
                    "needs": [{"text": "适合重载场景的可验证排温控制方案。", "evidence": ["post"]}],
                    "current_solutions": [{"text": "加装排温表并调整驾驶方式。", "evidence": ["post"]}],
                    "gaps": [{"text": "用户需要自行试错，缺少一套清晰的适配路径。", "evidence": ["post"]}],
                    "opportunity_hypotheses": [{"text": "开发带适配说明的排温监测与控制组合包。", "evidence": ["post"]}],
                    "product_decision": "accessory_bundle",
                    "evidence": {"post": "https://www.reddit.com/r/Cummins/comments/tow/example"},
                    "confidence": 0.86,
                }]
            }

    proposals = DeepSeekTopicConsolidator(
        client=Client(), model="deepseek-v4-pro"
    ).consolidate("Cummins", (signal,))

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.summary.text.startswith("拖挂爬坡")
    assert proposal.seller_insight.text.startswith("用户愿意")
    assert proposal.user_tasks[0].text.startswith("在不牺牲")
    assert proposal.pains[0].severity == "high"
    assert proposal.evidence[0].evidence_id == "post"


def test_deepseek_topic_consolidator_never_silently_uses_rule_topics() -> None:
    """A failed Pro call must stay retryable instead of producing a report labelled as DeepSeek."""
    thread = _thread()
    signal = opportunity_radar.PostSignal.from_thread(
        thread,
        opportunity_radar.PostAnalysis(
            topics=(opportunity_radar.TopicCandidate("Towing EGT control", ("post",)),),
            claims=(),
        ),
    )

    class FailingClient:
        def chat_json(self, *_args, **_kwargs):
            raise opportunity_radar.DeepSeekError("gateway unavailable")

    consolidator = DeepSeekTopicConsolidator(
        client=FailingClient(), model="deepseek-v4-pro"
    )

    with pytest.raises(opportunity_radar.DeepSeekError, match="gateway unavailable"):
        consolidator.consolidate("Cummins", (signal,))


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
