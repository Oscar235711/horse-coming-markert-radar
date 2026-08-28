from datetime import UTC, datetime

from opportunity_radar.collector import ThreadComment
from opportunity_radar.deepseek import AnalysisField, PostAnalysis, TopicCandidate
from opportunity_radar.keywords import build_topic_keyword_library
from opportunity_radar.models import NormalizedPost


def test_topic_keyword_library_keeps_source_ids_and_separates_brand_only_terms() -> None:
    post = NormalizedPost(
        post_id="t3_a",
        url="https://www.reddit.com/r/Cummins/comments/a",
        subreddit="Cummins",
        title="6.7 Cummins CCV reroute leaking after towing",
        body="The CCV reroute kit failed and I need a better clamp solution.",
        author="owner-a",
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        score=8,
        comment_count=2,
        source_surfaces=("hot",),
    )
    comment = ThreadComment("c1", "I replaced the clamp and would buy a stronger kit.", post.url + "?c=c1", "commenter")
    analysis = PostAnalysis(
        topics=(TopicCandidate("CCV reroute failure", ("post",)),),
        claims=(),
        platform=AnalysisField("Cummins", ("post",), "fact"),
        keyword_candidates=(AnalysisField("stronger clamp kit", ("post",), "fact"),),
    )

    library = build_topic_keyword_library((post,), (comment,), (analysis,), formal_terms=("cummins",))

    terms = {item["term_en"]: item for item in library["candidates"]}
    assert "stronger clamp kit" in terms
    assert terms["stronger clamp kit"]["source_post_ids"] == ["t3_a"]
    assert "ford" not in terms
