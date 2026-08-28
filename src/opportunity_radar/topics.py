"""Evidence-constrained, per-community topic aggregation and artifact export."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from math import log1p
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Protocol

from .deepseek import PostAnalysis
from .models import NormalizedPost
from .storage import TopicRegistry


EXCEL_SHEET_NAMES = (
    "运行概览",
    "社区库",
    "话题关键词库",
    "社区热点排行",
    "话题分析卡",
    "帖子及评论证据",
    "弱信号观察区",
    "排除与失败记录",
)
CURRENT_DAYS = 30
BASELINE_DAYS = 60


@dataclass(frozen=True, slots=True)
class PostSignal:
    """A normalized post, Flash extraction, and its exact evidence URL lookup."""

    post: NormalizedPost
    analysis: PostAnalysis
    evidence_urls: Mapping[str, str]
    comment_authors: tuple[str, ...] = ()
    # Keep comment bodies at the consolidation boundary.  The original
    # implementation retained only URLs, which made the offline fallback
    # unable to explain *why* a topic was created even though comments had
    # already been collected.
    comments: tuple[Any, ...] = ()

    @classmethod
    def from_thread(cls, thread: Any, analysis: PostAnalysis) -> "PostSignal":
        """Build the aggregation input from one collected deep-read thread."""
        evidence_urls = {"post": thread.post.url}
        evidence_urls.update({comment.comment_id: comment.url for comment in thread.comments})
        authors = getattr(thread, "comment_authors", ())
        return cls(
            post=thread.post,
            analysis=analysis,
            evidence_urls=evidence_urls,
            comment_authors=tuple(authors),
            comments=tuple(getattr(thread, "comments", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class TopicEvidence:
    """One Pro-proposed claim; URL is always resolved from its source signal."""

    post_id: str
    evidence_id: str
    claim: str
    stance: str
    translation_zh: str


@dataclass(frozen=True, slots=True)
class EvidenceBackedClaim:
    """A concrete topic assertion bound to its own source evidence."""

    text: str
    evidence: Sequence[TopicEvidence]


@dataclass(frozen=True, slots=True)
class ProTopicProposal:
    """Structured Pro result injected at the boundary, never called by this module."""

    canonical_key: str
    label_en: str
    label_zh: str
    summary: EvidenceBackedClaim
    post_ids: tuple[str, ...]
    evidence: Sequence[TopicEvidence]
    vehicles: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    scenarios: tuple[str, ...] = ()
    pains: tuple[EvidenceBackedClaim, ...] = ()
    needs: tuple[EvidenceBackedClaim, ...] = ()
    current_solutions: tuple[EvidenceBackedClaim, ...] = ()
    gaps: tuple[EvidenceBackedClaim, ...] = ()
    opportunity_hypotheses: tuple[EvidenceBackedClaim, ...] = ()
    category_tags: tuple[str, ...] = ()
    brand_tags: tuple[str, ...] = ()
    competitor_tags: tuple[str, ...] = ()
    confidence: float = 0.0
    validation_questions: tuple[str, ...] = ()


class ProTopicConsolidator(Protocol):
    """Inject a production Pro client or an explicitly labelled offline fixture."""

    mode: str

    def consolidate(self, community: str, signals: Sequence[PostSignal]) -> Sequence[ProTopicProposal]: ...


@dataclass(frozen=True, slots=True)
class TopicAggregationResult:
    analysis: dict[str, Any]
    formal_topics: tuple[dict[str, Any], ...]
    weak_topics: tuple[dict[str, Any], ...]
    excluded_records: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class TopicExportArtifacts:
    analysis_json: Path
    community_topics_json: Path
    workbook_path: Path
    report_path: Path | None = None


def build_community_library(
    communities: Sequence[Any], topics: Sequence[Mapping[str, Any]] = (), config_version: str = ""
) -> list[dict[str, Any]]:
    """Return the dedicated, versionable community catalog projection for reports."""
    topic_rows = [item for item in topics if isinstance(item, Mapping)]
    rows: list[dict[str, Any]] = []
    for community in communities:
        if isinstance(community, Mapping):
            name = str(community.get("name") or community.get("display_name") or "").strip()
            aliases = list(community.get("aliases", []) or [])
            include_terms = list(community.get("include", community.get("include_terms", [])) or [])
            exclude_terms = list(community.get("exclude", community.get("exclude_terms", [])) or [])
            slang = list(community.get("slang", []) or [])
            platform = str(community.get("brand") or community.get("category") or _platform_for_community(name))
            community_id = str(community.get("community_id") or f"r/{name}")
            status = str(community.get("status") or "approved")
        else:
            name = str(getattr(community, "name", "") or "").strip()
            aliases = list(getattr(community, "aliases", ()) or ())
            include_terms = list(getattr(community, "include", ()) or ())
            exclude_terms = list(getattr(community, "exclude", ()) or ())
            slang = list(getattr(community, "slang", ()) or ())
            platform = str(getattr(community, "brand", "") or getattr(community, "category", "") or _platform_for_community(name))
            community_id = str(getattr(community, "community_id", "") or f"r/{name}")
            status = str(getattr(community, "status", "approved") or "approved")
        if not name:
            continue
        rows.append({
            "community_id": community_id,
            "subreddit": f"r/{name.removeprefix('r/')}",
            "display_name": name,
            "platform": platform,
            "status": status,
            "aliases": aliases,
            "include_terms": include_terms,
            "exclude_terms": exclude_terms,
            "slang": slang,
            "config_version": config_version,
            "topic_count": sum(1 for topic in topic_rows if str(topic.get("community", "")).removeprefix("r/").casefold() == name.removeprefix("r/").casefold()),
        })
    return rows


class TopicAggregator:
    """Consolidate only one community at a time and retain only cited claims."""

    def __init__(self, *, pro: ProTopicConsolidator, registry: TopicRegistry, as_of: datetime) -> None:
        self._pro = pro
        self._registry = registry
        self._as_of = as_of

    def aggregate(self, community: str, signals: Sequence[PostSignal]) -> TopicAggregationResult:
        signals = tuple(
            signal for signal in signals if signal.post.subreddit.casefold() == community.casefold()
        )
        signal_by_id = {signal.post.post_id: signal for signal in signals}
        selected_per_post: dict[str, int] = defaultdict(int)
        excluded: list[dict[str, str]] = []
        candidates: list[dict[str, Any]] = []

        for proposal in self._pro.consolidate(community, tuple(signals)):
            unique_post_ids = tuple(dict.fromkeys(proposal.post_ids))
            accepted_post_ids = tuple(
                post_id for post_id in unique_post_ids
                if post_id in signal_by_id and selected_per_post[post_id] < 3
            )
            if not accepted_post_ids:
                excluded.append(_excluded(proposal.canonical_key, "no_eligible_posts"))
                continue
            valid_evidence = _validated_evidence(proposal.evidence, accepted_post_ids, signal_by_id)
            if valid_evidence is None:
                excluded.append(_excluded(proposal.canonical_key, "invalid_evidence"))
                continue
            for post_id in accepted_post_ids:
                selected_per_post[post_id] += 1
            candidates.append(self._make_topic(community, proposal, accepted_post_ids, valid_evidence, signal_by_id))

        _apply_heat_scores(candidates)
        candidates.sort(key=lambda topic: (-topic["heat_score"], topic["canonical_key"]))
        formal = tuple(topic for topic in candidates if topic["status"] == "formal")
        weak = tuple(topic for topic in candidates if topic["status"] == "weak_signal")
        analysis = {
            "analysis_version": "1.0",
            "generated_at": self._as_of.isoformat(),
            "communities": [community],
            "topics": candidates,
            "excluded_records": excluded,
            "model_mode": getattr(self._pro, "mode", "injected_pro"),
            "product_output_label": "opportunity hypothesis, not launch conclusion",
        }
        return TopicAggregationResult(analysis, formal, weak, tuple(excluded))

    def aggregate_threads(
        self, community: str, threads: Sequence[Any], analyses: Sequence[PostAnalysis]
    ) -> TopicAggregationResult:
        """Aggregate collected deep-read threads without dropping commenter authors."""
        threads = tuple(threads)
        analyses = tuple(analyses)
        if len(threads) != len(analyses):
            raise ValueError("threads and analyses must have the same length")
        signals = tuple(PostSignal.from_thread(thread, analysis) for thread, analysis in zip(threads, analyses))
        return self.aggregate(community, signals)

    def _make_topic(
        self,
        community: str,
        proposal: ProTopicProposal,
        post_ids: tuple[str, ...],
        evidence: list[dict[str, str]],
        signal_by_id: Mapping[str, PostSignal],
    ) -> dict[str, Any]:
        posts = [signal_by_id[post_id].post for post_id in post_ids]
        current_posts = [post for post in posts if self._is_current(post.created_at)]
        baseline_posts = [post for post in posts if self._is_baseline(post.created_at)]
        current_rate = len(current_posts) / CURRENT_DAYS
        baseline_rate = len(baseline_posts) / BASELINE_DAYS
        commenter_count = len(_distinct_commenters(post_ids, signal_by_id))
        formal = _is_formal(posts, commenter_count)
        summary = _validated_claim(proposal.summary, post_ids, signal_by_id)
        pains = _validated_claims(proposal.pains, post_ids, signal_by_id)
        needs = _validated_claims(proposal.needs, post_ids, signal_by_id)
        current_solutions = _validated_claims(proposal.current_solutions, post_ids, signal_by_id)
        gaps = _validated_claims(proposal.gaps, post_ids, signal_by_id)
        opportunity_hypotheses = _validated_claims(
            proposal.opportunity_hypotheses, post_ids, signal_by_id
        )
        record = self._registry.get_or_create(
            community=community,
            canonical_key=proposal.canonical_key,
            label_en=proposal.label_en,
            label_zh=proposal.label_zh,
        )
        return {
            "topic_id": record.topic_id,
            "community": record.community,
            "canonical_key": record.canonical_key,
            "label_en": record.label_en,
            "label_zh": record.label_zh,
            "summary": summary["text"] if summary is not None else "unknown",
            "status": "formal" if formal else "weak_signal",
            "trend": _trend(formal, current_rate, baseline_rate),
            "post_count": len(posts),
            "author_count": len({post.author for post in posts if post.author}),
            "commenter_count": commenter_count,
            "upvote_count": sum(max(0, post.score) for post in posts),
            "current_post_count": len(current_posts),
            "baseline_post_count": len(baseline_posts),
            "current_daily_rate": round(current_rate, 4),
            "baseline_daily_rate": round(baseline_rate, 4),
            "heat_score": 0.0,
            "vehicles": list(proposal.vehicles),
            "platforms": list(proposal.platforms),
            "scenarios": list(proposal.scenarios),
            "pains": [claim["text"] for claim in pains],
            "needs": [claim["text"] for claim in needs],
            "current_solutions": [claim["text"] for claim in current_solutions],
            "gaps": [claim["text"] for claim in gaps],
            "opportunity_hypotheses": [claim["text"] for claim in opportunity_hypotheses],
            "category_tags": list(proposal.category_tags),
            "brand_tags": list(proposal.brand_tags),
            "competitor_tags": list(proposal.competitor_tags),
            "confidence": max(0.0, min(1.0, proposal.confidence)),
            "validation_questions": list(proposal.validation_questions),
            "evidence": evidence,
            "supporting_views": _views(evidence, "supporting"),
            "opposing_views": _views(evidence, "opposing"),
            "claim_evidence": {
                "summary": summary if summary is not None else {"text": "unknown", "evidence": []},
                "pains": pains,
                "needs": needs,
                "current_solutions": current_solutions,
                "gaps": gaps,
                "opportunity_hypotheses": opportunity_hypotheses,
            },
            "field_evidence": {
                "vehicles": _labelled_evidence(proposal.vehicles, evidence),
                "platforms": _labelled_evidence(proposal.platforms, evidence),
                "scenarios": _labelled_evidence(proposal.scenarios, evidence),
                "category_tags": _labelled_evidence(proposal.category_tags, evidence),
                "brand_tags": _labelled_evidence(proposal.brand_tags, evidence),
                "competitor_tags": _labelled_evidence(proposal.competitor_tags, evidence),
                "validation_questions": _labelled_evidence(proposal.validation_questions, evidence),
                "supporting_views": _labelled_evidence(_views(evidence, "supporting"), evidence),
                "opposing_views": _labelled_evidence(_views(evidence, "opposing"), evidence),
            },
            "model_mode": getattr(self._pro, "mode", "injected_pro"),
        }

    def _is_current(self, created_at: datetime) -> bool:
        return self._as_of - timedelta(days=CURRENT_DAYS) <= created_at <= self._as_of

    def _is_baseline(self, created_at: datetime) -> bool:
        return self._as_of - timedelta(days=CURRENT_DAYS + BASELINE_DAYS) <= created_at < self._as_of - timedelta(days=CURRENT_DAYS)


def export_topic_analysis(
    analysis: Mapping[str, Any],
    *,
    output_dir: str | Path,
    formats: Sequence[str] = ("json", "xlsx"),
    node_executable: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> TopicExportArtifacts:
    """Persist one canonical analysis then derive only the requested projections."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    canonical = dict(analysis)
    canonical.setdefault("community_library", _fallback_community_library(canonical))
    if "keyword_library" not in canonical:
        legacy_keywords = canonical.get("keyword_candidates", [])
        canonical["keyword_library"] = {
            "version": "topic-keywords.v1",
            "formal_terms": [],
            "candidates": [
                {
                    "keyword_id": f"kw_legacy_{index + 1}",
                    "term_en": item.get("term", "") if isinstance(item, Mapping) else "",
                    "term_zh": item.get("term_zh", "待翻译") if isinstance(item, Mapping) else "待翻译",
                    "keyword_type": item.get("keyword_type", "candidate") if isinstance(item, Mapping) else "candidate",
                    "community": item.get("community", "") if isinstance(item, Mapping) else "",
                    "topic_key": item.get("topic_key", "") if isinstance(item, Mapping) else "",
                    "variants": item.get("variants", []) if isinstance(item, Mapping) else [],
                    "source_post_ids": item.get("source_post_ids", []) if isinstance(item, Mapping) else [],
                    "source_comment_ids": item.get("source_comment_ids", []) if isinstance(item, Mapping) else [],
                    "post_count": item.get("post_count", 0) if isinstance(item, Mapping) else 0,
                    "author_count": item.get("author_count", 0) if isinstance(item, Mapping) else 0,
                    "score": item.get("discovery_score", item.get("score", 0)) if isinstance(item, Mapping) else 0,
                    "status": item.get("status", "candidate_review") if isinstance(item, Mapping) else "candidate_review",
                }
                for index, item in enumerate(legacy_keywords)
            ],
        }
    canonical.setdefault("counts", _analysis_counts(canonical))
    analysis_json = directory / "analysis.json"
    community_topics_json = directory / "community_topics.json"
    workbook_path = directory / "community_topics.xlsx"
    report_path: Path | None = None
    requested_formats = tuple(dict.fromkeys(formats))
    _write_json(analysis_json, canonical)
    _write_json(community_topics_json, {
        "analysis_version": canonical.get("analysis_version"),
        "generated_at": canonical.get("generated_at"),
        "topics": canonical.get("topics", []),
    })
    if "xlsx" in requested_formats:
        builder = Path(__file__).resolve().parents[2] / "scripts" / "build_topic_workbook.mjs"
        node = _resolve_node_executable(node_executable, environment)
        subprocess.run((str(node), str(builder), str(analysis_json), str(workbook_path)), check=True, capture_output=True, text=True)
    if "html" in requested_formats:
        from .report import render_html
        report_path = render_html(canonical, directory / "report.html")
        _write_json(directory / "community_topic_map.json", _community_topic_map(canonical))
    return TopicExportArtifacts(analysis_json, community_topics_json, workbook_path, report_path)


