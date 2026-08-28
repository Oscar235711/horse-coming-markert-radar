"""Small, injected HTTP adapter for DeepSeek JSON post extraction."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import json
import os
from typing import Any

from .collector import ThreadDocument

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal HTTP response passed over the injected transport boundary."""

    status_code: int
    body: str


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    label: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    claim: str
    evidence_ids: tuple[str, ...]
    urls: tuple[str, ...]
    status: str = "supported"


@dataclass(frozen=True, slots=True)
class AnalysisField:
    """One Flash-extracted field with provenance and epistemic status."""

    value: str = "unknown"
    evidence_ids: tuple[str, ...] = ()
    status: str = "unknown"


@dataclass(frozen=True, slots=True)
class PostAnalysis:
    """Backward-compatible compact topics/claims plus the diesel V2 contract."""

    topics: tuple[TopicCandidate, ...]
    claims: tuple[EvidenceClaim, ...]
    platform: AnalysisField = field(default_factory=AnalysisField)
    vehicle: AnalysisField = field(default_factory=AnalysisField)
    year: AnalysisField = field(default_factory=AnalysisField)
    scenario: AnalysisField = field(default_factory=AnalysisField)
    goal: AnalysisField = field(default_factory=AnalysisField)
    pain_points: tuple[AnalysisField, ...] = ()
    needs: tuple[AnalysisField, ...] = ()
    current_solutions: tuple[AnalysisField, ...] = ()
    gaps: tuple[AnalysisField, ...] = ()
    opportunity_hypotheses: tuple[AnalysisField, ...] = ()
    products: tuple[AnalysisField, ...] = ()
    brands: tuple[AnalysisField, ...] = ()
    competitors: tuple[AnalysisField, ...] = ()
    purchase_intent: tuple[AnalysisField, ...] = ()
    sentiment: AnalysisField = field(default_factory=AnalysisField)
    keyword_candidates: tuple[AnalysisField, ...] = ()
    topic_candidates: tuple[AnalysisField, ...] = ()


class DeepSeekError(RuntimeError):
    """An operator-facing error that is intentionally safe to persist or display."""


HttpTransport = Callable[[str, str, dict[str, str], dict[str, Any]], HttpResponse]


