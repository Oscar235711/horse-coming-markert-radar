"""Evidence-grounded Chinese overview for the vendored last30days Skill.

The vendored engine intentionally keeps source titles and snippets verbatim.
This module is the project-owned interpretation boundary: it normalizes all
returned items, asks the configured DeepSeek gateway for Chinese item signals,
then asks it to synthesize a short, evidence-linked overview.  It never turns
an empty cluster list into a fabricated topic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .deepseek import DeepSeekClient, HttpResponse


def _clean(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit] if limit and len(text) > limit else text


def _number(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _item_id(row: Mapping[str, Any], index: int) -> str:
    value = _clean(row.get("evidence_id") or row.get("candidate_id") or row.get("item_id") or row.get("id"))
    if value:
        return value
    raw = _clean(row.get("url") or row.get("title") or row.get("snippet") or row.get("body"), 500)
    return "anon-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12] if raw else f"item-{index + 1}"


def _engagement(row: Mapping[str, Any]) -> tuple[int, int]:
    nested = row.get("engagement") if isinstance(row.get("engagement"), Mapping) else {}
    score = _number(row.get("score") or nested.get("score") or row.get("engagement_score"))
    comments = _number(row.get("num_comments") or nested.get("num_comments") or row.get("comment_count"))
    return score, comments


def build_evidence_pool(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Merge all returned source records, even when the vendor has no clusters."""
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    ranked = report.get("ranked_candidates")
    if isinstance(ranked, list):
        for row in ranked:
            if isinstance(row, Mapping):
                candidates.append((str(row.get("source") or "unknown").casefold(), row))
    items = report.get("items_by_source")
    if isinstance(items, Mapping):
        for source, rows in items.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, Mapping):
                    candidates.append((str(row.get("source") or source or "unknown").casefold(), row))

    merged: dict[str, dict[str, Any]] = {}
    for index, (source, row) in enumerate(candidates):
        identifier = _item_id(row, index)
        url = _clean(row.get("url") or row.get("source_url"))
        key = f"url:{url}" if url else f"id:{source}:{identifier}"
        score, comments = _engagement(row)
        raw_body = _clean(row.get("excerpt_original") or row.get("snippet") or row.get("summary") or row.get("body"), 1800)
        title = _clean(row.get("title") or row.get("name") or row.get("source_title"), 320)
        if not title and not raw_body:
            continue
        normalized = {
            "evidence_id": f"{source}:{identifier}",
            "source": source,
            "item_id": identifier,
            "url": url,
            "title_original": title,
            "excerpt_original": raw_body,
            "published_at": _clean(row.get("published_at") or row.get("date") or row.get("created_at")),
            "author": _clean(row.get("author") or row.get("username") or row.get("creator")) or "未知",
            "engagement": score,
            "comment_count": comments,
        }
        prior = merged.get(key)
        if prior is None:
            merged[key] = normalized
            continue
        # Prefer the richer body/title while preserving the strongest metrics.
        for field in ("title_original", "excerpt_original", "published_at", "author"):
            if len(str(normalized[field])) > len(str(prior[field])):
                prior[field] = normalized[field]
        prior["engagement"] = max(_number(prior.get("engagement")), score)
        prior["comment_count"] = max(_number(prior.get("comment_count")), comments)

    return sorted(
        merged.values(),
        key=lambda row: (_clean(row.get("published_at")), _number(row.get("engagement")), row["evidence_id"]),
        reverse=True,
    )


def _read_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if isinstance(payload, Mapping) and payload.get("evidence_id"):
                rows[str(payload["evidence_id"])] = dict(payload)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return rows


def _append_cache(path: Path | None, rows: Sequence[Mapping[str, Any]]) -> None:
    if path is None or not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def _client(environment: Mapping[str, str]) -> DeepSeekClient:
    from .last30days_adapter import Hot30Adapter

    return DeepSeekClient(transport=Hot30Adapter._http_transport, environment=environment)


