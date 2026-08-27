"""Small, injected HTTP adapter for DeepSeek JSON post extraction."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
class PostAnalysis:
    topics: tuple[TopicCandidate, ...]
    claims: tuple[EvidenceClaim, ...]


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
        base_url: str = DEFAULT_BASE_URL,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport
        self._environment = environment if environment is not None else os.environ
        self._base_url = base_url.rstrip("/")
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
        """Extract at most three evidence-cited topic candidates with Flash."""
        evidence = {"post": thread.post.url}
        evidence.update({comment.comment_id: comment.url for comment in thread.comments})
        prompt = {
            "post": {"evidence_id": "post", "url": thread.post.url, "title": thread.post.title, "body": thread.post.body},
            "comments": [{"evidence_id": comment.comment_id, "url": comment.url, "body": comment.body} for comment in thread.comments],
            "instruction": "Return JSON with topics (max 3) and claims. Cite only supplied evidence_ids and URLs.",
        }
        document = self.chat_json((
            {"role": "system", "content": "You extract evidence-grounded Reddit product signals."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ))
        return _analysis_from_document(document, evidence)


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
    return PostAnalysis(tuple(topics), tuple(claims))


def _known_ids(value: Any, evidence: Mapping[str, str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(identifier for identifier in value if isinstance(identifier, str) and identifier in evidence)