class DeepSeekClient:
    """Use DeepSeek's OpenAI-compatible chat endpoint through an injected transport."""

    def __init__(
        self,
        *,
        transport: HttpTransport,
        environment: Mapping[str, str] | None = None,
        base_url: str | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport
        self._environment = environment if environment is not None else os.environ
        configured_base_url = base_url or self._environment.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
        self._base_url = configured_base_url.rstrip("/")
        self._sleeper = sleeper or (lambda _: None)

    def chat_json(self, messages: Sequence[Mapping[str, str]], *, model: str = FLASH_MODEL) -> Mapping[str, Any]:
        """Call ``/chat/completions`` and retry only malformed or transient responses."""
        key = self._environment.get("DEEPSEEK_API_KEY")
        if not key:
            raise DeepSeekError("DeepSeek 未配置：请设置 DEEPSEEK_API_KEY。")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": 4096,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        last_error: DeepSeekError | None = None
        for attempt in range(3):
            try:
                response = self._transport("POST", f"{self._base_url}/chat/completions", headers, payload)
                status_error = _status_error(response.status_code)
                if status_error is not None:
                    if response.status_code in {401, 404}:
                        raise status_error
                    last_error = status_error
                    if attempt < 2:
                        self._sleeper(float(attempt + 1))
                        continue
                    raise status_error
                decoded = json.loads(response.body)
                content = _content_from_response(decoded)
                result = json.loads(content) if isinstance(content, str) else content
                if not isinstance(result, Mapping):
                    raise ValueError("chat response content is not a JSON object")
                return result
            except DeepSeekError:
                raise
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                last_error = DeepSeekError("DeepSeek 返回暂不可用或无效 JSON，将重试。")
            if attempt < 2:
                self._sleeper(float(attempt + 1))
        raise last_error or DeepSeekError("DeepSeek 请求失败。")

    def extract_post(self, thread: ThreadDocument) -> PostAnalysis:
        """Extract an evidence-cited diesel post contract with Flash."""
        evidence = {"post": thread.post.url}
        evidence.update({comment.comment_id: comment.url for comment in thread.comments})
        prompt = {
            "post": {"evidence_id": "post", "url": thread.post.url, "title": thread.post.title, "body": thread.post.body},
            "comments": [{"evidence_id": comment.comment_id, "url": comment.url, "body": comment.body} for comment in thread.comments],
            "instruction": (
                "Return JSON with topics (max 3), claims, and the diesel fields platform, vehicle, year, "
                "scenario, goal, pain_points, needs, current_solutions, gaps, opportunity_hypotheses, "
                "products, brands, competitors, purchase_intent, sentiment, keyword_candidates, and "
                "topic_candidates. Each diesel field is {value, evidence_ids, status}; status is fact, "
                "inference, or unknown. Cite only supplied evidence_ids and URLs; unknown has no citations."
            ),
        }
        document = self.chat_json((
            {"role": "system", "content": "You extract evidence-grounded Reddit product signals."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ), model=self._environment.get("DEEPSEEK_FLASH_MODEL", FLASH_MODEL))
        analysis = _analysis_from_document(document, evidence)
        if not analysis.topics and analysis.claims:
            # Some gateway deployments return grounded claims but omit the optional
            # topic array. Preserve a conservative topic seed so community-level
            # consolidation can still group the evidence instead of dropping it.
            claim = analysis.claims[0]
            label = " ".join(claim.claim.split())[:120] or "Unclassified product discussion"
            analysis = replace(
                analysis,
                topics=(TopicCandidate(label=label, evidence_ids=claim.evidence_ids),),
            )
        return analysis


def _status_error(status_code: int) -> DeepSeekError | None:
    if 200 <= status_code < 300:
        return None
    if status_code == 401:
        return DeepSeekError("DeepSeek 鉴权失败：请检查 DEEPSEEK_API_KEY。")
    if status_code == 404:
        return DeepSeekError("DeepSeek 接口或模型不存在：请检查 base URL 和模型名。")
    if status_code == 429:
        return DeepSeekError("DeepSeek 请求过于频繁：请稍后重试。")
    return DeepSeekError("DeepSeek 服务暂时不可用，将重试。")


def _content_from_response(document: Any) -> Any:
    if not isinstance(document, Mapping):
        raise ValueError("chat response must be a JSON object")
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ValueError("chat response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, Mapping) or "content" not in message:
        raise ValueError("chat response has no message content")
    return message["content"]


def _analysis_from_document(document: Mapping[str, Any], evidence: Mapping[str, str]) -> PostAnalysis:
    topics: list[TopicCandidate] = []
    for item in document.get("topics", []) if isinstance(document.get("topics"), list) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("label"), str) or not item["label"].strip():
            continue
        ids = _known_ids(item.get("evidence_ids"), evidence)
        if ids:
            topics.append(TopicCandidate(item["label"].strip(), ids))
        if len(topics) == 3:
            break
    claims: list[EvidenceClaim] = []
    for item in document.get("claims", []) if isinstance(document.get("claims"), list) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("claim"), str) or not item["claim"].strip():
            continue
        ids = _known_ids(item.get("evidence_ids"), evidence)
        supplied_urls = item.get("urls")
        urls = tuple(url for url in supplied_urls if isinstance(url, str)) if isinstance(supplied_urls, list) else ()
        valid = bool(ids) and urls == tuple(evidence[identifier] for identifier in ids)
        claims.append(EvidenceClaim(item["claim"].strip(), ids if valid else (), urls if valid else (), "supported" if valid else "unknown"))
    scalar_names = ("platform", "vehicle", "year", "scenario", "goal", "sentiment")
    list_names = (
        "pain_points", "needs", "current_solutions", "gaps", "opportunity_hypotheses", "products",
        "brands", "competitors", "purchase_intent", "keyword_candidates", "topic_candidates",
    )
    scalar_fields = {name: _analysis_field(document.get(name), evidence) for name in scalar_names}
    list_fields = {name: _analysis_fields(document.get(name), evidence) for name in list_names}
    return PostAnalysis(
        tuple(topics), tuple(claims),
        platform=scalar_fields["platform"], vehicle=scalar_fields["vehicle"], year=scalar_fields["year"],
        scenario=scalar_fields["scenario"], goal=scalar_fields["goal"],
        pain_points=list_fields["pain_points"], needs=list_fields["needs"],
        current_solutions=list_fields["current_solutions"], gaps=list_fields["gaps"],
        opportunity_hypotheses=list_fields["opportunity_hypotheses"], products=list_fields["products"],
        brands=list_fields["brands"], competitors=list_fields["competitors"],
        purchase_intent=list_fields["purchase_intent"], sentiment=scalar_fields["sentiment"],
        keyword_candidates=list_fields["keyword_candidates"], topic_candidates=list_fields["topic_candidates"],
    )


def _analysis_field(value: Any, evidence: Mapping[str, str]) -> AnalysisField:
    """Reject unsupported model assertions while preserving explicit uncertainty."""
    if not isinstance(value, Mapping) or not isinstance(value.get("value"), str) or not value["value"].strip():
        return AnalysisField()
    status = value.get("status") if value.get("status") in {"fact", "inference", "unknown"} else "unknown"
    ids = _known_ids(value.get("evidence_ids"), evidence)
    if status == "unknown" or not ids:
        return AnalysisField(value["value"].strip(), (), "unknown")
    return AnalysisField(value["value"].strip(), ids, status)


def _analysis_fields(value: Any, evidence: Mapping[str, str]) -> tuple[AnalysisField, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        field for item in value
        if (field := _analysis_field(item, evidence)).value != "unknown"
    )


def _known_ids(value: Any, evidence: Mapping[str, str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(identifier for identifier in value if isinstance(identifier, str) and identifier in evidence)
