"""Executable acceptance tests for Task 3 topic analysis and export."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import opportunity_radar


AS_OF = datetime(2026, 8, 26, tzinfo=UTC)


class DeterministicPro:
    """Fixture-only injected Pro implementation; it never makes a network call."""

    mode = "deterministic_fixture"

    def consolidate(self, community, signals):
        ids = tuple(signal.post.post_id for signal in signals)
        return (
            opportunity_radar.ProTopicProposal(
                canonical_key="winter durability",
                label_en="Winter durability",
                label_zh="冬季耐久性",
                summary="Owners report cracking after freezing weather.",
                post_ids=ids,
                evidence=(
                    opportunity_radar.TopicEvidence(
                        post_id=signal.post.post_id,
                        evidence_id="post",
                        claim="Cracking after winter use.",
                        stance="supporting",
                        translation_zh="冬季使用后开裂。",
                    )
                    for signal in signals
                ),
                vehicles=("Diesel pickup",),
                platforms=("aftermarket",),
                scenarios=("winter towing",),
                pains=("cracking",),
                needs=("freeze-resistant material",),
                current_solutions=("installed replacement",),
                gaps=("current options still crack",),
                opportunity_hypotheses=("Opportunity hypothesis: cold-weather replacement part.",),
                category_tags=("durability",),
                brand_tags=("ExampleBrand",),
                competitor_tags=("CompetitorX",),
                confidence=0.82,
                validation_questions=("Does failure repeat below freezing?",),
            ),
        )


def _post(number: int, *, age_days: int, author: str, comments: int = 2, score: int = 10):
    return opportunity_radar.NormalizedPost(
        post_id=f"t3_post_{number}",
        url=f"https://www.reddit.com/r/diesel/comments/post_{number}/evidence",
        subreddit="diesel",
        title=f"Winter failure {number}",
        body="The part cracked in winter.",
        author=author,
        created_at=AS_OF - timedelta(days=age_days),
        score=score,
        comment_count=comments,
        source_surfaces=("hot",),
    )


def _signal(post):
    return opportunity_radar.PostSignal(
        post=post,
        analysis=opportunity_radar.PostAnalysis(
            topics=(opportunity_radar.TopicCandidate("winter durability", ("post",)),),
            claims=(
                opportunity_radar.EvidenceClaim(
                    "Cracking after winter use.", ("post",), (post.url,)
                ),
            ),
        ),
        evidence_urls={"post": post.url},
    )


def test_topic_aggregation_applies_formal_threshold_trend_heat_and_stable_id(tmp_path: Path) -> None:
    """A formal current topic gets a stable id, new trend, and normalized heat."""
    posts = tuple(_post(index, age_days=index + 1, author=f"owner{index}") for index in range(3))
    registry = opportunity_radar.TopicRegistry(tmp_path / "topic-registry.json")

    result = opportunity_radar.TopicAggregator(
        pro=DeterministicPro(), registry=registry, as_of=AS_OF
    ).aggregate("diesel", tuple(_signal(post) for post in posts))

    topic = result.formal_topics[0]
    assert topic["topic_id"] == registry.records()[0].topic_id
    assert topic["status"] == "formal"
    assert topic["trend"] == "new"
    assert topic["heat_score"] == 100.0
    assert topic["post_count"] == 3
    assert topic["author_count"] == 3
    assert topic["model_mode"] == "deterministic_fixture"


def test_weak_signal_uses_commenter_threshold_and_drops_invalid_evidence(tmp_path: Path) -> None:
    """Unsupported claims never reach a topic, while ten commenters make it formal."""
    posts = (
        _post(1, age_days=2, author="one", comments=10),
        _post(2, age_days=3, author="two", comments=0),
    )
    pro = DeterministicPro()
    aggregator = opportunity_radar.TopicAggregator(pro=pro, registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF)
    result = aggregator.aggregate("diesel", tuple(_signal(post) for post in posts))

    assert result.formal_topics[0]["status"] == "formal"
    assert result.formal_topics[0]["commenter_count"] == 10
    assert result.excluded_records == ()

    class InvalidEvidencePro(DeterministicPro):
        def consolidate(self, community, signals):
            proposal = next(iter(super().consolidate(community, signals)))
            return (replace(proposal, evidence=(opportunity_radar.TopicEvidence("missing", "post", "invented", "supporting", "虚构证据"),)),)

    rejected = opportunity_radar.TopicAggregator(
        pro=InvalidEvidencePro(), registry=opportunity_radar.TopicRegistry(tmp_path / "invalid.json"), as_of=AS_OF
    ).aggregate("diesel", tuple(_signal(post) for post in posts))
    assert rejected.formal_topics == ()
    assert rejected.excluded_records[0]["reason"] == "invalid_evidence"


def test_export_derives_json_and_seven_sheet_excel_from_one_canonical_analysis(tmp_path: Path) -> None:
    """The persisted JSON and actual workbook must be exact projections of one analysis."""
    posts = tuple(_post(index, age_days=index + 1, author=f"owner{index}", score=10 + index) for index in range(3))
    analysis = opportunity_radar.TopicAggregator(
        pro=DeterministicPro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", tuple(_signal(post) for post in posts)).analysis

    exported = opportunity_radar.export_topic_analysis(analysis, output_dir=tmp_path / "artifacts")
    canonical = json.loads(exported.analysis_json.read_text(encoding="utf-8"))
    community_topics = json.loads(exported.community_topics_json.read_text(encoding="utf-8"))
    assert canonical["topics"] == analysis["topics"]
    assert community_topics["topics"] == canonical["topics"]
    assert exported.workbook_path.exists()

    with ZipFile(exported.workbook_path) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        workbook_parts = "".join(
            workbook.read(name).decode("utf-8")
            for name in workbook.namelist()
            if name.endswith(".xml")
        )
    assert workbook_xml.count(":sheet ") == 7
    assert all(name in workbook_xml for name in opportunity_radar.EXCEL_SHEET_NAMES)
    assert "冬季耐久性" in workbook_parts
    assert "Cracking after winter use." in workbook_parts
    assert "HYPERLINK" in workbook_parts
    assert "https://www.reddit.com/" in workbook_parts


def test_aggregation_never_mixes_communities_or_calls_pro_again_during_export(tmp_path: Path) -> None:
    """Community-local clustering prevents unrelated posts from inflating a topic."""
    class CountingPro(DeterministicPro):
        calls = 0

        def consolidate(self, community, signals):
            self.calls += 1
            return super().consolidate(community, signals)

    diesel = _post(1, age_days=2, author="diesel-owner")
    foreign = opportunity_radar.NormalizedPost(
        post_id="t3_foreign", url="https://www.reddit.com/r/powerstroke/comments/foreign/evidence",
        subreddit="powerstroke", title="Foreign", body="Foreign", author="foreign-owner",
        created_at=AS_OF - timedelta(days=2), score=99, comment_count=99, source_surfaces=("hot",),
    )
    pro = CountingPro()
    result = opportunity_radar.TopicAggregator(
        pro=pro, registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", (_signal(diesel), _signal(foreign)))

    assert result.analysis["topics"][0]["post_count"] == 1
    opportunity_radar.export_topic_analysis(result.analysis, output_dir=tmp_path / "artifacts")
    assert pro.calls == 1


def test_trends_use_current_thirty_days_against_prior_sixty_day_daily_rate(tmp_path: Path) -> None:
    """The boundary rates distinguish rising, falling, and stable topics."""
    def aggregate_for(ages: tuple[int, ...]):
        posts = tuple(_post(index, age_days=age, author=f"owner-{index}") for index, age in enumerate(ages))
        return opportunity_radar.TopicAggregator(
            pro=DeterministicPro(), registry=opportunity_radar.TopicRegistry(tmp_path / f"{ages}.json"), as_of=AS_OF
        ).aggregate("diesel", tuple(_signal(post) for post in posts)).analysis["topics"][0]["trend"]

    assert aggregate_for((1, 2, 3, 40)) == "rising"
    assert aggregate_for((1, 40, 41, 42)) == "falling"
    assert aggregate_for((1, 2, 40, 41, 42, 43)) == "stable"


def test_topic_rejects_evidence_without_a_chinese_translation(tmp_path: Path) -> None:
    """Adjacent bilingual evidence requires a real translation from the injected Pro result."""
    class UntranslatedPro(DeterministicPro):
        def consolidate(self, community, signals):
            proposal = next(iter(super().consolidate(community, signals)))
            evidence = tuple(proposal.evidence)
            untranslated = opportunity_radar.TopicEvidence(
                evidence[0].post_id, "post", "Cracking after winter use.", "supporting", ""
            )
            return (replace(proposal, evidence=(untranslated,)),)

    posts = (_post(1, age_days=2, author="owner", comments=10), _post(2, age_days=3, author="other"))
    result = opportunity_radar.TopicAggregator(
        pro=UntranslatedPro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", tuple(_signal(post) for post in posts))

    assert result.formal_topics == ()
    assert result.excluded_records[0]["reason"] == "invalid_evidence"
