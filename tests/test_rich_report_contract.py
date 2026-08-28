from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import opportunity_radar


AS_OF = datetime(2026, 8, 26, tzinfo=UTC)


class FixturePro:
    mode = "deterministic_fixture"

    def consolidate(self, community, signals):
        evidence = tuple(
            opportunity_radar.TopicEvidence(
                post_id=s.post.post_id,
                evidence_id="post",
                claim="Owners report repeated fitment and installation friction.",
                stance="supporting",
                translation_zh="车主反复提到适配和安装阻力。",
            )
            for s in signals
        )
        source = evidence[:1]
        return (
            opportunity_radar.ProTopicProposal(
                canonical_key="downpipe fitment",
                label_en="Downpipe fitment",
                label_zh="下降管适配",
                summary=opportunity_radar.EvidenceBackedClaim("Owners report repeated fitment friction.", source),
                post_ids=tuple(s.post.post_id for s in signals),
                evidence=evidence,
                vehicles=("2020 Ram 2500",), platforms=("Cummins",), scenarios=("towing",),
                pains=(opportunity_radar.EvidenceBackedClaim("Parts do not fit without rework.", source),),
                needs=(opportunity_radar.EvidenceBackedClaim("A verified fitment path.", source),),
                current_solutions=(opportunity_radar.EvidenceBackedClaim("DIY trimming and clamps.", source),),
                gaps=(opportunity_radar.EvidenceBackedClaim("Fitment information is incomplete.", source),),
                opportunity_hypotheses=(opportunity_radar.EvidenceBackedClaim("Opportunity hypothesis: a verified fitment kit.", source),),
                category_tags=("downpipe",), brand_tags=("Example",), competitor_tags=("Other",),
                confidence=0.8, validation_questions=("Which fitment changes cause most rework?",),
            ),
        )


def _post(index: int):
    return opportunity_radar.NormalizedPost(
        post_id=f"p{index}", url=f"https://www.reddit.com/r/Cummins/comments/p{index}", subreddit="Cummins",
        title="Downpipe fitment", body="The downpipe needs trimming and clamp changes.", author=f"owner{index}",
        created_at=AS_OF - timedelta(days=index + 1), score=20, comment_count=2, source_surfaces=("hot",),
    )


def test_topic_has_what_to_sell_business_sections(tmp_path: Path):
    posts = tuple(_post(i) for i in range(3))
    signals = tuple(opportunity_radar.PostSignal(
        post=p,
        analysis=opportunity_radar.PostAnalysis(topics=(), claims=()),
        evidence_urls={"post": p.url},
    ) for p in posts)
    topic = opportunity_radar.TopicAggregator(
        pro=FixturePro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF,
    ).aggregate("Cummins", signals).formal_topics[0]
    assert 0 <= topic["opportunity_score"] <= 10
    assert topic["decision"]["status"] in {"priority_validate", "validate", "observe", "skip"}
    assert topic["top_buyer_complaint"]
    assert topic["best_opening_angle"]
    assert topic["demand_validation"]["posts"] == 3
    assert "manufacturing_profile" in topic
    assert "seller_verdict" in topic


def test_html_contains_rich_report_sections_and_single_payload(tmp_path: Path):
    analysis = {
        "generated_at": AS_OF.isoformat(), "communities": ["Cummins"], "topics": [{
            "topic_id": "topic-1", "community": "Cummins", "label_zh": "下降管适配", "label_en": "Downpipe fitment",
            "status": "formal", "trend": "rising", "heat_score": 80, "post_count": 3, "author_count": 3,
            "commenter_count": 4, "summary": "适配问题反复出现", "pains": ["需要返工"], "needs": ["明确适配"],
            "current_solutions": ["DIY"], "gaps": ["资料不完整"], "opportunity_hypotheses": ["验证套件"],
            "vehicles": ["2020 Ram 2500"], "platforms": ["Cummins"], "scenarios": ["拖挂"],
            "evidence": [{"url": "https://www.reddit.com/r/Cummins/comments/x", "claim_en": "fitment", "claim_zh": "适配"}],
            "opportunity_score": 7.5, "decision": {"status": "priority_validate", "label": "优先验证"},
            "top_buyer_complaint": "需要返工", "best_opening_angle": "验证套件",
            "demand_validation": {"posts": 3, "authors": 3, "commenters": 4, "note": "社区样本"},
            "seller_insight": {"who_should_sell": "柴油配件团队", "who_should_avoid": "无适配能力团队", "positioning_angle": "验证套件", "competition_note": "未知"},
            "why_not_done": {"reasons": ["适配复杂"], "cost_supply_chain_impact": "待验证", "business_model_conflict": "未知"},
            "manufacturing_profile": {"platform_fitment": ["Cummins"], "material_process": "待工程验证", "tooling": "待工程验证", "sku_complexity": "中", "installation": "待验证"},
            "seller_verdict": "机会假设，建议先验证",
            "coverage": {"posts": 3, "authors": 3, "comments": 4, "evidence": 1},
        }], "keyword_library": {"candidates": []}, "crawl_counts": {"saved_comments": 4},
    }
    path = opportunity_radar.render_html(analysis, tmp_path / "report.html")
    html = path.read_text(encoding="utf-8")
    for section in ("Demand Validation", "Seller Insight", "Pain Points", "Seller Opportunities", "Why hasn’t this been done?", "Manufacturing Profile", "Seller Verdict"):
        assert section in html
    assert html.count('id="analysis-data"') == 1
