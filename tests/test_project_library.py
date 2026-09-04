from datetime import UTC, datetime
import json
from pathlib import Path

from opportunity_radar.library import active_communities, active_keywords, load_project_library, update_project_library
from opportunity_radar.models import NormalizedPost


def _post(post_id: str, subreddit: str, *, title: str, body: str, author: str) -> NormalizedPost:
    return NormalizedPost(
        post_id=post_id,
        url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/example",
        subreddit=subreddit,
        title=title,
        body=body,
        author=author,
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
        score=12,
        comment_count=2,
        source_surfaces=("hot",),
    )


def test_project_library_upserts_communities_topics_and_keywords_across_runs(tmp_path: Path) -> None:
    first = {
        "generated_at": "2026-08-28T10:00:00+00:00",
        "communities": ["Cummins"],
        "community_library": [{"display_name": "Cummins", "subreddit": "r/Cummins", "platform": "Cummins"}],
        "topics": [{
            "topic_id": "topic_a", "community": "Cummins", "canonical_key": "regen issue",
            "label_en": "Regeneration issue", "label_zh": "再生问题", "status": "formal",
            "post_count": 1, "author_count": 1, "commenter_count": 1, "heat_score": 32,
            "pains": ["Regeneration interrupts towing"], "gaps": ["No clear fitment guidance"],
            "opportunity_hypotheses": ["Opportunity hypothesis: towing-friendly monitoring kit"],
            "evidence": [{"post_id": "t3_a", "url": "https://www.reddit.com/r/Cummins/comments/a", "evidence_id": "t3_a:post"}],
        }],
        "keyword_library": {"candidates": [{
            "keyword_id": "kw_regen", "term_en": "regen issue", "term_zh": "再生问题",
            "keyword_type": "pain", "community": "Cummins", "topic_key": "regen issue",
            "variants": ["regen problem"], "source_post_ids": ["t3_a"], "source_comment_ids": [],
            "post_count": 1, "author_count": 1, "score": 20, "status": "observed",
        }]},
    }
    second = {
        "generated_at": "2026-08-29T10:00:00+00:00",
        "communities": ["cummins", "Duramax"],
        "community_library": [
            {"display_name": "cummins", "subreddit": "r/cummins", "platform": "Cummins"},
            {"display_name": "Duramax", "subreddit": "r/Duramax", "platform": "Duramax"},
        ],
        "topics": [{
            "topic_id": "topic_a", "community": "cummins", "canonical_key": "regen issue",
            "label_en": "Regeneration issue", "label_zh": "再生问题", "status": "formal",
            "post_count": 1, "author_count": 1, "commenter_count": 2, "heat_score": 48,
            "pains": ["Regeneration interrupts towing"], "gaps": ["No clear fitment guidance"],
            "opportunity_hypotheses": ["Opportunity hypothesis: towing-friendly monitoring kit"],
            "evidence": [{"post_id": "t3_a", "url": "https://www.reddit.com/r/Cummins/comments/a", "evidence_id": "t3_a:post"}],
        }],
        "keyword_library": {"candidates": [{
            "keyword_id": "kw_regen", "term_en": "regen issue", "term_zh": "再生问题",
            "keyword_type": "pain", "community": "cummins", "topic_key": "regen issue",
            "variants": ["regen problem", "regen issue"], "source_post_ids": ["t3_a"], "source_comment_ids": ["c1"],
            "post_count": 1, "author_count": 1, "score": 45, "status": "observed",
        }]},
    }
    posts = [_post("t3_a", "Cummins", title="Need help with regen", body="Also see r/Diesel for towing advice", author="owner")]

    first_result = update_project_library(tmp_path, first, run_id="run-1", posts=posts, comments=[])
    second_result = update_project_library(tmp_path, second, run_id="run-2", posts=posts, comments=[])
    document = load_project_library(tmp_path)

    communities = {item["key"]: item for item in document["communities"]}
    assert set(communities) == {"cummins", "duramax", "diesel"}
    assert communities["cummins"]["run_count"] == 2
    assert communities["cummins"]["source_post_count"] == 1
    assert communities["diesel"]["status"] == "observed"

    topics = document["topics"]
    assert len(topics) == 1
    assert topics[0]["topic_id"] == "topic_a"
    assert topics[0]["run_count"] == 2
    assert topics[0]["source_post_count"] == 1
    assert topics[0]["commenter_count_max"] == 2

    keywords = document["keywords"]
    assert len(keywords) == 1
    assert keywords[0]["normalized_term"] == "regen issue"
    assert keywords[0]["run_count"] == 2
    assert keywords[0]["source_comment_count"] == 1
    assert first_result["topic_count"] == 1
    assert second_result["community_count"] == 3

    # Files are plain UTF-8 JSON and do not contain raw post bodies.
    assert json.loads((tmp_path / "communities.json").read_text(encoding="utf-8"))["version"] == "community-library.v1"
    assert "Also see" not in (tmp_path / "communities.json").read_text(encoding="utf-8")


def test_library_auto_activates_only_diesel_evidence_and_quarantines_generic_noise(tmp_path: Path) -> None:
    """A three-post threshold must not promote game communities or sentence fragments."""
    analysis = {
        "generated_at": "2026-09-04T10:00:00+00:00",
        "communities": ["Cummins"],
        "topics": [],
        "keyword_library": {"candidates": [
            {
                "term_en": "cummins downpipe fitment", "term_zh": "Cummins下降管适配",
                "source_post_ids": ["diesel-1", "diesel-2", "diesel-3"], "author_count": 3,
                "post_count": 3, "score": 78, "status": "observed", "community": "DieselTech",
            },
            {
                "term_en": "lot of work", "term_zh": "很多工作量",
                "source_post_ids": ["diesel-1", "diesel-2", "diesel-3"], "author_count": 3,
                "post_count": 3, "score": 78, "status": "observed", "community": "DieselTech",
            },
        ]},
    }
    posts = [
        _post(f"diesel-{index}", "DieselTech", title="Cummins diesel downpipe fitment", body="Need a diesel truck installation solution", author=f"owner-{index}")
        for index in range(1, 4)
    ] + [
        _post("game-1", "GameProfessional", title="Game career advice", body="Looking for a job in games", author="gamer"),
    ]

    update_project_library(tmp_path, analysis, run_id="run-clean", posts=posts)
    communities = {item["key"]: item for item in load_project_library(tmp_path)["communities"]}

    assert communities["cummins"]["status"] == "seed"
    assert communities["dieseltech"]["status"] == "active"
    assert communities["gameprofessional"]["status"] == "quarantined"
    assert active_communities(tmp_path) == ("Cummins", "DieselTech")
    assert active_keywords(tmp_path) == ("cummins downpipe fitment",)