def _community_topic_map(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Tiny graph-ready projection for future WhatToSell-style visualization."""
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    communities = [str(item) for item in analysis.get("communities", []) if item]
    return {
        "nodes": ([{"id": f"community:{name}", "type": "community", "label": name} for name in communities]
                  + [{"id": str(item.get("topic_id", "")), "type": "topic", "label": item.get("label_zh", item.get("label_en", "")), "community": item.get("community")} for item in topics]),
        "edges": [{"source": f"community:{item.get('community')}", "target": item.get("topic_id")} for item in topics if item.get("topic_id")],
    }


def _fallback_community_library(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Create a report-ready community table when callers only provide names."""
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    names = [str(item).removeprefix("r/") for item in analysis.get("communities", []) if item]
    if not names:
        names = list(dict.fromkeys(str(item.get("community", "")) for item in topics if item.get("community")))
    return [
        {
            "community_id": f"r/{name}",
            "subreddit": f"r/{name}",
            "display_name": name,
            "platform": _platform_for_community(name),
            "status": "approved",
            "aliases": [],
            "include_terms": [],
            "exclude_terms": [],
            "slang": [],
            "config_version": str(analysis.get("community_catalog_version", "")),
            "topic_count": sum(1 for topic in topics if str(topic.get("community", "")).removeprefix("r/").casefold() == name.casefold()),
        }
        for name in names
    ]


def _platform_for_community(name: str) -> str:
    normalized = name.casefold().replace("r/", "")
    if "cummins" in normalized:
        return "Cummins"
    if "duramax" in normalized:
        return "Duramax"
    if "powerstroke" in normalized or "ford" in normalized:
        return "Powerstroke"
    return "柴油皮卡"


def _analysis_counts(analysis: Mapping[str, Any]) -> dict[str, int]:
    """Compute all displayed totals once so JSON, HTML and XLSX agree."""
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    evidence_count = sum(len(item.get("evidence", [])) for item in topics if isinstance(item.get("evidence", []), list))
    keyword_library = analysis.get("keyword_library", {})
    keyword_count = len(keyword_library.get("candidates", [])) if isinstance(keyword_library, Mapping) else 0
    return {
        "community_count": len(analysis.get("community_library", [])),
        "topic_count": len(topics),
        "formal_topic_count": sum(1 for item in topics if item.get("status") == "formal"),
        "weak_topic_count": sum(1 for item in topics if item.get("status") == "weak_signal"),
        "evidence_count": evidence_count,
        "keyword_count": keyword_count,
        "excluded_count": len(analysis.get("excluded_records", [])),
    }


def _validated_evidence(
    evidence: Sequence[TopicEvidence],
    accepted_post_ids: Sequence[str],
    signal_by_id: Mapping[str, PostSignal],
) -> list[dict[str, str]] | None:
    if not evidence:
        return None
    accepted = set(accepted_post_ids)
    result: list[dict[str, str]] = []
    for item in evidence:
        signal = signal_by_id.get(item.post_id)
        if item.post_id not in accepted or signal is None or item.evidence_id not in signal.evidence_urls:
            return None
        url = signal.evidence_urls[item.evidence_id]
        if not _is_url(url) or not item.claim.strip() or not item.translation_zh.strip():
            return None
        result.append({
            "evidence_id": f"{item.post_id}:{item.evidence_id}",
            "post_id": item.post_id,
            "url": url,
            "claim_en": item.claim.strip(),
            "claim_zh": item.translation_zh.strip(),
            "stance": item.stance if item.stance in {"supporting", "opposing"} else "supporting",
        })
    return result


def _validated_claim(
    claim: EvidenceBackedClaim, accepted_post_ids: Sequence[str], signal_by_id: Mapping[str, PostSignal]
) -> dict[str, Any] | None:
    if not claim.text.strip():
        return None
    evidence = _validated_evidence(claim.evidence, accepted_post_ids, signal_by_id)
    if evidence is None:
        return None
    return {"text": claim.text.strip(), "evidence": evidence}


def _validated_claims(
    claims: Sequence[EvidenceBackedClaim], accepted_post_ids: Sequence[str], signal_by_id: Mapping[str, PostSignal]
) -> list[dict[str, Any]]:
    return [validated for claim in claims if (validated := _validated_claim(claim, accepted_post_ids, signal_by_id)) is not None]


def _views(evidence: Sequence[Mapping[str, str]], stance: str) -> list[str]:
    return list(dict.fromkeys(item["claim_en"] for item in evidence if item["stance"] == stance))


def _labelled_evidence(values: Sequence[str], evidence: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Keep descriptive tags and validation questions tied to accepted topic evidence."""
    return [
        {"text": value, "evidence": list(evidence)}
        for value in dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip())
    ]


def _is_formal(posts: Sequence[NormalizedPost], commenter_count: int) -> bool:
    authors = {post.author for post in posts if post.author}
    return (len(posts) >= 3 and len(authors) >= 3) or (len(posts) >= 2 and commenter_count >= 10)


def _distinct_commenters(
    post_ids: Sequence[str], signal_by_id: Mapping[str, PostSignal]
) -> set[str]:
    commenters: set[str] = set()
    for post_id in post_ids:
        signal = signal_by_id[post_id]
        op_author = signal.post.author.casefold() if signal.post.author else None
        commenters.update(
            author.casefold()
            for author in signal.comment_authors
            if author.strip() and author.casefold() != op_author
        )
    return commenters


def _resolve_node_executable(
    explicit: str | Path | None, environment: Mapping[str, str] | None
) -> Path:
    configured_environment = os.environ if environment is None else environment
    candidates: list[str | Path | None] = [
        explicit,
        configured_environment.get("RADAR_NODE_EXE"),
        shutil.which("node"),
        Path.cwd() / ".local" / "artifact-runtime" / "node.exe",
        Path.cwd() / ".local" / "artifact-runtime" / "bin" / "node.exe",
    ]
    for candidate in candidates:
        if candidate:
            path = Path(candidate)
            if path.is_file():
                return path
    raise RuntimeError(
        "Node.js executable not found. Pass node_executable, set RADAR_NODE_EXE, add node to PATH, or configure the project runtime."
    )


def _trend(formal: bool, current_rate: float, baseline_rate: float) -> str:
    if formal and current_rate > 0 and baseline_rate == 0:
        return "new"
    if baseline_rate == 0:
        return "stable"
    change = (current_rate - baseline_rate) / baseline_rate
    if change >= 0.5:
        return "rising"
    if change < -0.25:
        return "falling"
    return "stable"


def _apply_heat_scores(topics: list[dict[str, Any]]) -> None:
    if not topics:
        return
    metrics = {
        "posts": [float(topic["post_count"]) for topic in topics],
        "authors": [float(topic["author_count"]) for topic in topics],
        "comments": [float(topic["commenter_count"]) for topic in topics],
        "upvotes": [log1p(float(topic["upvote_count"])) for topic in topics],
        "recency_growth": [
            float(topic["current_daily_rate"]) / max(float(topic["baseline_daily_rate"]), 1 / BASELINE_DAYS)
            for topic in topics
        ],
    }
    maxima = {name: max(values) for name, values in metrics.items()}
    weights = {"posts": 0.30, "authors": 0.20, "comments": 0.20, "upvotes": 0.15, "recency_growth": 0.15}
    for index, topic in enumerate(topics):
        score = sum(
            weights[name] * (metrics[name][index] / maxima[name] if maxima[name] else 0.0)
            for name in weights
        )
        topic["heat_score"] = round(score * 100, 2)


def _excluded(canonical_key: str, reason: str) -> dict[str, str]:
    return {"canonical_key": canonical_key, "reason": reason}


def _is_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
