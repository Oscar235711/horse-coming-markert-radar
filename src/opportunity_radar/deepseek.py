"""Small, injected HTTP adapter for DeepSeek JSON post extraction."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any
import urllib.error
import urllib.request

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
    user_type: AnalysisField = field(default_factory=AnalysisField)
    pain_severity: tuple[AnalysisField, ...] = ()
    consequences: tuple[AnalysisField, ...] = ()
    supporting_views: tuple[AnalysisField, ...] = ()
    opposing_views: tuple[AnalysisField, ...] = ()


class DeepSeekError(RuntimeError):
    """An operator-facing error that is intentionally safe to persist or display."""


HttpTransport = Callable[[str, str, dict[str, str], dict[str, Any]], HttpResponse]


def _is_windows() -> bool:
    return os.name == "nt"


def _powershell_executable() -> str | None:
    """Return a locally available Schannel-backed PowerShell executable."""
    if not _is_windows():
        return None
    return shutil.which("pwsh") or shutil.which("powershell")


def _curl_executable() -> str | None:
    """Return the Windows Schannel-backed curl shipped with modern Windows."""
    if not _is_windows():
        return None
    return shutil.which("curl.exe") or shutil.which("curl")


def _curl_config_value(value: str) -> str:
    """Escape a value for curl's double-quoted config-file syntax."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


