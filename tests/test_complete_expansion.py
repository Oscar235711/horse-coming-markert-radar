"""Contracts for uncapped, same-run keyword/community expansion."""

from datetime import date
import json

from opportunity_radar.keywords import KeywordCandidate, select_round_two_terms
from opportunity_radar.library import (
    active_communities,
    active_keywords,
    load_project_library,
    update_project_library,
)
from opportunity_radar.models import CollectionScope


def _candidate(index: int) -> KeywordCandidate:
    return KeywordCandidate(
        term=f"specific diesel signal {index}",
        normalized_term=f"specific diesel signal {index}",
        categories=("product",),
        extraction_methods=("model",),
        evidence_ids=(f"e{index}a", f"e{index}b"),
        source_post_ids=(f"t3_{index}a", f"t3_{index}b"),
        authors=(f"owner-{index}-a", f"owner-{index}-b"),
        communities=("Cummins", "Diesel"),
        parent_formal_terms=(),
        score_breakdown={"unique_users": 16},
        penalties={"total": 0},
        discovery_score=80,
    )


def test_complete_depth_has_no_business_count_caps() -> None:
    scope = CollectionScope(date(2025, 9, 2), date(2026, 9, 1), "complete")

    assert scope.listing_limit_per_community is None
    assert scope.deep_read_limit_per_community is None


def test_round_two_complete_selection_does_not_truncate_at_twenty() -> None:
    candidates = tuple(_candidate(index) for index in range(35))

    selected = select_round_two_terms(candidates, max_terms=None)

    assert len(selected) == 35


def test_keyword_library_is_unique_by_normalized_term_and_exposes_active_items(tmp_path) -> None:
    analysis = {
        "generated_at": "2026-09-01T12:00:00+00:00",
        "communities": ["Cummins"],
        "topics": [],
        "keyword_library": {"candidates": [
            {
                "term_en": "EGR Cooler Failure",
                "term_zh": "EGR冷却器故障",
                "community": "Cummins",
                "source_post_ids": ["t3_a", "t3_b", "t3_c"],
                "author_count": 3,
                "post_count": 3,
                "score": 72,
                "status": "active",
            },
            {
                "term_en": "egr-cooler failure",
                "term_zh": "EGR冷却器故障",
                "community": "powerstroke",
                "source_post_ids": ["t3_d"],
                "author_count": 1,
                "post_count": 1,
                "score": 55,
                "status": "observed",
            },
        ]},
    }

    update_project_library(tmp_path, analysis, run_id="run-a")
    library = load_project_library(tmp_path)

    assert len(library["keywords"]) == 1
    assert library["keywords"][0]["normalized_term"] == "egr cooler failure"
    assert set(library["keywords"][0]["communities"]) == {"Cummins", "powerstroke"}
    assert active_keywords(tmp_path) == ("egr cooler failure",)


def test_observed_community_auto_activates_after_cross_post_evidence(tmp_path) -> None:
    document = {
        "version": "community-library.v1",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "communities": [{
            "key": "dieseltech",
            "subreddit": "r/DieselTech",
            "display_name": "DieselTech",
            "status": "observed",
            "source_post_ids": ["t3_a", "t3_b", "t3_c"],
            "run_ids": ["run-a"],
            "first_seen": "2026-09-01T00:00:00+00:00",
            "last_seen": "2026-09-01T00:00:00+00:00",
        }],
    }
    (tmp_path / "communities.json").write_text(json.dumps(document), encoding="utf-8")

    assert active_communities(tmp_path) == ("DieselTech",)

