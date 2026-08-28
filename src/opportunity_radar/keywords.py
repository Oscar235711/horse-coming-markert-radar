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
