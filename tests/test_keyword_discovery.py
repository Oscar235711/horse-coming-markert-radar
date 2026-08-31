"""Contracts for auditable diesel exploratory keyword discovery."""

from __future__ import annotations

from dataclasses import asdict

import opportunity_radar


def _record(identifier: str, author: str, community: str, text: str) -> dict[str, object]:
    return {
        "id": identifier,
        "post_id": f"t3_{identifier}",
        "author": author,
        "subreddit": community,
        "title": "Diesel maintenance experience",
        "body": text,
        "score": 4,
    }


def test_keyword_discovery_keeps_formal_terms_immutable_and_records_provenance() -> None:
    """Changing the config or dropping source attribution would make a round-two query unauditable."""
    dictionaries = opportunity_radar.DieselDictionaries(
        platforms=("cummins", "power stroke"), products=("egr cooler", "egr valve"),
        vehicle_terms=("ram 2500",), scenarios=("towing",), brands=("ford", "ram"), slang=("regen",),
    )
    formal_terms = ("egr cooler", "cummins")
    before = formal_terms
    gate = opportunity_radar.apply_diesel_evidence_gate(
        (
            _record("post-a", "alice", "Cummins", "My 6.7 Cummins EGR cooler leaked while towing. I need a heavy duty clamp kit."),
            _record("post-b", "bob", "powerstroke", "I replaced an EGR cooler and the heavy-duty clamp kit stopped the leak."),
            _record("post-c", "carol", "Cummins", "After towing, the egr cooler heavy duty clamp kit still seeps. What should I buy?"),
        ),
        dictionaries=dictionaries,
        approved_communities=("Cummins", "powerstroke"),
    )
    analyses = {
        "t3_post-a": opportunity_radar.PostAnalysis(
            topics=(), claims=(),
            keyword_candidates=(opportunity_radar.AnalysisField("heavy duty clamp kit", ("post",), "fact"),),
        ),
    }

    candidates = opportunity_radar.discover_diesel_keywords(
        gate.qualified, dictionaries=dictionaries, formal_terms=formal_terms, analyses=analyses
    )
    by_term = {candidate.term: candidate for candidate in candidates}

    assert formal_terms == before
    candidate = by_term["heavy duty clamp kit"]
    assert candidate.evidence_ids == ("post-a", "post-b", "post-c")
    assert candidate.source_post_ids == ("t3_post-a", "t3_post-b", "t3_post-c")
    assert candidate.authors == ("alice", "bob", "carol")
    assert candidate.communities == ("Cummins", "powerstroke")
    assert set(candidate.extraction_methods) >= {"model", "ngram"}
    assert candidate.parent_formal_terms == ("cummins", "egr cooler")
    assert candidate.status == "candidate_review"
    assert candidate.score_breakdown["unique_users"] == 24
    assert candidate.discovery_score >= 65
    assert "egr cooler" not in by_term
    assert all(asdict(item)["status"] != "formal" for item in candidates)


def test_round_two_selection_requires_score_two_users_and_two_communities() -> None:
    """A single enthusiastic owner must not expand the search surface on their own."""
    candidates = (
        opportunity_radar.KeywordCandidate(
            term="heavy duty clamp kit", normalized_term="heavy duty clamp kit", categories=("product",),
            extraction_methods=("ngram",), evidence_ids=("a", "b"), source_post_ids=("t3_a", "t3_b"),
            authors=("alice", "bob"), communities=("Cummins", "powerstroke"), parent_formal_terms=(),
            score_breakdown={"unique_users": 16}, penalties={"total": 0}, discovery_score=65,
        ),
        opportunity_radar.KeywordCandidate(
            term="one owner idea", normalized_term="one owner idea", categories=("product",),
            extraction_methods=("model",), evidence_ids=("c",), source_post_ids=("t3_c",),
            authors=("carol",), communities=("Cummins",), parent_formal_terms=(),
            score_breakdown={"unique_users": 8}, penalties={"one_user_dominance": 10, "total": 10}, discovery_score=95,
        ),
    )

    assert opportunity_radar.select_round_two_terms(candidates) == ("heavy duty clamp kit",)
