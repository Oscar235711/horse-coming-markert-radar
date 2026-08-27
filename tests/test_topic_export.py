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
        evidence = tuple(
            opportunity_radar.TopicEvidence(
                post_id=signal.post.post_id,
                evidence_id="post",
                claim="Cracking after winter use.",
                stance="supporting",
                translation_zh="冬季使用后开裂。",
            )
            for signal in signals
        )
        claim_source = evidence[:1]
        return (
            opportunity_radar.ProTopicProposal(
                canonical_key="winter durability",
                label_en="Winter durability",
                label_zh="冬季耐久性",
                summary=opportunity_radar.EvidenceBackedClaim(
                    "Owners report cracking after freezing weather.", claim_source
                ),
                post_ids=ids,
                evidence=evidence,
                vehicles=("Diesel pickup",),
                platforms=("aftermarket",),
                scenarios=("winter towing",),
                pains=(opportunity_radar.EvidenceBackedClaim("cracking", claim_source),),
                needs=(opportunity_radar.EvidenceBackedClaim("freeze-resistant material", claim_source),),
                current_solutions=(opportunity_radar.EvidenceBackedClaim("installed replacement", claim_source),),
                gaps=(opportunity_radar.EvidenceBackedClaim("current options still crack", claim_source),),
                opportunity_hypotheses=(opportunity_radar.EvidenceBackedClaim("Opportunity hypothesis: cold-weather replacement part.", claim_source),),
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


def _signal(post, *, comment_authors: tuple[str, ...] = ()):
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
        comment_authors=comment_authors,
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
    assert topic["heat_score"] == 80.0
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
    signals = (
        _signal(posts[0], comment_authors=tuple(f"commenter-{index}" for index in range(10))),
        _signal(posts[1]),
    )
    result = aggregator.aggregate("diesel", signals)

    assert result.formal_topics[0]["status"] == "formal"
    assert result.formal_topics[0]["commenter_count"] == 10
    assert result.excluded_records == ()

    class InvalidEvidencePro(DeterministicPro):
        def consolidate(self, community, signals):
            proposal = next(iter(super().consolidate(community, signals)))
            return (replace(proposal, evidence=(opportunity_radar.TopicEvidence("missing", "post", "invented", "supporting", "虚构证据"),)),)

    rejected = opportunity_radar.TopicAggregator(
        pro=InvalidEvidencePro(), registry=opportunity_radar.TopicRegistry(tmp_path / "invalid.json"), as_of=AS_OF
    ).aggregate("diesel", signals)
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


def test_commenter_threshold_counts_distinct_non_op_authors_only(tmp_path: Path) -> None:
    """Ten comments by the same person cannot manufacture a formal topic."""
    posts = (_post(1, age_days=2, author="op-1", comments=10), _post(2, age_days=3, author="op-2", comments=10))
    result = opportunity_radar.TopicAggregator(
        pro=DeterministicPro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", tuple(_signal(post, comment_authors=("repeat",) * 10) for post in posts))

    assert result.weak_topics[0]["commenter_count"] == 1
    assert result.formal_topics == ()


def test_commenter_threshold_accepts_ten_distinct_non_op_authors(tmp_path: Path) -> None:
    """Ten distinct non-OP commenters satisfy the explicit alternate formal threshold."""
    posts = (_post(1, age_days=2, author="op-1"), _post(2, age_days=3, author="op-2"))
    result = opportunity_radar.TopicAggregator(
        pro=DeterministicPro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", (
        _signal(posts[0], comment_authors=tuple(f"commenter-{index}" for index in range(10))),
        _signal(posts[1], comment_authors=("op-2",)),
    ))

    assert result.formal_topics[0]["commenter_count"] == 10


def test_duplicate_post_ids_in_a_proposal_do_not_inflate_counts_or_bypass_limits(tmp_path: Path) -> None:
    """A malicious Pro response cannot repeat one post to create fake topic volume."""
    class DuplicatingPro(DeterministicPro):
        def consolidate(self, community, signals):
            proposal = next(iter(super().consolidate(community, signals)))
            post_id = signals[0].post.post_id
            return (replace(proposal, post_ids=(post_id, post_id, post_id, post_id)),)

    post = _post(1, age_days=2, author="owner", comments=99)
    result = opportunity_radar.TopicAggregator(
        pro=DuplicatingPro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", (_signal(post, comment_authors=("one",)),))

    assert result.weak_topics[0]["post_count"] == 1
    assert result.weak_topics[0]["author_count"] == 1
    assert result.weak_topics[0]["commenter_count"] == 1


def test_export_uses_explicit_node_executable_without_a_hard_coded_user_path(tmp_path: Path) -> None:
    """A caller-controlled Node path keeps export portable across developer machines."""
    analysis = {"analysis_version": "1.0", "generated_at": AS_OF.isoformat(), "communities": ["diesel"], "topics": [], "excluded_records": []}
    node = Path(__import__("shutil").which("node"))

    exported = opportunity_radar.export_topic_analysis(analysis, output_dir=tmp_path / "artifacts", node_executable=node)

    assert exported.workbook_path.exists()


def test_specific_topic_claims_require_their_own_valid_evidence_and_export_views(tmp_path: Path) -> None:
    """A topic-level citation cannot launder an unsupported pain or summary claim."""
    class ClaimEvidencePro(DeterministicPro):
        def consolidate(self, community, signals):
            proposal = next(iter(super().consolidate(community, signals)))
            source = tuple(proposal.evidence)[0]
            opposing = opportunity_radar.TopicEvidence(
                source.post_id, source.evidence_id, "Some owners report no crack.", "opposing", "部分车主未发现开裂。"
            )
            return (replace(
                proposal,
                evidence=(source, opposing),
                summary=opportunity_radar.EvidenceBackedClaim("Grounded summary.", (source,)),
                pains=(
                    opportunity_radar.EvidenceBackedClaim("Grounded pain.", (source,)),
                    opportunity_radar.EvidenceBackedClaim(
                        "Unsupported pain.", (opportunity_radar.TopicEvidence("missing", "post", "invented", "supporting", "虚构"),)
                    ),
                ),
                needs=(opportunity_radar.EvidenceBackedClaim("Grounded need.", (source,)),),
                current_solutions=(opportunity_radar.EvidenceBackedClaim("Grounded solution.", (source,)),),
                gaps=(opportunity_radar.EvidenceBackedClaim("Grounded gap.", (source,)),),
                opportunity_hypotheses=(opportunity_radar.EvidenceBackedClaim("Grounded hypothesis.", (source,)),),
            ),)

    posts = tuple(_post(index, age_days=index + 1, author=f"owner-{index}") for index in range(3))
    result = opportunity_radar.TopicAggregator(
        pro=ClaimEvidencePro(), registry=opportunity_radar.TopicRegistry(tmp_path / "registry.json"), as_of=AS_OF
    ).aggregate("diesel", tuple(_signal(post) for post in posts))
    topic = result.formal_topics[0]

    assert topic["summary"] == "Grounded summary."
    assert topic["pains"] == ["Grounded pain."]
    assert topic["supporting_views"] == ["Cracking after winter use."]
    assert topic["opposing_views"] == ["Some owners report no crack."]
    exported = opportunity_radar.export_topic_analysis(result.analysis, output_dir=tmp_path / "artifacts")
    with ZipFile(exported.workbook_path) as workbook:
        xml = "".join(workbook.read(name).decode("utf-8") for name in workbook.namelist() if name.endswith(".xml"))
    assert "Grounded pain." in xml and "Unsupported pain." not in xml
    assert "Some owners report no crack." in xml
