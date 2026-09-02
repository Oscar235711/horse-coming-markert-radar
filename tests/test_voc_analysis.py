from datetime import datetime, timezone

from opportunity_radar.collector import ThreadComment, ThreadDocument
from opportunity_radar.deepseek import AnalysisField, PostAnalysis
from opportunity_radar.models import NormalizedPost
from opportunity_radar.topics import EvidenceBackedClaim, PostSignal
from opportunity_radar.voc_analysis import extract_post_voc, synthesize_topic_voc


def _signal(post_id: str, author: str, body: str, comments=()):
    post = NormalizedPost(
        post_id=post_id,
        url=f"https://www.reddit.com/r/Cummins/comments/{post_id}/demo",
        subreddit="Cummins",
        title="Need help with a diesel fitment problem",
        body=body,
        author=author,
        created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        score=10,
        comment_count=len(comments),
        source_surfaces=("hot",),
    )
    thread = ThreadDocument(post=post, comments=tuple(comments))
    analysis = PostAnalysis(topics=(), claims=())
    return PostSignal.from_thread(thread, analysis)


def test_extract_post_voc_keeps_source_and_real_fields():
    signal = _signal(
        "p1",
        "owner_one",
        "I tow a 10k trailer. The replacement hose still leaks after install. I replaced it with an aftermarket kit.",
        (ThreadComment("c1", "The clamp did not fit and I had to redo it.", "https://www.reddit.com/c1", "reply_one"),),
    )
    voc = extract_post_voc(signal)
    assert voc.pains
    assert voc.pains[0].evidence_ids
    assert voc.pains[0].source_text
    assert voc.solutions
    assert not any("更可靠的适配" in claim.text for claim in voc.needs)


def test_synthesize_topic_voc_does_not_copy_same_evidence_to_every_claim():
    signals = (
        _signal("p1", "owner_one", "The replacement hose still leaks after install."),
        _signal("p2", "owner_two", "The replacement hose does not fit; I had to modify the clamp."),
    )
    topic = synthesize_topic_voc(signals, "coolant_leak")
    pains = topic.claims["pain"]
    assert len(pains) >= 2
    assert len({claim.evidence_ids for claim in pains}) == len(pains)
    assert all(claim.post_count == len(claim.post_ids) for claim in pains)


def test_synthesize_topic_voc_returns_no_product_without_repeated_explicit_gap():
    topic = synthesize_topic_voc((_signal("p1", "owner_one", "My truck is fine today."),), "coolant_leak")
    assert topic.opportunity_status == "no_product"
    assert topic.opportunity_hypotheses == ()


def test_evidence_backed_claim_carries_recurrence_metadata():
    claim = EvidenceBackedClaim(
        "用户报告泄漏或渗漏",
        (),
        status="fact",
        field="pain",
        post_ids=("p1", "p2"),
        author_ids=("a1", "a2"),
        frequency=2,
    )
    assert claim.field == "pain"
    assert claim.post_ids == ("p1", "p2")
    assert claim.frequency == 2
