"""Evidence-first, local VOC synthesis for the diesel pickup radar.

The collector and the optional model clients intentionally stay outside this
module.  This layer turns one ``PostSignal`` into small, auditable claims and
then aggregates claims within one topic.  It never invents a claim when the
post or a comment does not contain a matching signal.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class VOCClaim:
    """One concise claim with its own source and recurrence metrics."""

    field: str
    text: str
    status: str
    evidence_ids: tuple[str, ...]
    post_ids: tuple[str, ...]
    author_ids: tuple[str, ...]
    frequency: int
    severity: str = "unknown"
    consequence: str = "unknown"
    source_text: str = ""

    @property
    def post_count(self) -> int:
        return len(self.post_ids)

    @property
    def author_count(self) -> int:
        return len(self.author_ids)


@dataclass(frozen=True, slots=True)
class PostVOC:
    """Claims extracted from one post and its comments."""

    platform: tuple[str, ...] = ()
    vehicle: tuple[str, ...] = ()
    scenario: tuple[str, ...] = ()
    user_type: tuple[str, ...] = ()
    claims: Mapping[str, tuple[VOCClaim, ...]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.claims is None:
            object.__setattr__(self, "claims", {})

    @property
    def pains(self) -> tuple[VOCClaim, ...]:
        return tuple(self.claims.get("pain", ()))

    @property
    def needs(self) -> tuple[VOCClaim, ...]:
        return tuple(self.claims.get("need", ()))

    @property
    def solutions(self) -> tuple[VOCClaim, ...]:
        return tuple(self.claims.get("current_solution", ()))

    @property
    def gaps(self) -> tuple[VOCClaim, ...]:
        return tuple(self.claims.get("solution_gap", ()))


@dataclass(frozen=True, slots=True)
class TopicVOC:
    """Community-topic synthesis without a model-generated template."""

    topic_key: str
    claims: Mapping[str, tuple[VOCClaim, ...]]
    scenario: tuple[str, ...] = ()
    user_task: str = "unknown"
    opportunity_hypotheses: tuple[VOCClaim, ...] = ()
    opportunity_status: str = "no_product"


_FIELD_ALIASES = {
    "pain_points": "pain",
    "needs": "need",
    "current_solutions": "current_solution",
    "gaps": "solution_gap",
    "consequences": "consequence",
}
_TEMPLATE_VALUES = {
    "更可靠的适配与安装信息",
    "现有方案可能需要额外返工或适配确认",
    "更可靠的适配与安装信息",
    # Category tags emitted by the legacy rule extractor are useful for
    # matching, but are not user statements and must not become report prose.
    "leak/seep",
    "failure",
    "fitment",
    "installation complexity",
    "regeneration/dpf",
    "clogging",
    "oem",
    "aftermarket",
    "replace",
    "replacement",
    "installed",
    "installing",
    "bought",
    "ordered",
    "tried",
    "used",
    "running",
    "tune",
    "tuner",
    "clamp",
    "kit",
}
_SENTENCE_PATTERNS = {
    "pain": re.compile(
        r"\b(?:leak|leaking|seep|fail(?:ed|ure)?|broke?n?(?!\s+in)|crack(?:ed)?|"
        r"problem|issue|fit(?:ment)?|clearance|overheat|overheating|rust|"
        r"expensive|returned|doesn['’]?t fit|didn['’]?t fit|worried|concerned)\b",
        re.I,
    ),
    "need": re.compile(
        r"\b(?:i|we|my|our)\b.{0,100}\b(?:need|looking for|recommend|should i|"
        r"want to|how do i|which|help me|trying to find|advice)\b|"
        r"\b(?:need|looking for|recommend|should i|want to|how do i|which)\b.{0,100}\b(?:fit|kit|part|tuner|truck|help)\b",
        re.I,
    ),
    "current_solution": re.compile(
        r"\b(?:i|we|my|our)\b.{0,100}\b(?:installed|installing|replaced|replace|"
        r"bought|ordered|tried|used|running|oem|aftermarket|kit|tuner|tune|"
        r"shop|dealer|weld|clamp)\b",
        re.I,
    ),
    "solution_gap": re.compile(
        r"\b(?:i|we|my|our)\b.{0,100}\b(?:doesn['’]?t fit|didn['’]?t fit|"
        r"no instructions?|missing|returned|failed again|poor quality|had to modify|"
        r"hard to|unclear|not supported|not compatible|wrong part|extra work|redo)\b|"
        r"\b(?:had to modify|no instructions?|missing|returned|failed again|"
        r"not compatible|wrong part|extra work|redo)\b",
        re.I,
    ),
    "consequence": re.compile(
        r"\b(?:stranded|downtime|tow truck|missed work|damage|unsafe|fire|"
        r"cost me|lost money|ruined|breakdown|break down)\b",
        re.I,
    ),
}
_SUMMARY_TERMS = (
    (re.compile(r"leak|seep", re.I), "泄漏或渗漏"),
    (re.compile(r"fit|clearance|compatib|modify|wrong part", re.I), "安装适配或间隙不匹配"),
    (re.compile(r"fail|broke?n?|broken|crack|overheat|breakdown", re.I), "故障、损坏或失效"),
    (re.compile(r"problem|issue|concern|worried", re.I), "具体故障或问题"),
    (re.compile(r"install|instruction|redo|extra work", re.I), "安装步骤或返工复杂"),
    (re.compile(r"price|cost|expensive|money", re.I), "价格或维修成本"),
    (re.compile(r"rust", re.I), "锈蚀和耐久性"),
    (re.compile(r"egt|exhaust gas temperature|hot", re.I), "排温或热管理"),
)


def extract_post_voc(signal: Any) -> PostVOC:
    """Extract grounded claims from a ``PostSignal``.

    Existing model/rule fields are used only when they contain citations.  A
    short sentence fallback is used for fields absent from those analyses; its
    source is still the exact post or comment sentence.
    """

    sources = _sources(signal)
    claims: dict[str, list[VOCClaim]] = defaultdict(list)
    analysis = getattr(signal, "analysis", None)
    for source_id, source_text in sources.items():
        for raw_field, field_name in _FIELD_ALIASES.items():
            values = getattr(analysis, raw_field, ()) if analysis is not None else ()
            for field in _iter_fields(values):
                value = str(getattr(field, "value", "") or "").strip()
                evidence_ids = tuple(
                    str(item) for item in getattr(field, "evidence_ids", ()) or ()
                    if str(item) in sources
                )
                status = str(getattr(field, "status", "unknown") or "unknown")
                if not value or value.casefold() == "unknown" or value in _TEMPLATE_VALUES:
                    continue
                if status == "unknown" or source_id not in evidence_ids:
                    continue
                claims[field_name].append(_claim_from_value(
                    signal, field_name, value, evidence_ids, source_text, status,
                ))

    # Rules/API outputs can omit a field even though the raw thread contains
    # a concrete sentence.  Extract only the matching sentences; never create
    # generic needs, gaps or product claims without such a sentence.
    for source_id, source_text in sources.items():
        for field_name, pattern in _SENTENCE_PATTERNS.items():
            if any(claim.evidence_ids == (source_id,) and claim.source_text == source_text
                   for claim in claims[field_name]):
                continue
            for sentence in _sentences(source_text):
                if not pattern.search(sentence):
                    continue
                # A negated statement such as "no leak" or "doesn't have
                # rust" is not a pain signal.  Keep concrete third-person
                # diagnostic comments, but mark them as inference below.
                if field_name == "pain" and re.search(
                    r"\b(?:no|not|never|without)\s+(?:\w+\s+){0,2}(?:leak|rust|problem|issue|failure)\b",
                    sentence,
                    re.I,
                ):
                    continue
                source_is_first_person = bool(re.search(r"\b(?:i|my|we|our)\b", sentence, re.I))
                claim_status = "fact" if source_is_first_person else "inference"
                if field_name == "need" and not source_is_first_person:
                    continue
                claims[field_name].append(_claim_from_value(
                    signal, field_name, sentence, (source_id,), sentence, claim_status,
                ))

    return PostVOC(
        platform=_analysis_values(analysis, "platform"),
        vehicle=_analysis_values(analysis, "vehicle"),
        scenario=_analysis_values(analysis, "scenario"),
        user_type=_analysis_values(analysis, "user_type"),
        claims={key: _dedupe_claims(value) for key, value in claims.items()},
    )


def synthesize_topic_voc(
    signals: Sequence[Any],
    topic_key: str,
    *,
    topic_patterns: Sequence[str] = (),
) -> TopicVOC:
    """Aggregate real post claims and create only repeatable opportunities."""

    posts = tuple(signals)
    post_voc = tuple((signal, extract_post_voc(signal)) for signal in posts)
    grouped: dict[str, list[VOCClaim]] = defaultdict(list)
    for _signal, voc in post_voc:
        for field_name, values in voc.claims.items():
            grouped[field_name].extend(
                claim for claim in values
                if not topic_patterns or any(
                    re.search(pattern, claim.source_text, re.I) for pattern in topic_patterns
                )
            )
    aggregated = {key: _aggregate_claims(values) for key, values in grouped.items()}

    scenario = tuple(dict.fromkeys(
        value for _signal, voc in post_voc for value in voc.scenario if value
    ))[:6]
    needs = aggregated.get("need", ())
    user_task = needs[0].text if needs else "unknown"
    repeated_gap = tuple(
        claim for claim in aggregated.get("solution_gap", ())
        if claim.author_count >= 2 and claim.post_count >= 2
    )
    repeated_pain = tuple(
        claim for claim in aggregated.get("pain", ())
        if claim.author_count >= 2
    )
    opportunities: tuple[VOCClaim, ...] = ()
    if repeated_gap and repeated_pain:
        gap = repeated_gap[0]
        opportunities = (VOCClaim(
            field="opportunity_hypothesis",
            text=f"机会假设：验证“{gap.text}”对应的适配、安装或可靠性改进",
            status="inference",
            evidence_ids=gap.evidence_ids,
            post_ids=gap.post_ids,
            author_ids=gap.author_ids,
            frequency=gap.frequency,
            source_text=gap.source_text,
        ),)
        opportunity_status = "emerging_product"
    else:
        opportunity_status = "no_product"

    return TopicVOC(
        topic_key=topic_key,
        claims=aggregated,
        scenario=scenario,
        user_task=user_task,
        opportunity_hypotheses=opportunities,
        opportunity_status=opportunity_status,
    )


def _sources(signal: Any) -> dict[str, str]:
    post = getattr(signal, "post", None)
    post_text = " ".join(
        str(value or "").strip() for value in (
            getattr(post, "title", ""), getattr(post, "body", ""),
        ) if str(value or "").strip()
    )
    sources: dict[str, str] = {"post": post_text}
    for comment in getattr(signal, "comments", ()) or ():
        comment_id = str(getattr(comment, "comment_id", "") or "")
        body = " ".join(str(getattr(comment, "body", "") or "").split())
        if comment_id and body:
            sources[comment_id] = body
    return sources


def _iter_fields(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,) if value is not None else ()


def _analysis_values(analysis: Any, name: str) -> tuple[str, ...]:
    if analysis is None:
        return ()
    values = []
    for field in _iter_fields(getattr(analysis, name, ())):
        value = str(getattr(field, "value", "") or "").strip()
        if value and value.casefold() != "unknown":
            values.append(value)
    return tuple(dict.fromkeys(values))[:8]


def _claim_from_value(
    signal: Any,
    field_name: str,
    value: str,
    evidence_ids: tuple[str, ...],
    source_text: str,
    status: str,
) -> VOCClaim:
    post = getattr(signal, "post", None)
    post_id = str(getattr(post, "post_id", "") or "")
    author = str(getattr(post, "author", "") or "").strip().casefold()
    return VOCClaim(
        field=field_name,
        text=_summary_text(field_name, value),
        status=status if status in {"fact", "inference", "unknown"} else "unknown",
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        post_ids=(post_id,) if post_id else (),
        author_ids=(author,) if author else (),
        frequency=len(tuple(dict.fromkeys(evidence_ids))),
        severity=_severity(value),
        consequence=_consequence(value),
        source_text=" ".join(source_text.split())[:420],
    )


def _summary_text(field_name: str, value: str) -> str:
    # Prefer a field-specific extraction before generic vocabulary.  A
    # solution sentence may also contain words such as "failed" or "leak";
    # those must not be relabelled as a pain merely because the token appears
    # earlier in the sentence.
    if field_name == "need":
        match = re.search(r"(?:need|looking for|want(?: to)?|recommend|which|how do i)\s+(.{3,70})", value, re.I)
        if match:
            return "用户希望获得：" + " ".join(match.group(1).split())[:70]
    if field_name == "current_solution":
        match = re.search(r"(?:installed|installing|replaced|replace|bought|ordered|tried|used|running)\s+(.{3,70})", value, re.I)
        if match:
            return "用户已尝试：" + " ".join(match.group(1).split())[:70]
    if field_name == "solution_gap":
        match = re.search(r"(?:missing|no instructions?|wrong part|had to modify|doesn['’]?t fit|didn['’]?t fit)\s*(.{0,60})", value, re.I)
        if match:
            suffix = " ".join(match.group(1).split())[:60]
            return "用户指出方案缺口：" + (suffix or "适配或安装支持不足")
    for pattern, label in _SUMMARY_TERMS:
        if pattern.search(value):
            prefix = {
                "pain": "用户报告",
                "need": "用户希望",
                "current_solution": "用户已尝试",
                "solution_gap": "现有方案存在",
                "consequence": "可能后果",
            }.get(field_name, "用户提到")
            return f"{prefix}{label}"
    prefix = {
        "pain": "用户报告具体问题",
        "need": "用户提出具体需求",
        "current_solution": "用户提到现有解决办法",
        "solution_gap": "用户指出方案缺口",
        "consequence": "用户提到后果",
    }.get(field_name, "用户提到")
    # Keep a short, source-derived phrase in the analysis when no local
    # translation rule exists.  This is more useful than a generic placeholder
    # and still leaves the full wording in the collapsible evidence browser.
    excerpt = " ".join(value.split())[:80]
    return f"{prefix}：{excerpt}" if excerpt else prefix


def _severity(value: str) -> str:
    if re.search(r"stranded|fire|unsafe|overheat|breakdown|failed|broken|damage", value, re.I):
        return "high"
    if re.search(r"leak|fit|install|rust|expensive|return|problem|issue", value, re.I):
        return "medium"
    return "unknown"


def _consequence(value: str) -> str:
    match = re.search(r"(?:because|so|which|causing|lead(?:s|ing)? to)\s+(.{10,120})", value, re.I)
    return " ".join(match.group(1).split()) if match else "unknown"


def _sentences(text: str) -> tuple[str, ...]:
    cleaned = " ".join(text.split())
    return tuple(part.strip(" -—") for part in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if len(part.strip()) >= 8)


def _dedupe_claims(claims: Sequence[VOCClaim]) -> tuple[VOCClaim, ...]:
    # Keep a claim per distinct source sentence; repeated identical values from
    # a single post are collapsed before topic-level aggregation.
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    result: list[VOCClaim] = []
    for claim in claims:
        key = (claim.text, claim.evidence_ids, claim.source_text)
        if key in seen or not claim.evidence_ids:
            continue
        seen.add(key)
        result.append(claim)
    return tuple(result)


def _aggregate_claims(claims: Sequence[VOCClaim]) -> tuple[VOCClaim, ...]:
    buckets: dict[tuple[str, str], list[VOCClaim]] = defaultdict(list)
    for claim in claims:
        buckets[(claim.field, claim.text)].append(claim)
    result: list[VOCClaim] = []
    for (field, text), bucket in buckets.items():
        evidence_ids = tuple(dict.fromkeys(
            f"{claim.post_ids[0]}:{evidence_id}"
            for claim in bucket for evidence_id in claim.evidence_ids
            if claim.post_ids
        ))
        post_ids = tuple(dict.fromkeys(claim.post_ids[0] for claim in bucket if claim.post_ids))
        author_ids = tuple(dict.fromkeys(claim.author_ids[0] for claim in bucket if claim.author_ids))
        result.append(VOCClaim(
            field=field,
            text=text,
            status="fact" if all(claim.status == "fact" for claim in bucket) else "inference",
            evidence_ids=evidence_ids,
            post_ids=post_ids,
            author_ids=author_ids,
            frequency=len(evidence_ids),
            severity=max((claim.severity for claim in bucket), key=("unknown", "medium", "high").index, default="unknown"),
            consequence=next((claim.consequence for claim in bucket if claim.consequence != "unknown"), "unknown"),
            source_text=next((claim.source_text for claim in bucket if claim.source_text), ""),
        ))
    return tuple(sorted(result, key=lambda claim: (-claim.post_count, -claim.frequency, claim.text)))
