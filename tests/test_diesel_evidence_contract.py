"""Diesel-specific evidence quality and Flash extraction contracts."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import opportunity_radar


def test_diesel_direct_experience_is_auditable_and_recomputable() -> None:
    """A real owner outcome must stay distinct from an unsupported opinion."""
    result = opportunity_radar.classify_diesel_evidence(
        {
            "id": "owner-1",
            "author": "ram_owner",
            "subreddit": "Cummins",
            "title": "EGR cooler failure after towing",
            "body": "I replaced the EGR cooler on my 2018 6.7 Cummins after it leaked while towing 12,000 lb. The aftermarket kit fit, but the clamps still seep.",
            "score": 4,
        }
    )

    assert result.evidence_role == "direct_experience"
    assert result.claim_status == "fact"
    assert result.eligible is True
    assert result.hard_exclusion is False
    assert "first_person_experience" in result.reason_codes
    assert result.quality_score == max(0, min(100, sum(result.components.values()) - result.penalties["total"]))


def test_diesel_hard_relevance_exclusions_cannot_be_rescued_by_score() -> None:
    """Gasoline, motorcycle, promotional, and bot records are not diesel-pickup evidence."""
    records = (
        {"id": "gas", "author": "owner", "subreddit": "Ford", "body": "My Mustang downpipe made 500 hp.", "score": 5000},
        {"id": "bike", "author": "owner", "subreddit": "motorcycles", "body": "Installed a catless downpipe on my bike.", "score": 5000},
        {"id": "ad", "author": "seller", "subreddit": "Cummins", "body": "Use coupon code SAVE20 and buy now.", "score": 5000},
        {"id": "bot", "author": "AutoModerator", "subreddit": "Cummins", "body": "Community rules", "score": 5000},
    )

    gated = opportunity_radar.apply_diesel_evidence_gate(records)

    assert gated.qualified == ()
    assert [item.quality.reason_codes[0] for item in gated.excluded] == [
        "non_diesel_or_non_pickup",
        "non_diesel_or_non_pickup",
        "affiliate_or_coupon",
        "bot_author",
    ]
    assert all(item.quality.quality_score == 0 for item in gated.excluded)


def test_bare_product_terms_need_an_approved_diesel_community_or_platform_evidence() -> None:
    """Generic gasoline downpipe/tuner chatter must not enter the diesel evidence pool."""
    domain = opportunity_radar.load_diesel_domain_config(Path("configs/diesel_90d.yaml"))
    generic = opportunity_radar.classify_diesel_evidence(
        {"id": "generic", "subreddit": "AskCars", "body": "Which catless downpipe and tuner should I buy?"},
        dictionaries=domain.dictionaries,
        exclusions=domain.exclusions,
        approved_communities=("Cummins", "Duramax", "powerstroke", "FordDiesels"),
    )
    approved = opportunity_radar.classify_diesel_evidence(
        {"id": "approved", "subreddit": "Cummins", "body": "Which downpipe and tuner should I buy for towing?"},
        dictionaries=domain.dictionaries,
        exclusions=domain.exclusions,
        approved_communities=("Cummins", "Duramax", "powerstroke", "FordDiesels"),
    )

    assert generic.hard_exclusion is True
    assert generic.reason_codes == ("missing_diesel_context",)
    assert approved.evidence_role == "contextual_demand"
    assert approved.eligible is True
    assert approved.opportunity_weight < 1.0


def test_flash_contract_keeps_fact_inference_and_unknown_fields_separate() -> None:
    """Structured fields must retain citations and never promote invented facts."""
    post = opportunity_radar.NormalizedPost(
        post_id="t3_owner-1",
        url="https://www.reddit.com/r/Cummins/comments/owner-1/example",
        subreddit="Cummins",
        title="EGR cooler failure",
        body="My 2018 6.7 Cummins leaks while towing.",
        author="owner",
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
        score=1,
        comment_count=1,
        source_surfaces=("hot",),
    )
    thread = opportunity_radar.ThreadDocument(
        post=post,
        comments=(opportunity_radar.ThreadComment("c1", "Try new clamps.", post.url + "?comment=c1"),),
    )
    payload = {
        "platform": {"value": "Cummins", "evidence_ids": ["post"], "status": "fact"},
        "vehicle": {"value": "Ram 2500", "evidence_ids": ["post"], "status": "inference"},
        "year": {"value": "2018", "evidence_ids": ["post"], "status": "fact"},
        "scenario": {"value": "towing", "evidence_ids": ["post"], "status": "fact"},
        "goal": {"value": "stop leak", "evidence_ids": ["post"], "status": "inference"},
        "pain_points": [{"value": "EGR cooler leaks", "evidence_ids": ["post"], "status": "fact"}],
        "needs": [{"value": "durable clamps", "evidence_ids": ["c1"], "status": "inference"}],
        "current_solutions": [],
        "gaps": [],
        "opportunity_hypotheses": [{"value": "better clamp bundle", "evidence_ids": ["missing"], "status": "fact"}],
        "products": [], "brands": [], "competitors": [], "purchase_intent": [], "sentiment": {"value": "negative", "evidence_ids": ["post"], "status": "fact"},
        "keyword_candidates": [], "topic_candidates": [{"value": "EGR durability", "evidence_ids": ["post"], "status": "fact"}],
        "topics": [], "claims": [],
    }

    class Transport:
        def __call__(self, method, url, headers, request):
            return opportunity_radar.HttpResponse(200, json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}))

    analysis = opportunity_radar.DeepSeekClient(
        transport=Transport(), environment={"DEEPSEEK_API_KEY": "test-key"}
    ).extract_post(thread)

    assert analysis.platform.value == "Cummins"
    assert analysis.platform.status == "fact"
    assert analysis.vehicle.status == "inference"
    assert analysis.opportunity_hypotheses[0].status == "unknown"
    assert analysis.opportunity_hypotheses[0].evidence_ids == ()
    assert analysis.topic_candidates[0].value == "EGR durability"


def test_flash_contract_drops_malformed_scalar_and_list_entries() -> None:
    """Only the documented object/array wire shapes can enter saved post analysis."""
    post = opportunity_radar.NormalizedPost(
        post_id="t3_malformed", url="https://reddit.example/post", subreddit="Cummins", title="x", body="y",
        author="owner", created_at=datetime(2026, 8, 26, tzinfo=UTC), score=0, comment_count=0, source_surfaces=("hot",),
    )
    payload = {
        "platform": "Cummins",
        "pain_points": {"value": "not-an-array"},
        "needs": ["not-an-object", {"value": "valid need", "evidence_ids": ["post"], "status": "fact"}],
        "topics": [], "claims": [],
    }

    class Transport:
        def __call__(self, method, url, headers, request):
            return opportunity_radar.HttpResponse(200, json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}))

    analysis = opportunity_radar.DeepSeekClient(
        transport=Transport(), environment={"DEEPSEEK_API_KEY": "test-key"}
    ).extract_post(opportunity_radar.ThreadDocument(post=post, comments=()))

    assert analysis.platform.status == "unknown"
    assert analysis.pain_points == ()
    assert [item.value for item in analysis.needs] == ["valid need"]


def test_diesel_config_exposes_domain_dictionaries_and_disables_profile_deep_dive() -> None:
    """The checked-in scan contract must be concrete and safe for this phase."""
    document = opportunity_radar.load_diesel_domain_config(Path("configs/diesel_90d.yaml"))

    assert "cummins" in document.dictionaries.platforms
    assert "dpf delete pipe" in document.dictionaries.products
    assert "motorcycle" in document.exclusions.non_diesel_terms
    assert document.keyword_search.enabled is True
    assert document.report.formats == ("json", "xlsx", "html")
    assert document.user_deep_dive_enabled is False


def test_deepseek_higress_settings_remain_environment_configurable() -> None:
    """A gateway URL and Flash deployment name are read from environment, never YAML secrets."""
    calls: list[tuple[str, str, dict, dict]] = []

    def transport(method, url, headers, payload):
        calls.append((method, url, headers, payload))
        return opportunity_radar.HttpResponse(200, json.dumps({"choices": [{"message": {"content": "{}"}}]}))

    client = opportunity_radar.DeepSeekClient(
        transport=transport,
        environment={
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_BASE_URL": "https://higress.example/v1",
            "DEEPSEEK_FLASH_MODEL": "gateway-flash",
        },
    )
    client.extract_post(
        opportunity_radar.ThreadDocument(
            post=opportunity_radar.NormalizedPost(
                post_id="t3_gateway", url="https://reddit.example/post", subreddit="Cummins", title="x", body="y",
                author="a", created_at=datetime(2026, 8, 26, tzinfo=UTC), score=0, comment_count=0, source_surfaces=("hot",),
            ),
            comments=(),
        )
    )

    assert calls[0][1] == "https://higress.example/v1/chat/completions"
    assert calls[0][3]["model"] == "gateway-flash"
    assert "test-key" not in json.dumps(calls[0][3])


def test_existing_topic_seed_fallback_preserves_diesel_analysis_fields() -> None:
    """The pre-existing fallback may add a topic but must not discard structured facts."""
    post = opportunity_radar.NormalizedPost(
        post_id="t3_fallback", url="https://reddit.example/post", subreddit="Cummins", title="x", body="y",
        author="a", created_at=datetime(2026, 8, 26, tzinfo=UTC), score=0, comment_count=0, source_surfaces=("hot",),
    )
    payload = {
        "topics": [],
        "claims": [{"claim": "EGR cooler leaks", "evidence_ids": ["post"], "urls": [post.url]}],
        "platform": {"value": "Cummins", "evidence_ids": ["post"], "status": "fact"},
    }

    class Transport:
        def __call__(self, method, url, headers, request):
            return opportunity_radar.HttpResponse(200, json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}))

    analysis = opportunity_radar.DeepSeekClient(
        transport=Transport(), environment={"DEEPSEEK_API_KEY": "test-key"}
    ).extract_post(opportunity_radar.ThreadDocument(post=post, comments=()))

    assert analysis.topics[0].label == "EGR cooler leaks"
    assert analysis.platform.value == "Cummins"
