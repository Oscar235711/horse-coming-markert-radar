"""Persistent, evidence-linked libraries accumulated by every radar run.

The run artifacts remain immutable snapshots.  This module maintains a small
sanitised project-level index beside them so later runs can reuse what has
already been observed without storing raw post bodies or credentials.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any


COMMUNITY_VERSION = "community-library.v1"
TOPIC_VERSION = "topic-library.v1"
KEYWORD_VERSION = "keyword-library.v1"
_COMMUNITY_MENTION = re.compile(r"(?<![A-Za-z0-9_])r/([A-Za-z0-9_]+)")
_SEED_COMMUNITIES = frozenset({"cummins", "duramax", "powerstroke", "forddiesels"})
_NON_DIESEL_COMMUNITY_TOKENS = frozenset({
    "game", "cricket", "train", "ballast", "job", "career", "hiring", "anime", "meme", "crypto",
})
_DIESEL_COMMUNITY_ANCHORS = frozenset({
    "cummins", "duramax", "powerstroke", "forddiesel", "dieseltech", "diesel", "dpf", "egr", "ccv",
    "pcv", "downpipe", "tuner", "turbo", "injector", "exhaust", "regen", "towing", "truck",
})
_KEYWORD_NOISE = frozenset({
    "http", "https", "www", "com", "reddit", "org", "amp", "comments", "comment", "replies", "reply",
    "gallery", "share", "view", "more", "removed", "deleted", "edit", "as", "well", "if", "don", "doesn",
    "didn", "isn", "won", "wouldn", "t", "s", "ve", "re", "ll", "now", "right", "sure", "know", "make", "no",
    "just", "got", "because", "im", "i", "m", "was", "were", "been", "being", "all", "over", "also",
    "can", "could", "would", "should", "have", "has", "had", "do", "does", "did", "not", "will", "still",
})
_KEYWORD_ANCHORS = frozenset({
    "cummins", "duramax", "powerstroke", "ford", "diesel", "dpf", "egr", "ccv", "pcv", "downpipe",
    "tuner", "tuning", "exhaust", "egt", "temperature", "cooler", "valve", "pipe", "kit", "clamp",
    "regen", "leak", "failure", "failed", "broken", "crack", "clog", "problem", "issue", "fitment",
    "installation", "towing", "hauling", "commute", "winter", "off", "road", "work", "truck", "engine",
    "manifold", "intercooler", "gauge", "sensor", "injector", "turbo", "cooling", "system", "fuel", "oil",
    "filter", "delete", "price", "cost", "upgrade", "performance", "solution",
})
_KEYWORD_STRONG_ANCHORS = frozenset({
    "cummins", "duramax", "powerstroke", "ford", "diesel", "dpf", "egr", "ccv", "pcv", "downpipe",
    "tuner", "tuning", "exhaust", "egt", "cooler", "valve", "pipe", "kit", "clamp", "regen", "leak",
    "failure", "failed", "broken", "crack", "clog", "fitment", "installation", "engine", "manifold",
    "intercooler", "gauge", "sensor", "injector", "turbo", "fuel", "oil", "filter", "delete",
})
_KEYWORD_FRAGMENT_TOKENS = frozenset({
    "a", "an", "and", "are", "at", "because", "but", "by", "for", "from", "got", "i", "im", "in",
    "is", "just", "lot", "my", "new", "of", "on", "out", "over", "some", "the", "to", "under", "up",
    "top", "was", "were", "where", "with", "work", "working", "pulling", "coming", "getting",
})
_NON_DIESEL_KEYWORD_PHRASES = frozenset({"gas engine", "gasoline engine", "motorcycle exhaust"})


def update_project_library(
    root: str | Path,
    analysis: Mapping[str, Any],
    *,
    run_id: str,
    posts: Iterable[Any] = (),
    comments: Iterable[Any] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Upsert one run into three cumulative, secret-free project libraries.

    The operation is idempotent for a repeated ``run_id`` and repeated post or
    comment IDs.  New community mentions are recorded as ``observed`` but are
    never silently added to the active crawl configuration.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    library_root = Path(root)
    library_root.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp(analysis.get("generated_at"), now)
    post_rows = tuple(posts)
    comment_rows = tuple(comments)
    post_by_id = {
        _value(post, "post_id"): post
        for post in post_rows
        if _value(post, "post_id")
    }

    communities_doc = _read_document(library_root / "communities.json", COMMUNITY_VERSION, "communities")
    topics_doc = _read_document(library_root / "topics.json", TOPIC_VERSION, "topics")
    keywords_doc = _read_document(library_root / "keywords.json", KEYWORD_VERSION, "keywords")

    configured_community_keys = {
        _community_key(item)
        for item in _as_list(analysis.get("communities"))
        if _community_key(item)
    }
    community_rows = _community_observations(analysis, post_rows, comment_rows)
    _upsert_communities(
        communities_doc["communities"], community_rows, run_id=run_id,
        timestamp=timestamp, seed_keys=configured_community_keys & _SEED_COMMUNITIES,
    )
    _upsert_topics(topics_doc["topics"], analysis.get("topics"), run_id=run_id, timestamp=timestamp)
    _upsert_keywords(
        keywords_doc["keywords"],
        _keyword_candidates(analysis),
        run_id=run_id,
        timestamp=timestamp,
        post_by_id=post_by_id,
    )

    updated_at = timestamp.isoformat()
    for document in (communities_doc, topics_doc, keywords_doc):
        document["updated_at"] = updated_at
    _write_document(library_root / "communities.json", communities_doc)
    _write_document(library_root / "topics.json", topics_doc)
    _write_document(library_root / "keywords.json", keywords_doc)
    return {
        "community_count": len(communities_doc["communities"]),
        "topic_count": len(topics_doc["topics"]),
        "keyword_count": len(keywords_doc["keywords"]),
        "versions": {
            "communities": communities_doc.get("version", COMMUNITY_VERSION),
            "topics": topics_doc.get("version", TOPIC_VERSION),
            "keywords": keywords_doc.get("version", KEYWORD_VERSION),
        },
        "paths": {
            "communities": str(library_root / "communities.json"),
            "topics": str(library_root / "topics.json"),
            "keywords": str(library_root / "keywords.json"),
        },
    }


def load_project_library(root: str | Path) -> dict[str, Any]:
    """Load all cumulative libraries, returning empty documents when absent."""
    library_root = Path(root)
    return {
        "communities": _read_document(library_root / "communities.json", COMMUNITY_VERSION, "communities")["communities"],
        "topics": _read_document(library_root / "topics.json", TOPIC_VERSION, "topics")["topics"],
        "keywords": _read_document(library_root / "keywords.json", KEYWORD_VERSION, "keywords")["keywords"],
    }


def active_keywords(root: str | Path) -> tuple[str, ...]:
    """Return deduplicated terms that must be used by the next search cycle."""
    active_statuses = {"seed", "configured", "formal", "active"}
    rows = load_project_library(root)["keywords"]
    return tuple(dict.fromkeys(
        str(item.get("normalized_term") or item.get("term_en") or "").strip()
        for item in rows
        if str(item.get("status") or "").casefold() in active_statuses
        and _useful_keyword(item.get("normalized_term") or item.get("term_en"))
        and str(item.get("normalized_term") or item.get("term_en") or "").strip()
    ))


def active_communities(root: str | Path, *, minimum_source_posts: int = 3) -> tuple[str, ...]:
    """Return configured communities plus strongly evidenced discoveries.

    A discovered subreddit becomes usable without a manual copy step only
    after three relevant source posts from three distinct authors. Legacy
    ``approved`` rows are deliberately not trusted as crawl authority.
    """
    rows = load_project_library(root)["communities"]
    output: list[str] = []
    for item in rows:
        status = str(item.get("status") or "observed").casefold()
        source_count = len(set(str(value) for value in _as_list(item.get("source_post_ids")) if value))
        author_count = len(set(str(value) for value in _as_list(item.get("source_author_ids")) if value))
        relevant_count = len(set(str(value) for value in _as_list(item.get("relevant_source_post_ids")) if value))
        key = _community_key(item.get("key") or item.get("display_name") or item.get("subreddit"))
        if status in {"rejected", "disabled", "quarantined"}:
            continue
        if key in _SEED_COMMUNITIES or (
            status == "active" and source_count >= minimum_source_posts
            and author_count >= 3 and relevant_count >= minimum_source_posts
        ):
            name = str(item.get("display_name") or item.get("subreddit") or item.get("key") or "").strip().removeprefix("r/")
            if name and name.casefold() not in {value.casefold() for value in output}:
                output.append(name)
    return tuple(output)


def _community_observations(analysis: Mapping[str, Any], posts: Sequence[Any], comments: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _as_list(analysis.get("community_library")):
        if isinstance(item, Mapping):
            name = str(item.get("subreddit") or item.get("display_name") or item.get("name") or "")
            row = dict(item)
            row["name"] = name
            rows.append(row)
    for value in _as_list(analysis.get("communities")):
        rows.append({"name": str(value)})
    for post in posts:
        subreddit = _value(post, "subreddit")
        if subreddit:
            rows.append({
                "name": subreddit,
                "post_id": _value(post, "post_id"),
                "url": _value(post, "url"),
                "author": _value(post, "author"),
                "text": " ".join((_value(post, "title"), _value(post, "body"))),
                "platform": _platform(subreddit),
            })
        text = " ".join((_value(post, "title"), _value(post, "body")))
        rows.extend({
            "name": match.group(1), "post_id": _value(post, "post_id"), "url": _value(post, "url"),
            "author": _value(post, "author"), "text": text, "platform": _platform(match.group(1)),
        } for match in _COMMUNITY_MENTION.finditer(text))
    for comment in comments:
        text = _value(comment, "body")
        rows.extend({
            "name": match.group(1), "post_id": _value(comment, "post_id"), "comment_id": _value(comment, "comment_id"),
            "author": _value(comment, "author"), "text": text,
        } for match in _COMMUNITY_MENTION.finditer(text))
    return rows


def _upsert_communities(
    records: list[dict[str, Any]], observations: Sequence[Mapping[str, Any]], *,
    run_id: str, timestamp: datetime, seed_keys: set[str],
) -> None:
    by_key = {str(item.get("key", "")).casefold(): item for item in records if item.get("key")}
    for observation in observations:
        key = _community_key(observation.get("name"))
        if not key:
            continue
        item = by_key.get(key)
        if item is None:
            item = {
                "key": key,
                "subreddit": f"r/{key}",
                "display_name": _display_community(observation.get("name"), key),
                "status": "seed" if key in seed_keys else ("observed" if _diesel_community_observation(key, observation) else "quarantined"),
                "platforms": [],
                "aliases": [],
                "source_post_ids": [],
                "source_author_ids": [],
                "relevant_source_post_ids": [],
                "source_urls": [],
                "topic_ids": [],
                "run_ids": [],
                "first_seen": timestamp.isoformat(),
                "last_seen": timestamp.isoformat(),
            }
            records.append(item)
            by_key[key] = item
        status = str(item.get("status", "observed")).casefold()
        if key in seed_keys or key in _SEED_COMMUNITIES:
            item["status"] = "seed"
        elif status == "approved":
            item["status"] = "observed" if _diesel_community_name(key) else "quarantined"
        for field in ("aliases", "platforms"):
            values = item.setdefault(field, [])
            _merge_values(values, observation.get(field, ()))
        display = str(observation.get("display_name") or observation.get("name") or "").strip()
        if display and display.casefold().removeprefix("r/") != key:
            _merge_values(item.setdefault("aliases", []), [display])
        platform = str(observation.get("platform") or _platform(key)).strip()
        if platform:
            _merge_values(item.setdefault("platforms", []), [platform])
        for field in ("post_id",):
            value = str(observation.get(field) or "").strip()
            if value:
                _merge_values(item.setdefault("source_post_ids", []), [value])
                if _diesel_community_observation(key, observation):
                    _merge_values(item.setdefault("relevant_source_post_ids", []), [value])
        author = str(observation.get("author") or "").strip()
        if author:
            _merge_values(item.setdefault("source_author_ids", []), [author])
        url = str(observation.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            _merge_values(item.setdefault("source_urls", []), [url])
        _merge_values(item.setdefault("run_ids", []), [run_id])
        item["first_seen"] = min(str(item.get("first_seen") or timestamp.isoformat()), timestamp.isoformat())
        item["last_seen"] = max(str(item.get("last_seen") or timestamp.isoformat()), timestamp.isoformat())
        item["run_count"] = len(item.get("run_ids", []))
        item["source_post_count"] = len(item.get("source_post_ids", []))
        item["source_author_count"] = len(item.get("source_author_ids", []))
        item["relevant_source_post_count"] = len(item.get("relevant_source_post_ids", []))
        if key not in _SEED_COMMUNITIES and not _diesel_community_observation(key, observation):
            item["status"] = "quarantined"
        elif item.get("status") == "observed" and (
            item["source_post_count"] >= 3
            and item["source_author_count"] >= 3
            and item["relevant_source_post_count"] >= 3
        ):
            item["status"] = "active"
    records.sort(key=lambda item: str(item.get("key", "")))


def _upsert_topics(records: list[dict[str, Any]], raw_topics: Any, *, run_id: str, timestamp: datetime) -> None:
    by_key = {str(item.get("key", "")).casefold(): item for item in records if item.get("key")}
    for raw in _as_list(raw_topics):
        if not isinstance(raw, Mapping):
            continue
        community = _community_key(raw.get("community"))
        canonical = _normalise(raw.get("canonical_key") or raw.get("label_en") or raw.get("label_zh"))
        if not community or not canonical:
            continue
        identity = f"{community}|{canonical}"
        item = by_key.get(identity)
        if item is None:
            item = {
                "key": identity,
                "topic_id": str(raw.get("topic_id") or ""),
                "community": community,
                "canonical_key": canonical,
                "label_en": str(raw.get("label_en") or canonical),
                "label_zh": str(raw.get("label_zh") or "待翻译"),
                "status": "weak_signal",
                "source_post_ids": [],
                "source_urls": [],
                "run_ids": [],
                "pains": [],
                "needs": [],
                "current_solutions": [],
                "gaps": [],
                "opportunity_hypotheses": [],
                "first_seen": timestamp.isoformat(),
                "last_seen": timestamp.isoformat(),
            }
            records.append(item)
            by_key[identity] = item
        _merge_values(item.setdefault("source_post_ids", []), _topic_post_ids(raw))
        _merge_values(item.setdefault("source_urls", []), [e.get("url") for e in _as_list(raw.get("evidence")) if isinstance(e, Mapping)])
        _merge_values(item.setdefault("run_ids", []), [run_id])
        for field in ("pains", "needs", "current_solutions", "gaps", "opportunity_hypotheses"):
            _merge_values(item.setdefault(field, []), raw.get(field, ()))
        if str(raw.get("status", "")).casefold() == "formal":
            item["status"] = "formal"
        item["topic_id"] = item.get("topic_id") or str(raw.get("topic_id") or "")
        item["label_en"] = str(raw.get("label_en") or item.get("label_en") or canonical)
        item["label_zh"] = str(raw.get("label_zh") or item.get("label_zh") or "待翻译")
        item["post_count_latest"] = _int(raw.get("post_count"))
        item["author_count_max"] = max(_int(item.get("author_count_max")), _int(raw.get("author_count")))
        item["commenter_count_max"] = max(_int(item.get("commenter_count_max")), _int(raw.get("commenter_count")))
        item["heat_score_max"] = max(_float(item.get("heat_score_max")), _float(raw.get("heat_score")))
        item["first_seen"] = min(str(item.get("first_seen") or timestamp.isoformat()), timestamp.isoformat())
        item["last_seen"] = max(str(item.get("last_seen") or timestamp.isoformat()), timestamp.isoformat())
        item["run_count"] = len(item.get("run_ids", []))
        item["source_post_count"] = len(item.get("source_post_ids", []))
    records.sort(key=lambda item: (str(item.get("community", "")), str(item.get("canonical_key", ""))))


def _upsert_keywords(
    records: list[dict[str, Any]], candidates: Sequence[Mapping[str, Any]], *,
    run_id: str, timestamp: datetime, post_by_id: Mapping[str, Any],
) -> None:
    # A previous run may have been generated before URL/UI filtering existed;
    # clean those rows as they are loaded so the cumulative library converges
    # instead of preserving known noise forever.
    for item in records:
        if not _useful_keyword(item.get("normalized_term") or item.get("term_en")):
            item["status"] = "quarantined"
    # Keywords are global search concepts.  Community provenance belongs in a
    # list on the row; it must not create duplicate keyword identities.
    migrated: dict[str, dict[str, Any]] = {}
    for existing in records:
        term = _normalise(existing.get("normalized_term") or existing.get("term_en"))
        if not term:
            continue
        prior = migrated.get(term)
        if prior is None:
            existing["key"] = term
            community = str(existing.pop("community", "") or "").strip()
            existing.setdefault("communities", [])
            if community:
                _merge_values(existing["communities"], [community])
            migrated[term] = existing
        else:
            for field in ("communities", "variants", "source_post_ids", "source_comment_ids", "source_urls", "signal_types", "run_ids"):
                _merge_values(prior.setdefault(field, []), existing.get(field, ()))
            community = str(existing.get("community") or "").strip()
            if community:
                _merge_values(prior.setdefault("communities", []), [community])
    records[:] = list(migrated.values())
    by_key = {str(item.get("key", "")).casefold(): item for item in records if item.get("key")}
    for raw in candidates:
        term = _normalise(raw.get("term_en") or raw.get("term") or "")
        if not _useful_keyword(term):
            continue
        community = str(raw.get("community") or "").strip().removeprefix("r/")
        identity = term
        item = by_key.get(identity)
        if item is None:
            item = {
                "key": identity,
                "keyword_id": str(raw.get("keyword_id") or f"kw_{_slug(term)}"),
                "normalized_term": term,
                "term_en": str(raw.get("term_en") or raw.get("term") or term),
                "term_zh": str(raw.get("term_zh") or "待翻译"),
                "communities": [],
                "topic_keys": [],
                "variants": [],
                "source_post_ids": [],
                "source_comment_ids": [],
                "source_urls": [],
                "signal_types": [],
                "run_ids": [],
                "first_seen": timestamp.isoformat(),
                "last_seen": timestamp.isoformat(),
            }
            records.append(item)
            by_key[identity] = item
        if community:
            _merge_values(item.setdefault("communities", []), [community])
        for field in ("variants", "source_post_ids", "source_comment_ids", "signal_types"):
            _merge_values(item.setdefault(field, []), raw.get(field, ()))
        topic_key = str(raw.get("topic_key") or "").strip()
        if topic_key:
            _merge_values(item.setdefault("topic_keys", []), [topic_key])
        for post_id in _as_list(raw.get("source_post_ids")):
            post = post_by_id.get(str(post_id))
            url = _value(post, "url")
            if url.startswith(("http://", "https://")):
                _merge_values(item.setdefault("source_urls", []), [url])
        _merge_values(item.setdefault("run_ids", []), [run_id])
        item["score_max"] = max(_float(item.get("score_max")), _float(raw.get("score")))
        item["post_count_latest"] = _int(raw.get("post_count"))
        item["author_count_max"] = max(_int(item.get("author_count_max")), _int(raw.get("author_count")))
        item["status"] = _keyword_status(item.get("status"), raw.get("status"))
        item["first_seen"] = min(str(item.get("first_seen") or timestamp.isoformat()), timestamp.isoformat())
        item["last_seen"] = max(str(item.get("last_seen") or timestamp.isoformat()), timestamp.isoformat())
        item["run_count"] = len(item.get("run_ids", []))
        item["source_post_count"] = len(item.get("source_post_ids", []))
        item["source_comment_count"] = len(item.get("source_comment_ids", []))
        if (
            str(item.get("status", "")).casefold() not in {"rejected", "disabled", "quarantined"}
            and item["source_post_count"] >= 2
            and item["author_count_max"] >= 2
            and _float(item.get("score_max")) >= 20
        ):
            item["status"] = "active"
    records.sort(key=lambda item: (-_float(item.get("score_max")), str(item.get("normalized_term", ""))))


def _keyword_candidates(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    library = analysis.get("keyword_library")
    if isinstance(library, Mapping):
        return [item for item in _as_list(library.get("candidates")) if isinstance(item, Mapping)]
    return [item for item in _as_list(analysis.get("keyword_candidates")) if isinstance(item, Mapping)]


def _topic_post_ids(topic: Mapping[str, Any]) -> list[str]:
    ids = [str(topic.get("post_id") or "").strip()]
    ids.extend(str(item.get("post_id") or "").strip() for item in _as_list(topic.get("evidence")) if isinstance(item, Mapping))
    return [item for item in dict.fromkeys(ids) if item]


def _read_document(path: Path, version: str, collection_key: str) -> dict[str, Any]:
    if not path.exists():
        return {"version": version, "updated_at": "", collection_key: []}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": version, "updated_at": "", collection_key: []}
    if not isinstance(document, Mapping):
        return {"version": version, "updated_at": "", collection_key: []}
    rows = document.get(collection_key)
    return {"version": str(document.get("version") or version), "updated_at": str(document.get("updated_at") or ""), collection_key: [dict(item) for item in _as_list(rows) if isinstance(item, Mapping)]}


def _write_document(path: Path, document: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(document), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _merge_values(target: list[Any], values: Any) -> None:
    for value in _as_list(values):
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in target:
            target.append(text)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def _value(value: Any, field: str) -> str:
    if isinstance(value, Mapping):
        raw = value.get(field, "")
    else:
        raw = getattr(value, field, "")
    return str(raw or "").strip()


def _normalise(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold().replace("-", " ")))


def _useful_keyword(value: Any) -> bool:
    term = _normalise(value)
    tokens = term.split()
    numeric_tokens = [token for token in tokens if token.isdigit()]
    return bool(term and len(tokens) >= 2 and term not in _NON_DIESEL_KEYWORD_PHRASES
                and not any(token in _KEYWORD_FRAGMENT_TOKENS for token in tokens)
                and not any(token in _KEYWORD_NOISE for token in tokens)
                and any(token in _KEYWORD_STRONG_ANCHORS for token in tokens)
                and (not numeric_tokens or len(numeric_tokens) >= 2)
                and not any(token.isdigit() and len(token) >= 2 for token in tokens))


def _diesel_community_name(key: str) -> bool:
    """Whether a subreddit name itself provides a diesel-pickup anchor."""
    normalized = _normalise(key)
    if any(token in normalized for token in _NON_DIESEL_COMMUNITY_TOKENS):
        return False
    return any(anchor in normalized for anchor in _DIESEL_COMMUNITY_ANCHORS)


def _diesel_community_observation(key: str, observation: Mapping[str, Any]) -> bool:
    """Require a domain anchor before a discovered subreddit can be promoted."""
    text = " ".join((key, str(observation.get("text") or ""))).casefold()
    if any(token in text for token in _NON_DIESEL_COMMUNITY_TOKENS):
        return False
    return _diesel_community_name(key) or any(anchor in text for anchor in _DIESEL_COMMUNITY_ANCHORS)


def _community_key(value: Any) -> str:
    raw = str(value or "").strip()
    if raw[:2].casefold() == "r/":
        raw = raw[2:]
    return raw.casefold()


def _display_community(value: Any, key: str) -> str:
    raw = str(value or "").strip().removeprefix("r/")
    return raw or key


def _platform(value: Any) -> str:
    key = _community_key(value)
    if "cummins" in key:
        return "Cummins"
    if "duramax" in key:
        return "Duramax"
    if "powerstroke" in key or "ford" in key:
        return "Powerstroke"
    return "柴油皮卡"


def _timestamp(value: Any, fallback: datetime | None) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback or datetime.now(UTC)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")[:48] or "term"


def _keyword_status(current: Any, incoming: Any) -> str:
    priority = {"seed": 6, "active": 5, "approved": 5, "configured": 4, "formal": 4, "observed": 3, "candidate_review": 2, "weak_signal": 1, "rejected": 0}
    current_text = str(current or "observed")
    incoming_text = str(incoming or "observed")
    return incoming_text if priority.get(incoming_text, 1) > priority.get(current_text, 1) else current_text