def extract_item_signals(
    pool: Sequence[Mapping[str, Any]],
    client: DeepSeekClient,
    cache_path: Path | None = None,
    *,
    batch_size: int = 20,
) -> list[dict[str, Any]]:
    """Extract Chinese discussion signals in restartable batches."""
    cached = _read_cache(cache_path)
    output: dict[str, dict[str, Any]] = dict(cached)
    pending = [row for row in pool if str(row.get("evidence_id")) not in output]
    for start in range(0, len(pending), max(1, batch_size)):
        batch = pending[start:start + max(1, batch_size)]
        prompt_rows = [
            {
                "evidence_id": row.get("evidence_id"),
                "source": row.get("source"),
                "title_original": row.get("title_original"),
                "excerpt_original": row.get("excerpt_original"),
                "published_at": row.get("published_at"),
                "engagement": row.get("engagement"),
                "comment_count": row.get("comment_count"),
            }
            for row in batch
        ]
        document = client.chat_json((
            {"role": "system", "content": (
                "你是VOC研究分析员。只返回JSON对象 {items:[...]}。对每条输入证据用简体中文提取："
                "discussion_zh（用户在讨论什么）、user_context_zh（谁/什么场景）、pain_need_zh（痛点或需求）、"
                "current_response_zh（当前怎么处理）、candidate_topic_zh、candidate_topic_en、title_zh、excerpt_zh。"
                "保留车型、发动机、产品和品牌英文专名；只能使用输入内容，不确定写‘证据不足’；每条必须保留原 evidence_id。"
            )},
            {"role": "user", "content": json.dumps({"items": prompt_rows}, ensure_ascii=False)},
        ), model="deepseek-v4-flash")
        raw_items = document.get("items") if isinstance(document, Mapping) else []
        if not isinstance(raw_items, list):
            continue
        by_id = {str(row.get("evidence_id")): row for row in batch}
        completed: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            evidence_id = _clean(item.get("evidence_id"))
            source = by_id.get(evidence_id)
            if not source:
                continue
            merged = dict(source)
            merged.update({
                key: _clean(item.get(key), 1200)
                for key in (
                    "title_zh", "excerpt_zh", "discussion_zh", "user_context_zh",
                    "pain_need_zh", "current_response_zh", "candidate_topic_zh", "candidate_topic_en",
                )
                if _clean(item.get(key))
            })
            completed.append(merged)
            output[evidence_id] = merged
        _append_cache(cache_path, completed)
    return [dict(row) for row in pool if str(row.get("evidence_id")) in output for row in (output[str(row.get("evidence_id"))],)]


