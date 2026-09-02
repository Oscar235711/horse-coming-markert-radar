"""Research-question planning for the user-facing Radar entry point.

The planner is deliberately small and deterministic at the boundary.  A
DeepSeek planner can enrich the returned brief later, but the web task always
has a safe, auditable fallback when the gateway is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class ResearchBrief:
    question: str
    query_terms: tuple[str, ...]
    exclusions: tuple[str, ...]
    source: str = "deterministic_seed"

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "query_terms": list(self.query_terms),
            "exclusions": list(self.exclusions),
            "source": self.source,
        }


_TERM_MAP: tuple[tuple[str, str], ...] = (
    ("拖挂", "towing"),
    ("牵引", "towing"),
    ("高温", "high egt"),
    ("排温", "exhaust gas temperature"),
    ("排气温度", "exhaust gas temperature"),
    ("排气", "exhaust"),
    ("改装", "performance upgrade"),
    ("安装", "installation"),
    ("适配", "fitment"),
    ("故障", "failure"),
    ("漏", "leak"),
    ("价格", "price"),
    ("推荐", "recommendation"),
)

_DIESEL_ALIASES = ("cummins", "duramax", "powerstroke", "ford diesel", "diesel truck")


def build_research_brief(question: str, *, seed_terms: tuple[str, ...] = ()) -> ResearchBrief:
    """Turn a natural-language question into auditable initial search concepts."""
    cleaned = " ".join(str(question or "").split()).strip()
    if not cleaned:
        raise ValueError("研究问题不能为空")
    lowered = cleaned.casefold()
    terms: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.casefold().split()).strip()
        if value and value not in terms:
            terms.append(value)

    for alias in _DIESEL_ALIASES:
        if alias in lowered:
            add(alias)
    for marker, english in _TERM_MAP:
        if marker in cleaned or marker in lowered:
            add(english)
    english_tokens = re.findall(r"[a-z][a-z0-9-]{2,}", lowered)
    for token in english_tokens:
        if token not in {"what", "which", "when", "does", "with", "from", "about", "and", "the"}:
            add(token.replace("-", " "))
    for term in seed_terms:
        add(term)

    # Keep the default scope diesel-specific even when the user writes the
    # question entirely in Chinese.  These are search anchors, not report
    # topics and are not shown as a long checkbox list in the UI.
    if not any(term in terms for term in _DIESEL_ALIASES):
        add("diesel truck")
    if "towing" in terms and "high egt" in terms:
        add("towing high egt")
    if "high egt" in terms and "exhaust" in terms:
        add("exhaust gas temperature")
    if "exhaust gas temperature" in terms:
        add("exhaust gas temperature")

    return ResearchBrief(
        question=cleaned,
        query_terms=tuple(terms),
        exclusions=("gasoline vehicle", "motorcycle", "generic automotive", "spam", "affiliate promotion"),
    )
