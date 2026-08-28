"""Deterministic, diesel-pickup evidence quality classification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import re
from typing import Any


EVIDENCE_ROLES = (
    "direct_experience",
    "qualified_practitioner",
    "contextual_demand",
    "market_observation",
    "weak",
    "noise",
)
_COMPONENT_KEYS = (
    "first_person_or_practitioner",
    "product_specificity",
    "context",
    "observable_outcome",
    "purchase_signal",
    "diagnostic_detail",
    "corroboration",
    "engagement",
)
_PENALTY_KEYS = (
    "advertising_language",
    "low_information_density",
    "quotation_without_personal_context",
    "suspected_duplication",
)

# These are deliberately domain terms rather than an automotive-lighting transplant.
DIESEL_PRODUCTS = (
    "dpf", "egr", "def", "ccv", "pcv", "downpipe", "tuner", "tune file",
    "delete pipe", "delete kit", "egr cooler", "egr valve", "crankcase ventilation",
)
DIESEL_PLATFORMS = (
    "cummins", "powerstroke", "power stroke", "duramax", "6.7 cummins",
    "5.9 cummins", "6.7 powerstroke", "6.0 powerstroke", "lb7", "lly", "l5p",
)
NON_DIESEL_TERMS = (
    "motorcycle", "bike", "mustang", "camaro", "corvette", "infiniti", "subaru",
    "civic", "golf gti", "wrx", "audi", "bmw", "motorbike",
)


@dataclass(frozen=True, slots=True)
class EvidenceQuality:
    """One auditable evidence decision; scores are exactly recomputable."""

    evidence_role: str
    claim_status: str
    quality_score: int
    quality_band: str
    eligible: bool
    hard_exclusion: bool
    components: Mapping[str, int]
    penalties: Mapping[str, int]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GatedEvidence:
    """One original record paired with its evidence-quality result."""

    record: Mapping[str, Any]
    quality: EvidenceQuality


@dataclass(frozen=True, slots=True)
class EvidenceGateResult:
    """Deterministic separation of usable and excluded evidence."""

    qualified: tuple[GatedEvidence, ...]
    excluded: tuple[GatedEvidence, ...]
    distribution: Mapping[str, int]


def classify_diesel_evidence(record: Mapping[str, Any], *, seen_texts: set[str] | None = None) -> EvidenceQuality:
    """Classify one public Reddit record without using an LLM or external service."""
    text = _compose_text(record)
    normalized = _normalize(text)
    hard_reason = _hard_exclusion(record, text, normalized, seen_texts)
    zero_components = {key: 0 for key in _COMPONENT_KEYS}
    zero_penalties = {key: 0 for key in _PENALTY_KEYS}
    zero_penalties["total"] = 0
    if hard_reason:
        return EvidenceQuality(
            evidence_role="noise", claim_status="unknown", quality_score=0,
            quality_band="noise", eligible=False, hard_exclusion=True,
            components=zero_components, penalties=zero_penalties, reason_codes=(hard_reason,),
        )

    lower = text.casefold()
    first_person = bool(re.search(r"\b(i|my|we|our)\b", lower))
    practitioner = bool(re.search(r"\b(mechanic|technician|diesel tech|shop)\b", lower))
    product_hits = _matches(lower, DIESEL_PRODUCTS)
    platform_hits = _matches(lower, DIESEL_PLATFORMS)
    context = bool(re.search(r"\b(tow|towing|haul|hauling|daily driv|work truck|off[ -]?road|winter|cold)\w*\b", lower))
    vehicle = bool(re.search(r"\b(19|20)\d{2}\b|\b(ram|super duty|f[ -]?250|f[ -]?350|silverado|sierra)\b", lower))
    outcome = bool(re.search(r"\b(fail|failed|leak|leaked|crack|cracked|seep|fixed|fix|broke|broken|overheat|fit|didn.t fit)\w*\b", lower))
    purchase = bool(re.search(r"\b(buy|bought|purchase|price|cost|under \$|order|return|returned|replace|replaced)\w*\b", lower))
    diagnostic = bool(re.search(r"\b(code|dtc|diagnos|scan|clamp|sensor|pressure|temperature|torque|install)\w*\b", lower))
    demand = bool(re.search(r"\b(need|looking for|what should i|get me|recommend)\b", lower))

    components = {
        "first_person_or_practitioner": 20 if first_person else 15 if practitioner and diagnostic else 0,
        "product_specificity": 15 if product_hits else 0,
        "context": 15 if context or vehicle or platform_hits else 0,
        "observable_outcome": 20 if outcome else 0,
        "purchase_signal": 10 if purchase else 0,
        "diagnostic_detail": 10 if diagnostic else 0,
        "corroboration": 0,
        "engagement": min(5, int(math.log1p(max(0, _as_int(record.get("score")))))),
    }
    penalties = {key: 0 for key in _PENALTY_KEYS}
    words = normalized.split()
    if len(words) < 8:
        penalties["low_information_density"] = 5
    if re.search(r"\b(coupon|promo code|discount code|affiliate|buy now|free shipping)\b", lower):
        penalties["advertising_language"] = 10
    if text.lstrip().startswith(('"', "'")) and not first_person:
        penalties["quotation_without_personal_context"] = 5
    if seen_texts is not None and normalized in seen_texts:
        penalties["suspected_duplication"] = 5
    penalties["total"] = sum(penalties.values())
    score = max(0, min(100, sum(components.values()) - penalties["total"]))

    if first_person and (outcome or purchase) and (product_hits or platform_hits):
        role = "direct_experience"
    elif practitioner and diagnostic and (product_hits or platform_hits):
        role = "qualified_practitioner"
    elif demand and (context or vehicle or product_hits or platform_hits):
        role = "contextual_demand"
    elif product_hits or platform_hits:
        role = "market_observation"
    else:
        role = "weak"
    status = "fact" if role in {"direct_experience", "qualified_practitioner"} else "inference" if role in {"contextual_demand", "market_observation"} else "unknown"
    reasons = [role]
    if first_person:
        reasons.append("first_person_experience")
    if product_hits:
        reasons.append("diesel_product_term")
    if platform_hits:
        reasons.append("diesel_platform_term")
    if penalties["low_information_density"]:
        reasons.append("low_information_density")
    if seen_texts is not None and normalized:
        seen_texts.add(normalized)
    eligible = role in {"direct_experience", "qualified_practitioner", "market_observation"} and score >= 50
    return EvidenceQuality(role, status, score, _quality_band(score), eligible, False, components, penalties, tuple(reasons))


def apply_diesel_evidence_gate(records: Sequence[Mapping[str, Any]]) -> EvidenceGateResult:
    """Classify supplied records once and retain both qualified and rejected decisions."""
    seen: set[str] = set()
    qualified: list[GatedEvidence] = []
    excluded: list[GatedEvidence] = []
    distribution = {role: 0 for role in EVIDENCE_ROLES}
    for record in records:
        quality = classify_diesel_evidence(record, seen_texts=seen)
        distribution[quality.evidence_role] += 1
        item = GatedEvidence(record, quality)
        (qualified if quality.eligible else excluded).append(item)
    return EvidenceGateResult(tuple(qualified), tuple(excluded), distribution)


def _hard_exclusion(record: Mapping[str, Any], text: str, normalized: str, seen_texts: set[str] | None) -> str | None:
    author = str(record.get("author") or "").casefold()
    subreddit = str(record.get("subreddit") or "").casefold()
    lower = text.casefold()
    if author == "automoderator" or re.search(r"(?:^|[_-])bot(?:$|[_-])", author):
        return "bot_author"
    if re.fullmatch(r"\s*\[(?:deleted|removed)\]\s*", text, re.I):
        return "deleted_or_removed"
    if re.fullmatch(r"https?://\S+", text.strip(), re.I):
        return "url_only"
    if re.search(r"\b(coupon|promo code|discount code|affiliate|use code|buy now|free shipping)\b", lower):
        return "affiliate_or_coupon"
    if re.fullmatch(r"\s*(?:same|this|lol|lmao|nice|agreed|following|bump)\s*[.!?]*\s*", text, re.I):
        return "generic_banter"
    if _matches(lower, NON_DIESEL_TERMS) or subreddit in {"motorcycles", "cars", "mustang", "subaru"}:
        return "non_diesel_or_non_pickup"
    if seen_texts is not None and normalized and normalized in seen_texts:
        return "duplicate_or_near_duplicate"
    return None


def _compose_text(record: Mapping[str, Any]) -> str:
    return "\n".join(str(record.get(key) or "").strip() for key in ("title", "body", "body_original") if str(record.get(key) or "").strip())


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", re.sub(r"https?://\S+", " ", text.casefold()))).strip()


def _matches(text: str, terms: Sequence[str]) -> tuple[str, ...]:
    return tuple(term for term in terms if re.search(rf"\b{re.escape(term)}\b", text, re.I))


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _quality_band(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    if score >= 30:
        return "weak"
    return "noise"
