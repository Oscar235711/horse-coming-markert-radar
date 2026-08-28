"""Deterministic, evidence-linked exploratory diesel keyword discovery."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from .deepseek import PostAnalysis
from .evidence import GatedEvidence


_STOPWORDS = frozenset({
    "a", "an", "and", "after", "any", "are", "at", "be", "been", "but", "by", "for", "from", "get",
    "i", "in", "is", "it", "my", "need", "of", "on", "or", "our", "so", "still", "that", "the", "this",
    "to", "what", "which", "with", "you", "your", "diesel", "truck", "part", "option",
})
_PAIN = re.compile(r"\b(leak|leaked|seep|seeping|fail|failed|broken|crack|cracked|regen|clog|issue|problem)\b", re.I)
_WORKAROUND = re.compile(r"\b(fix|fixed|replace|replaced|install|installed|clamp|solution)\b", re.I)
_PURCHASE = re.compile(r"\b(buy|bought|purchase|price|cost|order|ordered|recommend|what should i)\b", re.I)
_PROMOTIONAL = re.compile(r"\b(coupon|promo|affiliate|buy now|free shipping)\b", re.I)
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")

_TERM_ZH = {
    "ccv reroute": "CCV重定向",
    "crankcase ventilation": "曲轴箱通风",
    "dpf delete pipe": "DPF删除管",
    "egr delete kit": "EGR删除套件",
    "downpipe": "下降管",
    "clamp kit": "卡箍套件",
    "stronger clamp kit": "加强型卡箍套件",
}


@dataclass(frozen=True, slots=True)
class KeywordCandidate:
    """One exploratory term, its source evidence, and independently recomputable score."""

    term: str
    normalized_term: str
    categories: tuple[str, ...]
    extraction_methods: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_post_ids: tuple[str, ...]
    authors: tuple[str, ...]
    communities: tuple[str, ...]
    parent_formal_terms: tuple[str, ...]
    score_breakdown: Mapping[str, int]
    penalties: Mapping[str, int]
    discovery_score: int
    status: str = "candidate_review"
    purchase_signal_count: int = 0
    pain_signal_count: int = 0
    workaround_signal_count: int = 0
    promotional_signal_count: int = 0

    @property
    def unique_user_count(self) -> int:
        return len(self.authors)

    @property
    def community_count(self) -> int:
        return len(self.communities)


def discover_diesel_keywords(
    evidence: Sequence[GatedEvidence], *, dictionaries: Any, formal_terms: Sequence[str],
    analyses: Mapping[str, PostAnalysis] | None = None,
) -> tuple[KeywordCandidate, ...]:
    """Derive unapproved terms from qualified evidence only; formal inputs are never changed."""
    formal = frozenset(_normalise(term) for term in formal_terms if _normalise(term))
    dictionary_terms = tuple(
        _normalise(term) for group in ("products", "vehicle_terms", "scenarios", "slang")
        for term in getattr(dictionaries, group, ()) if _normalise(term)
    )
    known_brands = frozenset(_normalise(term) for term in getattr(dictionaries, "brands", ()) if _normalise(term))
    aggregate: dict[str, dict[str, Any]] = {}
    for gated in evidence:
        if not gated.quality.eligible:
            continue
        record = gated.record
        evidence_id = _text(record.get("id")) or _text(record.get("post_id"))
        post_id = _text(record.get("post_id")) or evidence_id
        if not evidence_id or not post_id:
            continue
        text = " ".join(_text(record.get(field)) for field in ("title", "body", "body_original"))
        terms: dict[str, set[str]] = defaultdict(set)
        for term in dictionary_terms:
            if _contains(text, term):
                terms[term].add("dictionary")
        for term in _ngrams(text):
            terms[term].add("ngram")
        analysis = (analyses or {}).get(post_id)
        if analysis is not None:
            for field in analysis.keyword_candidates:
                if field.status != "unknown" and field.evidence_ids:
                    normal = _normalise(field.value)
                    if normal:
                        terms[normal].add("model")
        parents = tuple(sorted(term for term in formal if _contains(text, term)))
        for term, methods in terms.items():
            if not _keep(term, formal, known_brands):
                continue
            item = aggregate.setdefault(term, _shell(term))
            item["methods"].update(methods)
            item["evidence_ids"].add(evidence_id)
            item["source_post_ids"].add(post_id)
            if author := _text(record.get("author")):
                item["authors"].add(author)
            if community := _text(record.get("subreddit")):
                item["communities"].add(community)
            item["parents"].update(parents)
            item["purchase"] += int(bool(_PURCHASE.search(text)))
            item["pain"] += int(bool(_PAIN.search(text)))
            item["workaround"] += int(bool(_WORKAROUND.search(text)))
            item["promotional"] += int(bool(_PROMOTIONAL.search(text)))
    return tuple(sorted((_candidate(item, formal) for item in aggregate.values()), key=lambda item: (-item.discovery_score, item.term)))


def select_round_two_terms(
    candidates: Sequence[KeywordCandidate], *, max_terms: int = 20, minimum_score: int = 65,
    minimum_users: int = 2, minimum_communities: int = 2,
) -> tuple[str, ...]:
    """Return the only terms allowed to issue second-round queries."""
    return tuple(
        candidate.term for candidate in candidates
        if candidate.status not in {"formal", "rejected"}
        and candidate.discovery_score >= minimum_score
        and candidate.unique_user_count >= minimum_users
        and candidate.community_count >= minimum_communities
    )[:max_terms]


def build_topic_keyword_library(
    posts: Sequence[Any], comments: Sequence[Any], analyses: Sequence[PostAnalysis], *, formal_terms: Sequence[str] = ()
) -> dict[str, Any]:
    """Build a deterministic, source-linked keyword table from collected text and post analyses."""
    post_by_id = {_obj_value(post, "post_id"): post for post in posts if _obj_value(post, "post_id")}
    analysis_by_id = {
        _obj_value(post, "post_id"): analysis
        for post, analysis in zip(posts, analyses)
        if _obj_value(post, "post_id")
    }
    aggregate: dict[str, dict[str, Any]] = {}

    def add(term: str, *, post_id: str = "", comment_id: str = "", author: str = "", method: str = "text", topic_key: str = "") -> None:
        normalized = _normalise(term)
        if not normalized or len(normalized.split()) < 2 or normalized in {"diesel truck", "pickup truck", "diesel pickup"}:
            return
        bucket = aggregate.setdefault(normalized, {"variants": set(), "post_ids": set(), "comment_ids": set(), "authors": set(), "methods": set(), "topics": set()})
        bucket["variants"].add(str(term).strip())
        if post_id:
            bucket["post_ids"].add(post_id)
        if comment_id:
            bucket["comment_ids"].add(comment_id)
        if author:
            bucket["authors"].add(author)
        bucket["methods"].add(method)
        if topic_key:
            bucket["topics"].add(topic_key)

    for post in posts:
        post_id = _obj_value(post, "post_id")
        analysis = analysis_by_id.get(post_id)
        text = " ".join((_obj_value(post, "title"), _obj_value(post, "body")))
        for term in _ngrams(text):
            add(term, post_id=post_id, author=_obj_value(post, "author"), method="ngram")
        if analysis is not None:
            topic_key = analysis.topics[0].label if analysis.topics else ""
            for field in (*analysis.keyword_candidates, *analysis.topic_candidates):
                if field.value != "unknown" and field.status != "unknown":
                    add(field.value, post_id=post_id, author=_obj_value(post, "author"), method="analysis", topic_key=topic_key)
            for field in (*analysis.products, *analysis.pain_points, *analysis.current_solutions, *analysis.gaps):
                if field.value != "unknown" and field.status != "unknown":
                    add(field.value, post_id=post_id, author=_obj_value(post, "author"), method="analysis", topic_key=topic_key)

    for comment in comments:
        post_id = _obj_value(comment, "post_id")
        comment_id = _obj_value(comment, "comment_id")
        for term in _ngrams(_obj_value(comment, "body")):
            add(term, post_id=post_id, comment_id=comment_id, author=_obj_value(comment, "author"), method="comment")

    formal = {_normalise(term) for term in formal_terms if _normalise(term)}
    candidates: list[dict[str, Any]] = []
    for term, item in aggregate.items():
        post_count = len(item["post_ids"])
        author_count = len(item["authors"])
        score = min(100, post_count * 12 + author_count * 8 + len(item["comment_ids"]) * 2)
        candidates.append({
            "keyword_id": "kw_" + re.sub(r"[^a-z0-9]+", "_", term).strip("_")[:48],
            "term_en": term,
            "term_zh": _TERM_ZH.get(term, "待翻译"),
            "keyword_type": _keyword_type(term),
            "community": _obj_value(post_by_id.get(next(iter(item["post_ids"]), "")), "subreddit") if item["post_ids"] else "",
            "topic_key": sorted(item["topics"])[0] if item["topics"] else "",
            "variants": sorted(item["variants"]),
            "source_post_ids": sorted(item["post_ids"]),
            "source_comment_ids": sorted(item["comment_ids"]),
            "post_count": post_count,
            "author_count": author_count,
            "signal_types": sorted(item["methods"]),
            "score": score,
            "status": "configured" if term in formal else ("candidate_review" if score >= 20 else "weak_signal"),
        })
    candidates.sort(key=lambda item: (-item["score"], item["term_en"]))
    # Keep the review table useful on real comment-heavy runs. Every retained
    # row still has source IDs; low-signal tail terms remain reproducible in
    # raw comments rather than overwhelming the report.
    candidates = [item for item in candidates if item["post_count"] or item["source_comment_ids"]][:500]
    return {"version": "topic-keywords.v1", "formal_terms": sorted(formal), "candidates": candidates}


def _obj_value(value: Any, key: str) -> str:
    """Read a field from either a dataclass/object or a normalized mapping."""
    if isinstance(value, Mapping):
        raw = value.get(key, "")
    else:
        raw = getattr(value, key, "")
    return str(raw or "")


def _keyword_type(term: str) -> str:
    if re.search(r"\b(leak|failure|failed|broken|crack|regen|clog|problem|issue)\b", term):
        return "pain"
    if re.search(r"\b(kit|pipe|tuner|clamp|valve|cooler|downpipe|reroute)\b", term):
        return "product_or_solution"
    if re.search(r"\b(towing|hauling|commute|winter|off road|work truck)\b", term):
        return "scenario"
    return "phrase"


def _shell(term: str) -> dict[str, Any]:
    return {"term": term, "methods": set(), "evidence_ids": set(), "source_post_ids": set(), "authors": set(),
            "communities": set(), "parents": set(), "purchase": 0, "pain": 0, "workaround": 0, "promotional": 0}


def _candidate(item: Mapping[str, Any], formal: frozenset[str]) -> KeywordCandidate:
    users = min(len(item["authors"]), 5) * 8
    communities = min(len(item["communities"]), 3) * 5
    specificity = 15 if len(item["term"].split()) >= 2 else 6
    purchase = min(item["purchase"] * 5, 15)
    pain = min(item["pain"] * 4 + item["workaround"] * 2, 10)
    anchor = min(len(item["parents"]) * 5, 10)
    score_breakdown = {"unique_users": users, "cross_community": communities, "specificity": specificity,
                       "purchase_intent": purchase, "pain_or_workaround": pain, "anchor_cooccurrence": anchor, "novelty": 10}
    penalties = {"one_user_dominance": 10 if len(item["authors"]) < 2 else 0,
                 "one_thread_dominance": 6 if len(item["source_post_ids"]) < 2 and len(item["evidence_ids"]) > 1 else 0,
                 "brand_only": 0, "promotional_language": min(item["promotional"] * 5, 10),
                 "generic_language": 12 if len(item["term"].split()) == 1 else 0, "excluded_evidence": 0}
    penalties["total"] = sum(penalties.values())
    score = max(0, min(100, sum(score_breakdown.values()) - penalties["total"]))
    return KeywordCandidate(item["term"], item["term"], _categories(item["term"]), tuple(sorted(item["methods"])),
        tuple(sorted(item["evidence_ids"])), tuple(sorted(item["source_post_ids"])), tuple(sorted(item["authors"])),
        tuple(sorted(item["communities"])), tuple(sorted(item["parents"])), score_breakdown, penalties, score,
        "candidate_review" if score else "rejected", item["purchase"], item["pain"], item["workaround"], item["promotional"])


def _categories(term: str) -> tuple[str, ...]:
    if re.search(r"\b(leak|seep|regen|fail|crack|clog)\b", term): return ("pain",)
    if re.search(r"\b(ram|ford|silverado|sierra|f-?250|f-?350)\b", term): return ("fitment",)
    return ("product",)


def _ngrams(text: str) -> tuple[str, ...]:
    tokens = _TOKEN.findall(_normalise(text))
    terms: set[str] = set()
    for size in (2, 3, 4):
        for offset in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[offset:offset + size])
            if (tokens[offset] not in _STOPWORDS and tokens[offset + size - 1] not in _STOPWORDS
                    and any(token not in _STOPWORDS for token in tokens[offset:offset + size])):
                terms.add(phrase)
    return tuple(sorted(terms))


def _keep(term: str, formal: frozenset[str], brands: frozenset[str]) -> bool:
    tokens = term.split()
    return bool(term and term not in formal and len(tokens) >= 2 and not all(token in _STOPWORDS for token in tokens)
                and not any(brand in tokens for brand in brands))


def _normalise(value: object) -> str:
    return " ".join(_TOKEN.findall(str(value).casefold().replace("-", " ")))


def _contains(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term).replace(r'\ ', r'\s+')}(?!\w)", _normalise(text)))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