def _evidence_lookup(pool: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in pool:
        identifier = _clean(row.get("evidence_id"))
        if not identifier:
            continue
        value = dict(row)
        lookup[identifier] = value
        # Models sometimes cite the URL or source item id rather than the
        # canonical evidence_id. Keep those aliases local to validation.
        for alias in (_clean(row.get("url")), _clean(row.get("item_id"))):
            if alias:
                lookup.setdefault(alias, value)
    return lookup


def _topic_rows(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Accept the small naming variations seen across gateway deployments."""
    for key in ("topics", "topic_cards", "formal_topics", "hot_topics"):
        rows = document.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, Mapping)]
    return []


def _raw_evidence_refs(topic: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in (
        "evidence_ids", "supporting_evidence_ids", "evidence_refs", "supporting_evidence",
        "evidence", "evidence_items", "supporting_posts", "post_ids",
    ):
        value = topic.get(key)
        if not isinstance(value, list):
            if value:
                value = [value]
            else:
                continue
        for item in value:
            if isinstance(item, Mapping):
                item = item.get("evidence_id") or item.get("id") or item.get("post_id") or item.get("url")
            text = _clean(item)
            if text and text not in refs:
                refs.append(text)
    return refs


def _merge_enriched_pool(
    base_pool: Sequence[Mapping[str, Any]],
    enriched_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay model translations on source metadata without losing counts."""
    enriched = _evidence_lookup(enriched_rows)
    merged: list[dict[str, Any]] = []
    for row in base_pool:
        identifier = str(row.get("evidence_id") or "")
        value = dict(row)
        if identifier in enriched:
            value.update({key: item for key, item in enriched[identifier].items() if item not in (None, "")})
        merged.append(value)
    return merged


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _text_list(value: Any, *, limit: int = 5) -> list[str]:
    """Normalize model summaries that may be returned as a string or list."""
    if isinstance(value, str):
        text = _clean(value, 500)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _clean(item, 500)
        if text and text not in output:
            output.append(text)
    return output[:limit]


def _published_date(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _apply_sample_heat(
    topics: Sequence[dict[str, Any]],
    lookup: Mapping[str, Mapping[str, Any]],
    *,
    source_total: int,
) -> None:
    """Compute comparable sample heat from validated evidence only."""
    metrics: list[tuple[dict[str, Any], int, float, int, float, int]] = []
    today = date.today()
    for topic in topics:
        rows = [lookup[eid] for eid in topic.get("evidence_ids", []) if eid in lookup]
        evidence_count = len(rows)
        engagement = sum(math.log1p(_number(row.get("engagement"))) for row in rows)
        sources = len({str(row.get("source")) for row in rows if row.get("source")})
        recencies = []
        for row in rows:
            published = _published_date(row.get("published_at"))
            if published:
                recencies.append(max(0.0, min(1.0, 1 - max(0, (today - published).days) / 30)))
        recency = sum(recencies) / len(recencies) if recencies else 0.0
        authors = {
            _clean(row.get("author")).casefold()
            for row in rows
            if _clean(row.get("author")) and _clean(row.get("author")).casefold() not in {"unknown", "未知", "anonymous", "匿名"}
        }
        metrics.append((topic, evidence_count, engagement, sources, recency, len(authors)))
    if not metrics:
        return
    max_evidence = max(item[1] for item in metrics) or 1
    max_engagement = max(item[2] for item in metrics) or 1.0
    max_sources = max(1, source_total)
    for topic, evidence_count, engagement, sources, recency, participant_count in metrics:
        score = round(100 * (
            0.35 * evidence_count / max_evidence
            + 0.25 * engagement / max_engagement
            + 0.20 * sources / max_sources
            + 0.20 * recency
        ))
        heat = topic.get("heat") if isinstance(topic.get("heat"), dict) else {}
        heat.update({
            "score": max(0, min(100, score)),
            "label_zh": "高热样本" if score >= 70 else "中热样本" if score >= 40 else "低热样本",
            "evidence_count": evidence_count,
            "source_count": sources,
            "participant_count": participant_count,
        })
        topic["heat"] = heat


def validate_overview(document: Mapping[str, Any], evidence_pool: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep only model claims that cite evidence from this exact run."""
    lookup = _evidence_lookup(evidence_pool)
    result = dict(document)
    valid_topics: list[dict[str, Any]] = []
    weak_topics: list[dict[str, Any]] = []
    raw_topics = _topic_rows(document)
    for index, raw in enumerate(raw_topics):
        if not isinstance(raw, Mapping):
            continue
        ids: list[str] = []
        for value in _raw_evidence_refs(raw):
            row = lookup.get(value)
            if row is None and value.startswith("http"):
                row = lookup.get(value.rstrip("/"))
            if row is None:
                continue
            identifier = _clean(row.get("evidence_id"))
            if identifier and identifier not in ids:
                ids.append(identifier)
        if not ids:
            continue
        topic = dict(raw)
        topic["topic_id"] = _clean(topic.get("topic_id")) or f"hot30-{hashlib.sha1('|'.join(ids).encode()).hexdigest()[:10]}"
        # The gateway occasionally follows the prompt's ``topic_title_*``
        # naming even though our canonical contract uses ``title_*``. Accept
        # both spellings, then persist only the canonical fields.
        topic["title_zh"] = _clean(
            topic.get("title_zh") or topic.get("topic_title_zh") or topic.get("title") or "未命名话题"
        )
        topic["title_en"] = _clean(topic.get("title_en") or topic.get("topic_title_en"))
        topic["one_line_zh"] = _clean(topic.get("one_line_zh") or topic.get("summary_zh") or topic.get("summary"), 800)
        for field in (
            "discussion_zh", "user_context_zh", "pain_need_zh", "current_response_zh",
            "why_watch_zh", "opportunity_hypothesis_zh", "counter_signal_zh",
        ):
            topic[field] = _clean(topic.get(field), 1600)
        topic["evidence_ids"] = ids
        topic["evidence"] = [lookup[item] for item in ids]
        topic["heat"] = dict(topic.get("heat") or {}) if isinstance(topic.get("heat"), Mapping) else {}
        topic["heat"]["evidence_count"] = len(ids)
        topic["heat"]["source_count"] = len({lookup[item].get("source") for item in ids})
        if len(ids) >= 3:
            valid_topics.append(topic)
        else:
            weak_topics.append(topic)
    result["topics"] = valid_topics
    raw_watchlist = document.get("watchlist") if isinstance(document.get("watchlist"), list) else []
    result["watchlist"] = weak_topics + [
        dict(item) for item in raw_watchlist
        if isinstance(item, Mapping) and any(ref in lookup for ref in _raw_evidence_refs(item))
    ]
    for item in result["watchlist"]:
        ids: list[str] = []
        for value in _raw_evidence_refs(item):
            row = lookup.get(value)
            if row is None and value.startswith("http"):
                row = lookup.get(value.rstrip("/"))
            identifier = _clean(row.get("evidence_id")) if row else ""
            if identifier and identifier not in ids:
                ids.append(identifier)
        item["evidence_ids"] = ids
        item["evidence"] = [lookup[eid] for eid in item["evidence_ids"]]
    _apply_sample_heat(valid_topics + [item for item in result["watchlist"] if isinstance(item, dict)], lookup, source_total=len({
        str(row.get("source")) for row in evidence_pool if row.get("source")
    }))
    snapshot = result.get("data_snapshot") if isinstance(result.get("data_snapshot"), Mapping) else {}
    snapshot = dict(snapshot)
    snapshot["evidence_count"] = len(evidence_pool)
    snapshot["source_count"] = len({str(row.get("source")) for row in evidence_pool if row.get("source")})
    snapshot["formal_topic_count"] = len(valid_topics)
    snapshot["weak_signal_count"] = len(result["watchlist"])
    result["data_snapshot"] = snapshot
    result["status"] = "completed" if valid_topics else "insufficient_evidence"
    return result


def synthesize_overview(
    item_signals: Sequence[Mapping[str, Any]],
    client: DeepSeekClient,
    *,
    source_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask Pro to explain the full 30-day sample and return Chinese topic cards."""
    compact = [
        {
            key: row.get(key)
            for key in (
                "evidence_id", "source", "title_zh", "title_original", "excerpt_zh", "excerpt_original",
                "discussion_zh", "user_context_zh", "pain_need_zh", "current_response_zh",
                "candidate_topic_zh", "candidate_topic_en", "published_at", "engagement", "comment_count",
            )
            if row.get(key)
        }
        for row in item_signals
    ]
    document = client.chat_json((
        {"role": "system", "content": (
            "你是产品市场研究负责人。请只返回JSON对象，生成近30天热点总览。"
            "必须用简体中文写 headline_zh、executive_summary_zh、话题的 title_zh、one_line_zh、"
            "discussion_zh、user_context_zh、pain_need_zh、current_response_zh、why_watch_zh、"
            "opportunity_hypothesis_zh、counter_signal_zh。按用户任务/问题归并，不按关键词机械分组。"
            "每个正式话题至少引用3个不同 evidence_id；不足3个放watchlist。所有结论只能来自输入证据，"
            "机会只能写成待验证假设，不要编造销量、价格、利润或市场规模。"
        )},
        {"role": "user", "content": json.dumps({"source_snapshot": dict(source_snapshot or {}), "evidence": compact}, ensure_ascii=False)},
    ), model="deepseek-v4-pro")
    if not isinstance(document, Mapping):
        return {"status": "analysis_unavailable", "topics": [], "watchlist": [], "limitations_zh": ["模型没有返回可解析的中文总览。"]}
    return dict(document)


def build_hot30_overview(
    report: Mapping[str, Any],
    *,
    environment: Mapping[str, str],
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Build a validated overview from one Skill report; retrieval is never repeated."""
    pool = build_evidence_pool(report)
    base_snapshot = {
        "evidence_count": len(pool),
        "source_count": len({str(row.get("source")) for row in pool if row.get("source")}),
        "actual_start": _clean(report.get("range_from")),
        "actual_end": _clean(report.get("range_to")),
    }
    if not environment.get("DEEPSEEK_API_KEY"):
        return {
            "status": "analysis_unavailable",
            "headline_zh": "本轮数据已获取，中文热点分析尚未运行",
            "executive_summary_zh": [],
            "data_snapshot": {**base_snapshot, "formal_topic_count": 0, "weak_signal_count": 0},
            "topics": [],
            "watchlist": [],
            "limitations_zh": ["未配置 DeepSeek 网关，当前只保存原始来源证据。"],
        }
    try:
        client = _client(environment)
        signals = extract_item_signals(pool, client, cache_path)
        if not signals:
            return {
                "status": "analysis_unavailable",
                "headline_zh": "本轮数据已获取，但未形成可验证中文热点",
                "executive_summary_zh": [],
                "data_snapshot": {**base_snapshot, "formal_topic_count": 0, "weak_signal_count": 0},
                "topics": [], "watchlist": [],
                "limitations_zh": ["帖子级中文提取没有返回有效结果，请从检查点重新分析。"],
            }
        raw = synthesize_overview(signals, client, source_snapshot=base_snapshot)
        raw["headline_zh"] = _clean(raw.get("headline_zh")) or "近30天热点讨论总览"
        raw["executive_summary_zh"] = _text_list(raw.get("executive_summary_zh"))
        raw["data_snapshot"] = {**base_snapshot, **dict(raw.get("data_snapshot") or {})}
        # Keep the complete source count, but use the translated item rows for
        # evidence cards so the HTML can show Chinese excerpts next to links.
        enriched_pool = _merge_enriched_pool(pool, signals)
        validated = validate_overview(raw, enriched_pool)
        validated["data_snapshot"]["evidence_count"] = len(pool)
        return validated
    except Exception as error:
        # Do not turn a provider outage into fake topic cards.
        return {
            "status": "analysis_failed",
            "headline_zh": "本轮数据已获取，但中文热点分析失败",
            "executive_summary_zh": [],
            "data_snapshot": {**base_snapshot, "formal_topic_count": 0, "weak_signal_count": 0},
            "topics": [], "watchlist": [],
            "limitations_zh": [f"DeepSeek 分析失败：{type(error).__name__}。请检查网关状态后重新分析。"],
        }