def _curl_http_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
) -> HttpResponse | None:
    """Send the request through curl without putting the bearer token in argv.

    The request JSON is held in a short-lived temp file while the curl config
    (including the Authorization header) is piped on stdin.  This avoids both
    a Windows OpenSSL handshake problem and credentials in process listings.
    """
    executable = _curl_executable()
    if not executable:
        return None
    marker = "__OPPORTUNITY_RADAR_STATUS__"
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="opportunity-radar-", suffix=".json", delete=False) as handle:
            handle.write(body)
            temp_path = handle.name
        config = "\n".join((
            f'url = "{_curl_config_value(url)}"',
            f'request = "{_curl_config_value(method)}"',
            f'header = "Authorization: {_curl_config_value(headers.get("Authorization", ""))}"',
            f'header = "Content-Type: {_curl_config_value(headers.get("Content-Type", "application/json"))}"',
            f'data-binary = "@{_curl_config_value(temp_path)}"',
            f'write-out = "\\n{marker}:%{{http_code}}"',
            "",
        )).encode("utf-8")
        completed = subprocess.run(
            (executable, "--silent", "--show-error", "--config", "-"),
            input=config,
            capture_output=True,
            timeout=125,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    if completed.returncode != 0:
        return None
    output = completed.stdout.decode("utf-8", errors="replace")
    body_text, separator, status_text = output.rpartition(f"\n{marker}:")
    if not separator:
        return None
    try:
        status = int(status_text.strip())
    except ValueError:
        return None
    return HttpResponse(status, body_text)


def _powershell_http_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
) -> HttpResponse | None:
    """Retry a Windows TLS request through .NET/Schannel.

    Some corporate gateways accept Windows Schannel but fail during Python's
    OpenSSL handshake.  The request body is piped over stdin and the bearer
    token is supplied only through the child environment; neither is put in
    the process command line or persisted to a project file.
    """
    executable = _powershell_executable()
    if not executable:
        return None
    script = r"""
$ErrorActionPreference = 'Stop'
$requestBody = [Console]::In.ReadToEnd()
$requestHeaders = @{
  Authorization = $env:OPPORTUNITY_RADAR_HTTP_AUTH
  'Content-Type' = $env:OPPORTUNITY_RADAR_HTTP_CONTENT_TYPE
}
try {
  $response = Invoke-WebRequest -UseBasicParsing -Uri $env:OPPORTUNITY_RADAR_HTTP_URL -Method $env:OPPORTUNITY_RADAR_HTTP_METHOD -Headers $requestHeaders -Body $requestBody -TimeoutSec 120 -ErrorAction Stop
  $result = [ordered]@{ status = [int]$response.StatusCode; body = [string]$response.Content }
} catch {
  $status = 0
  $content = [string]$_.Exception.Message
  if ($_.Exception.Response) {
    try {
      $status = [int]$_.Exception.Response.StatusCode
      $stream = $_.Exception.Response.GetResponseStream()
      if ($stream) {
        $reader = [IO.StreamReader]::new($stream)
        $content = $reader.ReadToEnd()
        $reader.Dispose()
      }
    } catch { }
  }
  $result = [ordered]@{ status = $status; body = $content }
}
$result | ConvertTo-Json -Compress
""".strip()
    child_environment = dict(os.environ)
    child_environment.update({
        "OPPORTUNITY_RADAR_HTTP_URL": url,
        "OPPORTUNITY_RADAR_HTTP_METHOD": method,
        "OPPORTUNITY_RADAR_HTTP_AUTH": headers.get("Authorization", ""),
        "OPPORTUNITY_RADAR_HTTP_CONTENT_TYPE": headers.get("Content-Type", "application/json"),
    })
    try:
        completed = subprocess.run(
            (executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script),
            input=body,
            capture_output=True,
            timeout=125,
            check=False,
            env=child_environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        envelope = json.loads(completed.stdout.decode("utf-8", errors="replace"))
        return HttpResponse(int(envelope["status"]), str(envelope.get("body", "")))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def openai_http_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> HttpResponse:
    """POST JSON using urllib, with a Windows Schannel fallback for TLS errors."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return HttpResponse(response.status, response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return HttpResponse(error.code, error.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # curl uses Windows Schannel and is the most reliable path through
        # the company's Higress gateway; PowerShell remains a second fallback
        # for hosts where curl is unavailable.
        fallback = _curl_http_transport(method, url, headers, body)
        if fallback is None:
            fallback = _powershell_http_transport(method, url, headers, body)
        if fallback is not None:
            return fallback
        raise error


class DeepSeekClient:
    """Use DeepSeek's OpenAI-compatible chat endpoint through an injected transport."""

    def __init__(
        self,
        *,
        transport: HttpTransport,
        environment: Mapping[str, str] | None = None,
        base_url: str | None = None,
        sleeper: Callable[[float], None] | None = None,
        chunk_chars: int | None = None,
    ) -> None:
        self._transport = transport
        self._environment = environment if environment is not None else os.environ
        configured_base_url = base_url or self._environment.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
        self._base_url = configured_base_url.rstrip("/")
        self._sleeper = sleeper or (lambda _: None)
        configured_chunk_chars = chunk_chars if chunk_chars is not None else self._environment.get("DEEPSEEK_CHUNK_CHARS", "24000")
        try:
            self._chunk_chars = max(512, int(configured_chunk_chars))
        except (TypeError, ValueError):
            self._chunk_chars = 24000
        try:
            self._max_tokens = max(1024, int(self._environment.get("DEEPSEEK_MAX_TOKENS", "8192")))
        except (TypeError, ValueError):
            self._max_tokens = 8192

    def chat_json(self, messages: Sequence[Mapping[str, str]], *, model: str = FLASH_MODEL) -> Mapping[str, Any]:
        """Call ``/chat/completions`` and retry only malformed or transient responses."""
        key = self._environment.get("DEEPSEEK_API_KEY")
        if not key:
            raise DeepSeekError("DeepSeek 未配置：请设置 DEEPSEEK_API_KEY。")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "response_format": {"type": "json_object"},
            # The Higress deployment exposes DeepSeek's reasoning stream as
            # ``reasoning_content``.  For this contract we need the final
            # structured JSON in ``content``; otherwise the model can consume
            # the whole token budget reasoning and leave ``content`` empty.
            "thinking": {"type": "disabled"},
            "stream": False,
            "max_tokens": self._max_tokens,
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

    def extract_post(self, thread: ThreadDocument, *, model: str | None = None) -> PostAnalysis:
        """Extract all post/comment evidence, chunking only the model request.

        Complete collection deliberately keeps every saved comment.  A large
        thread is split into request-sized comment batches, each batch is
        extracted with the same evidence IDs, and the typed results are merged
        locally.  The raw evidence is never truncated or discarded.
        """
        comments = tuple(thread.comments)
        chunks = _comment_chunks(comments, self._chunk_chars)
        analyses = tuple(
            self._extract_post_chunk(thread, chunk, model=model)
            for chunk in chunks
        )
        return _merge_post_analyses(analyses)

    def _extract_post_chunk(
        self,
        thread: ThreadDocument,
        comments: Sequence[Any],
        *,
        model: str | None = None,
    ) -> PostAnalysis:
        """Run one bounded Flash request without changing the source record."""
        evidence = {"post": thread.post.url}
        evidence.update({comment.comment_id: comment.url for comment in comments})
        prompt = {
            "post": {"evidence_id": "post", "url": thread.post.url, "title": thread.post.title, "body": thread.post.body},
            "comments": [{"evidence_id": comment.comment_id, "url": comment.url, "body": comment.body} for comment in comments],
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
        ), model=model or self._environment.get("DEEPSEEK_FLASH_MODEL", FLASH_MODEL))
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

    def plan_research(self, question: str, *, seed_terms: Sequence[str] = (), model: str | None = None) -> dict[str, list[str]]:
        """Expand a user's research question into clean, auditable search concepts."""
        prompt = {
            "question": " ".join(str(question or "").split()),
            "seed_terms": [str(term).strip() for term in seed_terms if str(term).strip()],
            "instruction": (
                "Return JSON only with query_terms and exclusions. query_terms must be complete "
                "diesel-pickup search concepts: platforms, products, symptoms, scenarios, fitment, "
                "or buying intent. Do not return pronouns, filler fragments, sentence snippets, or "
                "generic phrases such as just got or because im. Keep terms in English."
            ),
        }
        document = self.chat_json((
            {"role": "system", "content": "You are a search-query planner for North American diesel pickup VOC research."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ), model=model or self._environment.get("DEEPSEEK_FLASH_MODEL", FLASH_MODEL))
        from .keywords import clean_keyword_term

        platform_terms = {"cummins", "duramax", "powerstroke", "ford diesel", "diesel truck"}
        terms: list[str] = []
        for raw in document.get("query_terms", []) if isinstance(document.get("query_terms"), list) else []:
            normalized = " ".join(str(raw).casefold().replace("-", " ").split())
            if normalized in platform_terms or clean_keyword_term(normalized) is not None:
                if normalized not in terms:
                    terms.append(normalized)
        exclusions: list[str] = []
        for raw in document.get("exclusions", []) if isinstance(document.get("exclusions"), list) else []:
            normalized = " ".join(str(raw).casefold().split())
            if normalized and normalized not in exclusions:
                exclusions.append(normalized)
        return {"query_terms": terms, "exclusions": exclusions}


def _comment_chunks(comments: Sequence[Any], limit: int) -> tuple[tuple[Any, ...], ...]:
    """Partition comments by serialized-size estimate without dropping rows."""
    if not comments:
        return ((),)
    chunks: list[tuple[Any, ...]] = []
    current: list[Any] = []
    current_size = 0
    for comment in comments:
        # Account for JSON keys and URL overhead in addition to the body. A
        # single oversized comment stays intact; it is still better evidence
        # than silently clipping the user's source data.
        item_size = len(str(getattr(comment, "body", "") or "")) + len(str(getattr(comment, "url", "") or "")) + 256
        if current and current_size + item_size > limit:
            chunks.append(tuple(current))
            current = []
            current_size = 0
        current.append(comment)
        current_size += item_size
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _merge_post_analyses(analyses: Sequence[PostAnalysis]) -> PostAnalysis:
    """Merge chunk results while preserving all distinct evidence citations."""
    if not analyses:
        return PostAnalysis(topics=(), claims=())
    topic_map: dict[str, TopicCandidate] = {}
    claim_map: dict[str, EvidenceClaim] = {}
    for analysis in analyses:
        for topic in analysis.topics:
            key = _merge_key(topic.label)
            prior = topic_map.get(key)
            topic_map[key] = topic if prior is None else TopicCandidate(
                label=prior.label,
                evidence_ids=_merge_ids(prior.evidence_ids, topic.evidence_ids),
            )
        for claim in analysis.claims:
            key = _merge_key(claim.claim)
            prior = claim_map.get(key)
            if prior is None:
                claim_map[key] = claim
                continue
            ids = _merge_ids(prior.evidence_ids, claim.evidence_ids)
            urls_by_id = {
                **dict(zip(prior.evidence_ids, prior.urls)),
                **dict(zip(claim.evidence_ids, claim.urls)),
            }
            urls = tuple(urls_by_id[identifier] for identifier in ids if identifier in urls_by_id)
            claim_map[key] = EvidenceClaim(
                claim=prior.claim,
                evidence_ids=ids,
                urls=urls,
                status="supported" if ids and len(urls) == len(ids) else "unknown",
            )

    scalar_names = ("platform", "vehicle", "year", "scenario", "goal", "sentiment", "user_type")
    list_names = (
        "pain_points", "needs", "current_solutions", "gaps", "opportunity_hypotheses", "products",
        "brands", "competitors", "purchase_intent", "keyword_candidates", "topic_candidates",
        "pain_severity", "consequences", "supporting_views", "opposing_views",
    )
    merged_values: dict[str, Any] = {
        name: _merge_field_values(tuple(getattr(analysis, name) for analysis in analyses))
        for name in scalar_names
    }
    merged_values.update({
        name: _merge_field_lists(tuple(getattr(analysis, name) for analysis in analyses))
        for name in list_names
    })
    return replace(
        analyses[0],
        topics=tuple(topic_map.values()),
        claims=tuple(claim_map.values()),
        **merged_values,
    )


def _merge_key(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _merge_ids(first: Sequence[str], second: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _merge_status(first: str, *others: str) -> str:
    rank = {"unknown": 0, "inference": 1, "fact": 2}
    statuses = (first, *others)
    return max(statuses, key=lambda status: rank.get(status, 0))


def _merge_field_values(fields: Sequence[AnalysisField]) -> AnalysisField:
    valid = tuple(field for field in fields if field.value and field.value != "unknown")
    if not valid:
        return AnalysisField()
    chosen = valid[0]
    evidence_ids = tuple(dict.fromkeys(identifier for field in valid for identifier in field.evidence_ids))
    status = _merge_status(chosen.status, *(field.status for field in valid[1:])) if len(valid) > 1 else chosen.status
    return AnalysisField(chosen.value, evidence_ids, status)


def _merge_field_lists(groups: Sequence[Sequence[AnalysisField]]) -> tuple[AnalysisField, ...]:
    merged: dict[str, AnalysisField] = {}
    for fields in groups:
        for field in fields:
            if not field.value or field.value == "unknown":
                continue
            key = _merge_key(field.value)
            prior = merged.get(key)
            if prior is None:
                merged[key] = field
            else:
                merged[key] = AnalysisField(
                    value=prior.value,
                    evidence_ids=_merge_ids(prior.evidence_ids, field.evidence_ids),
                    status=_merge_status(prior.status, field.status),
                )
    return tuple(merged.values())


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
    # Some Higress model deployments wrap the requested fields in a ``diesel``
    # object and emit topic/claim labels as plain strings.  Normalize that
    # response shape at the boundary so the rest of the pipeline keeps one
    # evidence-aware contract.
    normalized: dict[str, Any] = dict(document)
    nested = document.get("diesel")
    if isinstance(nested, Mapping):
        for name, value in nested.items():
            key = str(name)
            # Nested gateway responses occasionally encode a list-valued
            # field as one object.  Accept that documented wrapper shape, but
            # keep a malformed top-level scalar field rejected below.
            if key in {
                "pain_points", "needs", "current_solutions", "gaps", "opportunity_hypotheses",
                "products", "brands", "competitors", "purchase_intent", "keyword_candidates",
                "topic_candidates", "pain_severity", "consequences", "supporting_views", "opposing_views",
            } and isinstance(value, Mapping):
                value = [value]
            normalized.setdefault(key, value)

    topics: list[TopicCandidate] = []
    topic_fallback_ids = _field_evidence_ids(normalized.get("topic_candidates"), evidence)
    raw_topics = normalized.get("topics")
    for item in raw_topics if isinstance(raw_topics, list) else []:
        if isinstance(item, Mapping):
            label = item.get("label")
            ids = _known_ids(item.get("evidence_ids"), evidence)
        elif isinstance(item, str):
            label = item
            # The deployed model sometimes supplies labels without repeating
            # citations.  Reuse citations from its topic_candidates field,
            # never inventing an evidence ID.
            ids = topic_fallback_ids
        else:
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        if ids:
            topics.append(TopicCandidate(label.strip(), ids))
        if len(topics) == 3:
            break
    claims: list[EvidenceClaim] = []
    raw_claims = normalized.get("claims")
    for item in raw_claims if isinstance(raw_claims, list) else []:
        if isinstance(item, str):
            if item.strip():
                claims.append(EvidenceClaim(item.strip(), (), (), "unknown"))
            continue
        if not isinstance(item, Mapping) or not isinstance(item.get("claim"), str) or not item["claim"].strip():
            continue
        ids = _known_ids(item.get("evidence_ids"), evidence)
        supplied_urls = item.get("urls")
        urls = tuple(url for url in supplied_urls if isinstance(url, str)) if isinstance(supplied_urls, list) else ()
        valid = bool(ids) and urls == tuple(evidence[identifier] for identifier in ids)
        claims.append(EvidenceClaim(item["claim"].strip(), ids if valid else (), urls if valid else (), "supported" if valid else "unknown"))
    scalar_names = ("platform", "vehicle", "year", "scenario", "goal", "sentiment", "user_type")
    list_names = (
        "pain_points", "needs", "current_solutions", "gaps", "opportunity_hypotheses", "products",
        "brands", "competitors", "purchase_intent", "keyword_candidates", "topic_candidates",
        "pain_severity", "consequences", "supporting_views", "opposing_views",
    )
    scalar_fields = {name: _analysis_field(normalized.get(name), evidence) for name in scalar_names}
    list_fields = {name: _analysis_fields(normalized.get(name), evidence) for name in list_names}
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
        user_type=scalar_fields["user_type"], pain_severity=list_fields["pain_severity"],
        consequences=list_fields["consequences"], supporting_views=list_fields["supporting_views"],
        opposing_views=list_fields["opposing_views"],
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
    if isinstance(value, Mapping):
        # List-valued fields must remain arrays on the wire.  Treating a
        # scalar mapping as one list item makes malformed gateway output look
        # like a valid VOC assertion.
        return ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        field for item in value
        if (field := _analysis_field(item, evidence)).value != "unknown"
    )


def _field_evidence_ids(value: Any, evidence: Mapping[str, str]) -> tuple[str, ...]:
    """Return citations from a scalar or list analysis field."""
    if isinstance(value, Mapping):
        return _known_ids(value.get("evidence_ids"), evidence)
    if isinstance(value, (list, tuple)):
        for item in value:
            ids = _field_evidence_ids(item, evidence)
            if ids:
                return ids
    return ()


def _known_ids(value: Any, evidence: Mapping[str, str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(identifier for identifier in value if isinstance(identifier, str) and identifier in evidence)
