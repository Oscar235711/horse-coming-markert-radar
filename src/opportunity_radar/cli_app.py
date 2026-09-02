"""Task 4 application services for CLI orchestration and governance."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import date, timedelta
from datetime import UTC, datetime
from hashlib import sha256
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import Event, RLock
import time
from typing import Any

import yaml

from .config import load_community_catalog, load_config, load_diesel_domain_config, write_community_catalog
from .collector import CollectionCancelled, CollectionFailure, OpenCliCollector, ThreadDocument
from .codex_analysis import CodexAnalysisClient, CodexTopicConsolidator, ChunkedCodexTopicConsolidator
from .deepseek import (
    DEFAULT_BASE_URL,
    FLASH_MODEL,
    PRO_MODEL,
    DeepSeekClient,
    DeepSeekError,
    EvidenceClaim,
    HttpResponse,
    PostAnalysis,
    TopicCandidate,
    AnalysisField,
)
from .evidence import apply_diesel_evidence_gate, classify_diesel_evidence
from .models import CollectionScope, Community, CommunityCatalog, RadarConfig, RunManifest
from .storage import TopicRegistry, create_run_paths, read_manifest, write_keyword_library, write_manifest
from .keywords import build_topic_keyword_library
from .library import active_communities, active_keywords, update_project_library
from .metrics import build_report_metrics
from .topics import (
    EvidenceBackedClaim,
    ProTopicProposal,
    TopicAggregationResult,
    TopicAggregator,
    TopicEvidence,
    TopicExportArtifacts,
    build_community_library,
    export_topic_analysis,
)
from .report import render_html
from .voc_analysis import synthesize_topic_voc
from .query_planner import build_research_brief


ToolRunner = Callable[[tuple[str, ...]], str]
FlashClient = Any
Exporter = Callable[[Path, Mapping[str, Any], tuple[str, ...]], TopicExportArtifacts]
Clock = Callable[[], datetime]


class RadarCliApp:
    """High-level application service used by the Python CLI and PowerShell wrapper."""

    def __init__(
        self,
        *,
        runs_root: str | Path | None = None,
        config_versions_root: str | Path | None = None,
        library_root: str | Path | None = None,
        environment: Mapping[str, str] | None = None,
        tool_runner: ToolRunner | None = None,
        collector: OpenCliCollector | None = None,
        flash_client: FlashClient | None = None,
        pro_consolidator: Any | None = None,
        codex_client: Any | None = None,
        exporter: Exporter | None = None,
        now: Clock | None = None,
    ) -> None:
        self._environment = dict(environment if environment is not None else os.environ)
        self._repo_root = Path(__file__).resolve().parents[2]
        self._runs_root = self._resolve_root(
            runs_root,
            env_name="RADAR_RUNS_ROOT",
            default_relative=".local/runs",
        )
        self._config_versions_root = self._resolve_root(
            config_versions_root,
            env_name="RADAR_COMMUNITY_VERSIONS_ROOT",
            default_relative="configs/generated",
        )
        library_candidate = library_root
        if library_candidate is None and "RADAR_LIBRARY_ROOT" not in self._environment and runs_root is not None:
            library_candidate = Path(runs_root).parent / "library"
        self._library_root = self._resolve_root(
            library_candidate,
            env_name="RADAR_LIBRARY_ROOT",
            default_relative="library",
        )
        self._tool_runner = tool_runner or self._default_tool_runner
        self._has_custom_tool_runner = tool_runner is not None
        self._has_custom_exporter = exporter is not None
        self._collector = collector or OpenCliCollector(
            runner=lambda arguments: self._tool_runner(self._rewrite_opencli(arguments))
        )
        self._flash_client = flash_client or DeepSeekClient(
            transport=self._http_transport,
            environment=self._deepseek_environment(),
            base_url=self._deepseek_base_url(),
        )
        self._pro_consolidator = pro_consolidator or DeepSeekTopicConsolidator(
            client=DeepSeekClient(
                transport=self._http_transport,
                environment=self._deepseek_environment(),
                base_url=self._deepseek_base_url(),
            ),
            model=self._deepseek_pro_model(),
        )
        self._has_custom_codex_client = codex_client is not None
        self._codex_client = codex_client or CodexAnalysisClient(
            workspace=self._repo_root,
            schema_root=self._repo_root / "schemas",
            executable=self._find_executable("RADAR_CODEX_EXE", "codex"),
        )
        try:
            configured_concurrency = int(self._environment.get("RADAR_CODEX_CONCURRENCY", "2"))
        except (TypeError, ValueError):
            configured_concurrency = 2
        # Keep injected test doubles deterministic; production Codex calls can
        # run two independent CLI processes at once to avoid one-call-at-a-time
        # startup overhead. Set RADAR_CODEX_CONCURRENCY=1 to disable this.
        self._codex_concurrency = max(1, configured_concurrency) if not self._has_custom_codex_client else 1
        self._exporter = exporter or self._default_exporter
        self._now = now or (lambda: datetime.now(UTC))
        self._flash_rule_fallback_used = False
        self._cancel_lock = RLock()
        self._cancel_events: dict[str, Event] = {}
        self._active_run_id: str | None = None
        self._active_processes: dict[str, subprocess.Popen[str]] = {}

    @property
    def runs_root(self) -> Path:
        """Expose the local run directory to the localhost task server."""
        return self._runs_root

    def doctor(self) -> dict[str, Any]:
        """Report local readiness without persisting any secrets."""
        warnings: list[str] = []
        checks: dict[str, Any] = {
            "python": {
                "status": "ok",
                "version": ".".join(str(part) for part in os.sys.version_info[:3]),
                "executable": os.sys.executable,
            },
            "dependencies": {"status": "ok", "modules": self._dependency_status()},
            "paths": {
                "status": "ok",
                "runs_root": str(self._runs_root),
                "config_versions_root": str(self._config_versions_root),
                "library_root": str(self._library_root),
            },
        }
        self._runs_root.mkdir(parents=True, exist_ok=True)
        self._config_versions_root.mkdir(parents=True, exist_ok=True)
        self._library_root.mkdir(parents=True, exist_ok=True)

        tool_paths = {
            "agent_reach": self._find_executable("RADAR_AGENT_REACH_EXE", "agent-reach"),
            "opencli": self._find_executable("RADAR_OPENCLI_EXE", "opencli"),
            "node": self._find_executable("RADAR_NODE_EXE", "node"),
            "codex": self._find_executable("RADAR_CODEX_EXE", "codex"),
        }
        checks["tools"] = {
            name: {"status": "ok" if path else "warning", "path": str(path) if path else ""}
            for name, path in tool_paths.items()
        }
        plugin_source = self._repo_root / "opencli-plugin" / "opportunity-reddit"
        plugin_install = Path.home() / ".opencli" / "plugins" / "opportunity-reddit"
        checks["opencli_range_plugin"] = {
            "status": "ok" if plugin_install.is_dir() else "warning",
            "source": str(plugin_source),
            "installed_path": str(plugin_install),
        }
        if not plugin_install.is_dir():
            warnings.append("未安装项目的OpenCLI分页插件；请运行 scripts/install-opencli-plugin.ps1。")

        catalog = self._approved_catalog()
        checks["reddit"] = self._reddit_checks(catalog.communities)
        if checks["reddit"]["status"] != "ok":
            warnings.append("Reddit 采集环境未完全就绪：请检查 OpenCLI 登录态和社区访问。")

        checks["codex"] = {
            "status": "ok" if tool_paths["codex"] else "warning",
            "path": str(tool_paths["codex"]) if tool_paths["codex"] else "",
            "mode": "ephemeral/read-only",
        }
        if not tool_paths["codex"]:
            warnings.append("未找到 Codex CLI；默认分析流程需要本机已登录的 codex 命令。")

        deepseek = {
            "status": "configured" if bool(self._environment.get("DEEPSEEK_API_KEY")) else "optional",
            "base_url": self._deepseek_base_url(),
            "flash_model": self._deepseek_flash_model(),
            "pro_model": self._deepseek_pro_model(),
            "has_key": bool(self._environment.get("DEEPSEEK_API_KEY")),
            "required": False,
        }
        checks["deepseek"] = deepseek

        checks["excel"] = {
            "status": "ok" if tool_paths["node"] else "warning",
            "node_executable": str(tool_paths["node"]) if tool_paths["node"] else "",
            "builder_script": str(self._repo_root / "scripts" / "build_topic_workbook.mjs"),
        }
        if checks["excel"]["status"] != "ok":
            warnings.append("未找到 Node.js；`export` 生成 XLSX 前请设置 RADAR_NODE_EXE 或把 node 加入 PATH。")

        status = "ok" if not warnings else "warning"
        return {"status": status, "warnings": warnings, "checks": checks}

    def run(
        self,
        config_path: str | Path,
        *,
        run_id: str | None = None,
        scope: CollectionScope | None = None,
        analysis_engine: str = "legacy",
        selected_communities: Sequence[str] = (),
        selected_keywords: Sequence[str] = (),
        research_question: str = "",
    ) -> dict[str, Any]:
        """Start a new run and persist resumable state under one run directory."""
        resolved_config = self._resolve_path(config_path)
        if analysis_engine not in {"codex", "rules", "deepseek", "legacy"}:
            raise ValueError("analysis_engine must be codex, rules, deepseek, or legacy")
        config = load_config(resolved_config)
        config = self._select_communities(config, selected_communities)
        active_catalog_path = self._resolve_catalog_path(resolved_config)
        run_id = run_id or self._generate_run_id()
        run_dir = self._runs_root / run_id
        if run_dir.exists():
            raise ValueError(f"run_id already exists: {run_id}")
        paths = create_run_paths(self._runs_root, run_id)
        snapshot_text = self._config_snapshot_text(resolved_config)
        paths.config_snapshot_path.write_text(snapshot_text, encoding="utf-8")
        manifest = RunManifest(
            run_id=run_id,
            started_at=self._now(),
            config_sha256=sha256(snapshot_text.encode("utf-8")).hexdigest(),
            status="running",
            completed_stages=("configured",),
        )
        write_manifest(paths, manifest)
        state = self._base_state(run_id, resolved_config, active_catalog_path, config)
        state["analysis_engine"] = analysis_engine
        normalized_question = " ".join(str(research_question or "").split()).strip()
        if normalized_question:
            brief = build_research_brief(normalized_question, seed_terms=tuple(selected_keywords))
            if analysis_engine == "deepseek" and self._environment.get("DEEPSEEK_API_KEY", "").strip():
                try:
                    planned = self._flash_client.plan_research(
                        brief.question,
                        seed_terms=brief.query_terms,
                        model=self._deepseek_flash_model(),
                    )
                    expanded_terms = tuple(dict.fromkeys((
                        *brief.query_terms,
                        *tuple(str(item).strip() for item in planned.get("query_terms", ()) if str(item).strip()),
                    )))
                    brief = replace(brief, query_terms=expanded_terms, source="deepseek")
                except Exception:
                    # The deterministic brief keeps a run usable when the
                    # gateway is temporarily unavailable; the actual post
                    # analysis still reports the model error if it recurs.
                    pass
            state["research_question"] = brief.question
            state["research_brief"] = brief.as_dict()
            selected_keywords = brief.query_terms
        elif "research_question" not in state:
            state["research_question"] = ""
        state["selected_communities"] = [community.name for community in config.communities]
        state["selected_keywords"] = [str(item).strip() for item in selected_keywords if str(item).strip()]
        state["collection_scope"] = self._scope_to_dict(scope)
        state["completed_stages"] = ["configured"]
        state["progress"] = {
            "stage": "configured",
            "completed": 0,
            "total": 1,
            "message": "任务已创建，准备启动采集。",
        }
        self._write_state(paths.state_path, state)
        self._begin_run_context(run_id)
        try:
            return self._continue_run(
                paths, config, state, scope=scope, analysis_engine=analysis_engine,
                selected_keywords=selected_keywords,
            )
        finally:
            self._end_run_context(run_id)

    def resume(self, run_id: str) -> dict[str, Any]:
        """Continue a previously incomplete run from its saved checkpoints."""
        paths = create_run_paths(self._runs_root, run_id)
        state = self._read_state(paths.state_path)
        # A resumed run is active immediately. Persist this before any
        # collection or model call so the dashboard never shows a stale
        # ``completed`` badge while work is still in progress.
        state["status"] = "running"
        state["stage"] = "resuming"
        self._write_state(paths.state_path, state)
        config = load_config(paths.config_snapshot_path)
        config = self._select_communities(config, tuple(state.get("selected_communities", ())))
        scope = self._scope_from_dict(state.get("collection_scope"))
        self._begin_run_context(run_id)
        try:
            return self._continue_run(
                paths,
                config,
                state,
                scope=scope,
                analysis_engine=str(state.get("analysis_engine", "codex")),
                selected_keywords=tuple(str(item) for item in state.get("selected_keywords", ()) if str(item).strip()),
            )
        finally:
            self._end_run_context(run_id)

    def request_cancel(self, run_id: str) -> None:
        """Signal cancellation and terminate the active OpenCLI process tree."""
        with self._cancel_lock:
            self._cancel_events.setdefault(run_id, Event()).set()
            process = self._active_processes.get(run_id)
        if process is not None and process.poll() is None:
            self._terminate_process_tree(process)

    def _begin_run_context(self, run_id: str) -> None:
        with self._cancel_lock:
            self._active_run_id = run_id
            self._cancel_events.setdefault(run_id, Event()).clear()

    def _end_run_context(self, run_id: str) -> None:
        with self._cancel_lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            self._active_processes.pop(run_id, None)

    def _check_cancelled(self, run_id: str | None = None) -> None:
        key = run_id or self._active_run_id
        if not key:
            return
        with self._cancel_lock:
            event = self._cancel_events.get(key)
            cancelled = event is not None and event.is_set()
        if cancelled:
            raise CollectionCancelled("任务已取消")

    def status(self, run_id: str) -> dict[str, Any]:
        """Return the secret-free saved state for one run."""
        paths = create_run_paths(self._runs_root, run_id)
        state = self._read_state(paths.state_path)
        manifest = asdict(read_manifest(paths))
        manifest["started_at"] = manifest["started_at"].isoformat()
        state["manifest"] = manifest
        return state

    def export(self, run_id: str, *, formats: Sequence[str]) -> dict[str, Any]:
        """Rebuild JSON/XLSX artifacts from the canonical saved analysis JSON."""
        requested_formats = self._validate_export_formats(formats)
        paths = create_run_paths(self._runs_root, run_id)
        analysis_path = paths.artifacts_dir / "analysis.json"
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        exported = (
            self._write_json_exports(paths.artifacts_dir, analysis)
            if requested_formats == ("json",)
            else self._invoke_exporter(paths.artifacts_dir, analysis, requested_formats)
        )
        state = self._read_state(paths.state_path)
        state["artifacts"] = self._artifact_map(exported, requested_formats)
        state["export_formats"] = list(requested_formats)
        state["stage"] = "exported"
        state["status"] = "completed"
        if "exported" not in state["completed_stages"]:
            state["completed_stages"].append("exported")
        self._write_state(paths.state_path, state)
        manifest = read_manifest(paths)
        write_manifest(
            paths,
            RunManifest(
                run_id=manifest.run_id,
                started_at=manifest.started_at,
                config_sha256=manifest.config_sha256,
                status="completed",
                completed_stages=tuple(state["completed_stages"]),
            ),
        )
        return {
            "run_id": run_id,
            "status": "completed",
            "formats": list(requested_formats),
            "artifacts": state["artifacts"],
        }

    def communities_suggest(self, run_id: str) -> dict[str, Any]:
        """Produce evidence-backed candidate community-term suggestions from one run."""
        paths = create_run_paths(self._runs_root, run_id)
        state = self._read_state(paths.state_path)
        analysis = json.loads((paths.artifacts_dir / "analysis.json").read_text(encoding="utf-8"))
        catalog = load_community_catalog(state["active_version_path"])
        suggestions = self._build_suggestions(run_id, analysis, catalog, state["active_version_path"])
        suggestion_path = paths.suggestions_dir / "community_suggestions.json"
        suggestion_path.write_text(
            json.dumps(suggestions, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        state["artifacts"]["suggestions_json"] = str(suggestion_path)
        self._write_state(paths.state_path, state)
        return {
            "run_id": run_id,
            "suggestion_path": str(suggestion_path),
            "suggestion_count": len(suggestions["suggestions"]),
        }

    def communities_approve(self, suggestion_path: str | Path, *, suggestion_id: str) -> dict[str, Any]:
        """Validate and write a new community catalog version without switching the active file."""
        resolved_path = self._resolve_path(suggestion_path)
        document = json.loads(resolved_path.read_text(encoding="utf-8"))
        suggestions = document.get("suggestions", [])
        suggestion = next(
            (item for item in suggestions if isinstance(item, Mapping) and item.get("suggestion_id") == suggestion_id),
            None,
        )
        if suggestion is None:
            raise ValueError(f"suggestion_id not found: {suggestion_id}")
        active_version_path = Path(str(document["active_version_path"]))
        catalog = load_community_catalog(active_version_path)
        updated = self._apply_suggestion(catalog, suggestion)
        self._config_versions_root.mkdir(parents=True, exist_ok=True)
        new_version_path = self._config_versions_root / self._next_catalog_filename(active_version_path.name)
        write_community_catalog(new_version_path, updated)
        return {
            "status": "approved",
            "suggestion_id": suggestion_id,
            "active_version_path": str(active_version_path),
            "new_version_path": str(new_version_path),
            "new_version": updated.version,
        }

    def keywords_suggest(self, run_id: str) -> dict[str, Any]:
        """Write an auditable review queue for newly observed topic keywords."""
        paths = create_run_paths(self._runs_root, run_id)
        state = self._read_state(paths.state_path)
        analysis = json.loads((paths.artifacts_dir / "analysis.json").read_text(encoding="utf-8"))
        library = analysis.get("keyword_library", {})
        candidates = library.get("candidates", []) if isinstance(library, Mapping) else []
        suggestions = []
        for index, item in enumerate(candidates, start=1):
            if not isinstance(item, Mapping):
                continue
            status = str(item.get("status", "candidate_review")).casefold()
            if status in {"configured", "approved", "rejected"}:
                continue
            term = str(item.get("term_en", "")).strip()
            if not term:
                continue
            suggestions.append({
                "suggestion_id": f"keyword-{index}",
                "term_en": term,
                "term_zh": str(item.get("term_zh", "待翻译")),
                "community": str(item.get("community", "")),
                "topic_key": str(item.get("topic_key", "")),
                "score": item.get("score", 0),
                "post_count": item.get("post_count", 0),
                "author_count": item.get("author_count", 0),
                "source_post_ids": list(item.get("source_post_ids", []) or []),
                "source_comment_ids": list(item.get("source_comment_ids", []) or []),
                "status": "candidate_review",
            })
        suggestion_path = paths.suggestions_dir / "keyword_suggestions.json"
        suggestion_path.write_text(
            json.dumps({
                "run_id": run_id,
                "generated_at": self._now().isoformat(),
                "suggestions": suggestions,
            }, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        state.setdefault("artifacts", {})["keyword_suggestions_json"] = str(suggestion_path)
        self._write_state(paths.state_path, state)
        return {"run_id": run_id, "suggestion_path": str(suggestion_path), "suggestion_count": len(suggestions)}

    def keywords_approve(self, suggestion_path: str | Path) -> dict[str, Any]:
        """Mark selected keyword suggestions approved in the project library.

        The command accepts the file produced by ``keywords suggest``.  To
        avoid accidental bulk changes, only entries explicitly listed in an
        optional top-level ``approved`` array are promoted; when that array is
        absent, the file's ``suggestions`` are treated as the user's explicit
        approval input.
        """
        resolved_path = self._resolve_path(suggestion_path)
        document = json.loads(resolved_path.read_text(encoding="utf-8"))
        raw_items = document.get("approved", document.get("suggestions", []))
        if not isinstance(raw_items, list):
            raise ValueError("keyword approval file must contain an approved or suggestions array")
        selected = {
            (str(item.get("community", "")).casefold(), str(item.get("term_en", item.get("term", ""))).strip().casefold())
            for item in raw_items if isinstance(item, Mapping) and str(item.get("term_en", item.get("term", ""))).strip()
        }
        library_path = self._library_root / "keywords.json"
        library = json.loads(library_path.read_text(encoding="utf-8")) if library_path.exists() else {"version": "keyword-library.v1", "keywords": []}
        changed = 0
        for item in library.get("keywords", []) if isinstance(library.get("keywords"), list) else []:
            if not isinstance(item, Mapping):
                continue
            key = (str(item.get("community", "")).casefold(), str(item.get("term_en", item.get("normalized_term", ""))).strip().casefold())
            if key in selected:
                item["status"] = "approved"
                item["approved_at"] = self._now().isoformat()
                changed += 1
        library["updated_at"] = self._now().isoformat()
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.write_text(json.dumps(library, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return {"status": "approved", "approved_count": changed, "library_path": str(library_path)}

    def _continue_run(
        self,
        paths: Any,
        config: RadarConfig,
        state: dict[str, Any],
        *,
        scope: CollectionScope | None = None,
        analysis_engine: str = "legacy",
        selected_keywords: Sequence[str] = (),
    ) -> dict[str, Any]:
        activated_names = active_communities(self._library_root)
        # The cumulative library is discovery evidence, not crawl authority.
        # Only the communities selected for this run may drive subreddit
        # listing collection; keyword search can still discover posts across
        # Reddit without turning noisy mentions into thousands of extra reads.
        state["community_expansion"] = {
            "loaded_active_count": len(activated_names),
            "used_community_count": len(config.communities),
            "used_communities": [community.name for community in config.communities],
            "library_only_count": len({name.casefold() for name in activated_names} - {community.name.casefold() for community in config.communities}),
        }
        collect_arguments: dict[str, Any] = {
            "paths": paths,
            "as_of": self._now(),
            # Discover the whole selected surface first. The subsequent
            # keyword-search pass merges global results and then deep-reads
            # the deduplicated relevant set once.
            "deep_read": False if scope is not None and analysis_engine == "codex" else True,
            "shortlist_limit": config.shortlist_per_community,
        }
        if scope is not None:
            collect_arguments["scope"] = scope
        def report_collection_progress(update: Mapping[str, Any]) -> None:
            # Persist each meaningful collection milestone so the local task
            # page can show progress while OpenCLI is still fetching data.
            self._check_cancelled()
            state["stage"] = str(update.get("stage", "collecting"))
            state["progress"] = dict(update)
            self._write_state(paths.state_path, state)

        if "progress" in inspect.signature(self._collector.collect).parameters:
            collect_arguments["progress"] = report_collection_progress
        # Once the collection stage has been persisted, resume from its raw
        # files instead of reopening Chrome. This is essential for long
        # analysis jobs: a browser interruption must not overwrite good
        # evidence with an empty collection result.
        completed_stages = state.get("completed_stages", ())
        raw_listing_exists = any(paths.raw_listings_dir.glob("*.json"))
        if "collected" in completed_stages and raw_listing_exists and hasattr(self._collector, "load_from_raw"):
            raw_arguments = {
                "paths": paths,
                "as_of": self._now(),
                "shortlist_limit": config.shortlist_per_community,
            }
            if scope is not None:
                raw_arguments["scope"] = scope
            collection = self._collector.load_from_raw(config.communities, **raw_arguments)
        else:
            self._check_cancelled()
            collection = self._collector.collect(config.communities, **collect_arguments)

        self._check_cancelled()

        # The four configured subreddits are seed surfaces, not the market
        # boundary.  Every dated run also executes the persistent keyword
        # library across Reddit and deep-reads each newly discovered post in
        # complete mode.  This happens before the evidence gate so searched
        # posts follow the exact same VOC and citation contract as seed posts.
        domain = load_diesel_domain_config(paths.config_snapshot_path)
        library_terms = active_keywords(self._library_root)
        requested_terms = tuple(
            dict.fromkeys(" ".join(str(term).split()) for term in selected_keywords if str(term).strip())
        )
        # An empty selection means “use the current active library”.  When the
        # web UI sends a selection, keep the run auditable and do not silently
        # add unrelated terms from the default dictionary.
        expansion_terms = requested_terms or tuple(dict.fromkeys((*self._search_terms(domain), *library_terms)))
        if scope is not None and domain.keyword_search.enabled and expansion_terms:
            expansion = self._collector.collect_round_two(
                expansion_terms,
                paths=paths,
                as_of=self._now(),
                existing_candidates=collection.candidates,
                existing_deep_reads=collection.deep_reads,
                max_posts_per_term=domain.keyword_search.max_posts_per_keyword,
                max_terms=domain.keyword_search.max_candidate_keywords,
                scope=scope,
                deep_read=True,
                progress=report_collection_progress,
                post_filter=lambda item: self._search_post_relevant(item, config, domain),
                allowed_communities=(
                    None if state.get("research_question") else tuple(community.name for community in config.communities)
                ),
            )
            collection = replace(
                collection,
                candidates=expansion.candidates,
                deep_reads=expansion.deep_reads,
                failures=tuple((*collection.failures, *expansion.failures)),
            )
            state["expansion"] = {
                "loaded_keyword_count": len(library_terms),
                "used_keyword_count": len(expansion.selected_terms),
                "used_keywords": list(expansion.selected_terms),
                "initial_query_terms": list(requested_terms),
                "selected_by_user": bool(requested_terms),
                "discovered_community_count": len({
                    item.post.subreddit.casefold() for item in expansion.candidates
                }),
            }
        if not collection.candidates and not collection.deep_reads and collection.failures:
            state["counts"]["failure_count"] = len(collection.failures)
            state["failures"] = [self._failure_to_dict(failure) for failure in collection.failures]
            state["status"] = "incomplete"
            state["stage"] = "collecting"
            state["progress"] = {
                "stage": "collecting",
                "completed": 0,
                "total": len(config.communities),
                "message": "采集未返回有效帖子，任务暂停等待重试。",
            }
            self._write_state(paths.state_path, state)
            return state
        state["counts"]["community_count"] = len(config.communities)
        state["counts"]["candidate_count"] = len(collection.candidates)
        state["counts"]["shortlist_count"] = len(collection.shortlisted)
        state["counts"]["deep_read_count"] = len(collection.deep_reads)
        state["completed_stages"] = self._merge_stages(state["completed_stages"], "configured", "collected")
        state["failures"] = [self._failure_to_dict(failure) for failure in collection.failures]
        state["coverage"] = {
            community: {
                **asdict(item),
                "requested_start": item.requested_start.isoformat(),
                "requested_end": item.requested_end.isoformat(),
                "actual_start": item.actual_start.isoformat() if item.actual_start else None,
                "actual_end": item.actual_end.isoformat() if item.actual_end else None,
            }
            for community, item in collection.coverage.items()
        }
        state["stage"] = "collected"
        state["progress"] = {
            "stage": "collected",
            "completed": len(collection.deep_reads),
            "total": len(collection.deep_reads),
            "message": "帖子列表和深读证据已采集，正在执行证据筛选。",
        }
        self._write_state(paths.state_path, state)

        eligible_threads, audit = self._gate_threads(collection.deep_reads, config, domain)
        audit_path = paths.artifacts_dir / "evidence_gate.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        state["artifacts"]["evidence_gate_json"] = str(audit_path)
        state["counts"]["eligible_post_count"] = len(eligible_threads)
        state["counts"]["excluded_post_count"] = len(collection.deep_reads) - len(eligible_threads)
        state["counts"]["comment_evidence_count"] = len(audit["comments"])
        state["stage"] = "post_analysis"
        state["progress"] = {
            "stage": "post_analysis",
            "completed": len(analyses_by_post := self._load_saved_analyses(paths)),
            "total": len(eligible_threads),
            "message": "正在从帖子和评论中提取场景、任务、痛点与方案。",
        }
        self._write_state(paths.state_path, state)

        flash_failures: list[CollectionFailure] = []
        pending_threads = [thread for thread in eligible_threads if thread.post.post_id not in analyses_by_post]

        def record_success(thread: ThreadDocument, analysis: PostAnalysis) -> None:
            analyses_by_post[thread.post.post_id] = analysis
            self._write_analysis_checkpoint(paths, thread.post.post_id, analysis)
            total = int(state.get("progress", {}).get("total", 0) or 0)
            state["progress"]["completed"] = min(
                total,
                len(analyses_by_post) + len(flash_failures),
            )
            self._write_state(paths.state_path, state)

        def record_failure(thread: ThreadDocument, error: Exception) -> None:
            failure = CollectionFailure(
                community=thread.post.subreddit,
                post_id=thread.post.post_id,
                stage="flash_extract",
                message=f"{type(error).__name__}: external operation failed",
            )
            flash_failures.append(failure)
            self._write_failed_analysis_checkpoint(paths, thread.post.post_id, failure.message)
            # A failed item is still processed for this attempt. Persist the
            # count so the dashboard cannot appear frozen below its total.
            total = int(state.get("progress", {}).get("total", 0) or 0)
            state["progress"]["completed"] = min(
                total,
                len(analyses_by_post) + len(flash_failures),
            )
            self._write_state(paths.state_path, state)

        def analyse_pending(targets: Sequence[ThreadDocument]) -> None:
            if analysis_engine == "codex" and self._codex_concurrency > 1 and targets:
                # Independent read-only Codex jobs remove repeated startup
                # latency without parallelising the authenticated browser.
                with ThreadPoolExecutor(max_workers=self._codex_concurrency) as executor:
                    futures = {
                        executor.submit(self._codex_client.extract_post, thread): thread
                        for thread in targets
                    }
                    for future in as_completed(futures):
                        thread = futures[future]
                        try:
                            record_success(thread, future.result())
                        except Exception as error:
                            record_failure(thread, error)
                return
            for thread in targets:
                try:
                    self._check_cancelled()
                    if analysis_engine == "codex":
                        analysis = self._codex_client.extract_post(thread)
                    elif analysis_engine == "rules":
                        analysis = _rule_extract_post(thread, domain)
                        self._flash_rule_fallback_used = True
                    elif analysis_engine == "deepseek":
                        if not self._environment.get("DEEPSEEK_API_KEY", "").strip():
                            raise DeepSeekError("DeepSeek 未配置。")
                        analysis = self._extract_flash(thread)
                    else:
                        if self._environment.get("DEEPSEEK_API_KEY", "").strip():
                            analysis = self._extract_flash(thread)
                        else:
                            raise DeepSeekError("DeepSeek 未配置，使用规则提取。")
                    record_success(thread, analysis)
                except Exception as error:
                    try:
                        allow_rule_fallback = analysis_engine == "legacy" and not self._environment.get("DEEPSEEK_API_KEY", "").strip()
                        analysis = _rule_extract_post(thread, domain) if allow_rule_fallback else None
                    except Exception:
                        analysis = None
                    if analysis is not None and (analysis.topics or analysis.claims):
                        self._flash_rule_fallback_used = True
                        record_success(thread, analysis)
                        continue
                    record_failure(thread, error)

        analyse_pending(pending_threads)

        # Close the discovery loop inside the same run. Model-discovered
        # English terms supported by at least two independent posts/authors
        # are searched immediately; the loop ends only when no new active term
        # remains. Existing query checkpoints prevent re-fetching old terms.
        if analysis_engine in {"codex", "deepseek"} and scope is not None and domain.keyword_search.enabled:
            used_terms = set(str(term).casefold() for term in state.get("expansion", {}).get("used_keywords", []))
            while True:
                discovered = self._analysis_keyword_terms(eligible_threads, analyses_by_post)
                new_terms = tuple(term for term in discovered if term.casefold() not in used_terms)
                if not new_terms:
                    break
                used_terms.update(term.casefold() for term in new_terms)
                expansion = self._collector.collect_round_two(
                    tuple((*state.get("expansion", {}).get("used_keywords", []), *new_terms)),
                    paths=paths,
                    as_of=self._now(),
                    existing_candidates=collection.candidates,
                    existing_deep_reads=collection.deep_reads,
                    max_posts_per_term=domain.keyword_search.max_posts_per_keyword,
                    max_terms=None,
                    scope=scope,
                    deep_read=True,
                    progress=report_collection_progress,
                    post_filter=lambda item: self._search_post_relevant(item, config, domain),
                    allowed_communities=(
                        None if state.get("research_question") else tuple(community.name for community in config.communities)
                    ),
                )
                prior_post_ids = {thread.post.post_id for thread in collection.deep_reads}
                collection = replace(
                    collection,
                    candidates=expansion.candidates,
                    deep_reads=expansion.deep_reads,
                    failures=tuple((*collection.failures, *expansion.failures)),
                )
                state.setdefault("expansion", {})["used_keywords"] = list(expansion.selected_terms)
                state["expansion"]["used_keyword_count"] = len(expansion.selected_terms)
                eligible_threads, audit = self._gate_threads(collection.deep_reads, config, domain)
                audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
                added_targets = [
                    thread for thread in eligible_threads
                    if thread.post.post_id not in analyses_by_post
                ]
                if not added_targets and not ({thread.post.post_id for thread in collection.deep_reads} - prior_post_ids):
                    break
                state["progress"] = {
                    "stage": "post_analysis",
                    "completed": len(analyses_by_post),
                    "total": len(eligible_threads),
                    "message": "正在分析自动扩展检索新增的帖子。",
                }
                analyse_pending(added_targets)

        state["counts"]["analyzed_posts"] = len(analyses_by_post)
        state["counts"]["failure_count"] = len(collection.failures) + len(flash_failures)
        state["failures"].extend(self._failure_to_dict(failure) for failure in flash_failures)
        # A failed post must not discard a run when other evidence was
        # successfully analysed.  Codex and DeepSeek runs both continue to
        # topic consolidation and report export while exposing failed posts in
        # the run's failure log.  If every model extraction failed, keep the
        # run resumable instead of fabricating an empty report; preserve the
        # legacy path's historical all-failure behavior for other engines.
        if flash_failures and (
            analysis_engine not in {"codex", "deepseek"} or not analyses_by_post
        ):
            state["status"] = "incomplete"
            state["stage"] = "flash_extract"
            self._write_state(paths.state_path, state)
            manifest = read_manifest(paths)
            write_manifest(
                paths,
                RunManifest(
                    run_id=manifest.run_id,
                    started_at=manifest.started_at,
                    config_sha256=manifest.config_sha256,
                    status="incomplete",
                    completed_stages=tuple(state["completed_stages"]),
                ),
            )
            return state

        topic_consolidator = (
            ChunkedCodexTopicConsolidator(client=self._codex_client, chunk_size=8)
            if analysis_engine == "codex" else self._pro_consolidator
        )
        state["stage"] = "topic_consolidation"
        state["progress"] = {
            "stage": "topic_consolidation",
            "completed": 0,
            "total": len(config.communities),
            "message": "正在社区内归并同类用户任务和问题，并复核证据。",
        }
        self._write_state(paths.state_path, state)
        analysis = self._aggregate_run(
            config,
            eligible_threads,
            analyses_by_post,
            paths=paths,
            pro_consolidator=topic_consolidator,
            model_mode=analysis_engine if analysis_engine != "legacy" else None,
        )
        if state.get("research_question"):
            analysis["research_question"] = state["research_question"]
            analysis["research_brief"] = state.get("research_brief", {})
            analysis["query_expansion"] = state.get("expansion", {})
        topic_failures = [
            item for item in analysis.get("topic_failures", [])
            if isinstance(item, Mapping)
        ]
        if topic_failures:
            state["failures"].extend(dict(item) for item in topic_failures)
            state["counts"]["failure_count"] = len(state["failures"])
        if analysis_engine == "deepseek" and topic_failures and not analysis.get("topics"):
            state["status"] = "incomplete"
            state["stage"] = "topic_consolidation"
            state["progress"] = {
                "stage": "topic_consolidation",
                "completed": 0,
                "total": len(config.communities),
                "message": "DeepSeek 话题归并未完成，已保留分析检查点，可直接续跑。",
            }
            self._write_state(paths.state_path, state)
            manifest = read_manifest(paths)
            write_manifest(
                paths,
                RunManifest(
                    run_id=manifest.run_id,
                    started_at=manifest.started_at,
                    config_sha256=manifest.config_sha256,
                    status="incomplete",
                    completed_stages=tuple(state["completed_stages"]),
                ),
            )
            return state
        analyzed_threads = tuple(
            thread for thread in eligible_threads if thread.post.post_id in analyses_by_post
        )
        report_metrics = build_report_metrics(
            communities=tuple(dict.fromkeys(
                thread.post.subreddit for thread in analyzed_threads
            )),
            collection=collection,
            analyzed_threads=analyzed_threads,
            topics=tuple(
                topic for topic in analysis.get("topics", []) if isinstance(topic, Mapping)
            ),
        )
        analysis["report_metrics"] = report_metrics
        analysis["research_scope"] = {
            "start_date": scope.start_date.isoformat() if scope else None,
            "end_date": scope.end_date.isoformat() if scope else None,
            "depth": scope.depth if scope else "legacy",
            "coverage": state.get("coverage", {}),
        }
        # Backward-compatible names are only a projection of the canonical
        # metrics object; HTML and Excel read report_metrics directly.
        analysis["crawl_counts"] = {
            "normalized_posts": report_metrics["scanned_post_count"],
            "saved_threads": report_metrics["deep_read_post_count"],
            "analyzed_posts": report_metrics["analyzed_post_count"],
            "saved_comments": report_metrics["collected_comment_count"],
        }
        # Keep a small, cumulative project library so each run improves the
        # community/topic/keyword index without copying raw post bodies into
        # the repository.
        library_status = update_project_library(
            self._library_root,
            analysis,
            run_id=paths.run_dir.name,
            posts=[thread.post for thread in eligible_threads],
            comments=[
                {
                    "post_id": thread.post.post_id,
                    "comment_id": comment.comment_id,
                    "body": comment.body,
                    "url": comment.url,
                    "author": comment.author,
                }
                for thread in eligible_threads for comment in thread.comments
            ],
            now=self._now(),
        )
        analysis["project_library"] = {
            "version": library_status.get("versions", {}),
            "counts": library_status.get("counts", {}),
            "root": "library",
        }
        exported = self._invoke_exporter(paths.artifacts_dir, analysis, ("json", "xlsx"))
        state["artifacts"] = self._artifact_map(exported, ("json", "xlsx"))
        report_path = render_html(analysis, paths.artifacts_dir / "report.html")
        state["artifacts"]["report_html"] = str(report_path)
        state["artifacts"]["community_topic_map_json"] = str(report_path.parent / "community_topic_map.json")
        state["artifacts"]["evidence_gate_json"] = str(audit_path)
        state["stage"] = "exported"
        state["status"] = "completed"
        state["completed_stages"] = self._merge_stages(
            state["completed_stages"], "configured", "collected", "flash_extract", "topic_consolidation", "exported"
        )
        state["counts"]["topic_count"] = len(analysis.get("topics", []))
        state["progress"] = {
            "stage": "exported",
            "completed": 1,
            "total": 1,
            "message": "分析、HTML 与 Excel 已生成。",
        }
        # Keep extraction failures visible after a successful partial run;
        # report generation must not erase them from the final counters.
        state["counts"]["failure_count"] = len(state.get("failures", []))
        self._write_state(paths.state_path, state)

        manifest = read_manifest(paths)
        write_manifest(
            paths,
            RunManifest(
                run_id=manifest.run_id,
                started_at=manifest.started_at,
                config_sha256=manifest.config_sha256,
                status="completed",
                completed_stages=tuple(state["completed_stages"]),
            ),
        )
        return state

    def _gate_threads(self, threads: Sequence[ThreadDocument], config: RadarConfig, domain: Any) -> tuple[tuple[ThreadDocument, ...], dict[str, Any]]:
        """Keep only relevant diesel posts for Flash while retaining every gate decision."""
        approved = tuple(community.name for community in config.communities)
        post_records = tuple(
            {
                "post_id": thread.post.post_id,
                "record_type": "post",
                "author": thread.post.author,
                "subreddit": thread.post.subreddit,
                "title": thread.post.title,
                "body": thread.post.body,
                "score": thread.post.score,
            }
            for thread in threads
        )
        post_gate = apply_diesel_evidence_gate(
            post_records,
            dictionaries=domain.dictionaries,
            exclusions=domain.exclusions,
            approved_communities=approved,
        )
        eligible_ids = {str(item.record["post_id"]) for item in post_gate.qualified}
        comment_records = tuple(
            {
                "post_id": thread.post.post_id,
                "comment_id": comment.comment_id,
                "record_type": "comment",
                "author": comment.author,
                "subreddit": thread.post.subreddit,
                "body": comment.body,
                "score": 0,
            }
            for thread in threads for comment in thread.comments
        )
        comment_gate = apply_diesel_evidence_gate(
            comment_records,
            dictionaries=domain.dictionaries,
            exclusions=domain.exclusions,
            approved_communities=approved,
        )
        audit = {
            "qualified_posts": [self._gate_entry(item) for item in post_gate.qualified],
            "excluded_posts": [self._gate_entry(item) for item in post_gate.excluded],
            "comments": [self._gate_entry(item) for item in (*comment_gate.qualified, *comment_gate.excluded)],
            "distribution": {"posts": dict(post_gate.distribution), "comments": dict(comment_gate.distribution)},
        }
        return tuple(thread for thread in threads if thread.post.post_id in eligible_ids), audit

    @staticmethod
    def _gate_entry(item: Any) -> dict[str, Any]:
        record = item.record
        quality = item.quality
        return {
            "post_id": str(record.get("post_id", "")),
            "comment_id": str(record.get("comment_id", "")),
            "record_type": str(record.get("record_type", "")),
            "evidence_role": quality.evidence_role,
            "claim_status": quality.claim_status,
            "quality_score": quality.quality_score,
            "quality_band": quality.quality_band,
            "opportunity_weight": quality.opportunity_weight,
            "eligible": quality.eligible,
            "hard_exclusion": quality.hard_exclusion,
            "reason_codes": list(quality.reason_codes),
        }

    def _extract_flash(self, thread: ThreadDocument) -> PostAnalysis:
        """Pass the configured Flash deployment when the injected client accepts it."""
        extract = self._flash_client.extract_post
        if "model" in inspect.signature(extract).parameters:
            return extract(thread, model=self._deepseek_flash_model())
        return extract(thread)

    @staticmethod
    def _search_terms(domain: Any) -> tuple[str, ...]:
        """Build broad but diesel-anchored seed queries for global Reddit search."""
        dictionaries = domain.dictionaries
        raw_terms = (
            *dictionaries.platforms,
            *dictionaries.products,
            *dictionaries.vehicle_terms,
            *dictionaries.slang,
        )
        terms: list[str] = []
        for raw in raw_terms:
            term = " ".join(str(raw).strip().split())
            if not term:
                continue
            if len(term.split()) == 1 and term.casefold() not in {"cummins", "duramax", "powerstroke"}:
                term = f"diesel {term}"
            if term.casefold() not in {item.casefold() for item in terms}:
                terms.append(term)
        # Intent queries collect problems and desired outcomes that a product
        # dictionary alone would miss. They remain discovery inputs only;
        # Codex, not these strings, creates the VOC analysis.
        for term in (
            "diesel truck problem", "diesel truck failure", "diesel truck towing",
            "diesel truck fitment", "diesel truck install", "diesel truck recommend",
            "diesel truck aftermarket", "diesel truck repair",
        ):
            if term.casefold() not in {item.casefold() for item in terms}:
                terms.append(term)
        return tuple(terms)

    @staticmethod
    def _analysis_keyword_terms(
        threads: Sequence[ThreadDocument], analyses_by_post: Mapping[str, PostAnalysis],
    ) -> tuple[str, ...]:
        """Promote model-discovered English terms with independent evidence."""
        support: dict[str, dict[str, set[str]]] = {}
        display: dict[str, str] = {}
        for thread in threads:
            analysis = analyses_by_post.get(thread.post.post_id)
            if analysis is None:
                continue
            fields = (*analysis.keyword_candidates, *analysis.topic_candidates, *analysis.products)
            for field in fields:
                term = " ".join(str(field.value or "").strip().split())
                if field.status == "unknown" or not field.evidence_ids or not term or term.casefold() == "unknown":
                    continue
                if len(term) > 80 or not re.search(r"[A-Za-z]", term) or re.search(r"[\u4e00-\u9fff]", term):
                    continue
                key = re.sub(r"\s+", " ", term.casefold().replace("-", " ")).strip()
                if len(key.split()) < 2:
                    continue
                bucket = support.setdefault(key, {"posts": set(), "authors": set(), "communities": set()})
                bucket["posts"].add(thread.post.post_id)
                if thread.post.author:
                    bucket["authors"].add(str(thread.post.author))
                bucket["communities"].add(thread.post.subreddit.casefold())
                display.setdefault(key, term)
        return tuple(
            display[key] for key, values in support.items()
            if len(values["posts"]) >= 2 and len(values["authors"]) >= 2
        )

    @staticmethod
    def _search_post_relevant(item: Any, config: RadarConfig, domain: Any) -> bool:
        """High-recall cleaning before expensive thread retrieval."""
        post = item.post
        quality = classify_diesel_evidence(
            {
                "post_id": post.post_id,
                "record_type": "post",
                "author": post.author,
                "subreddit": post.subreddit,
                "title": post.title,
                "body": post.body,
                "score": post.score,
            },
            dictionaries=domain.dictionaries,
            exclusions=domain.exclusions,
            approved_communities=tuple(community.name for community in config.communities),
        )
        return not quality.hard_exclusion and quality.evidence_role != "noise"

    def _aggregate_run(
        self,
        config: RadarConfig,
        threads: Sequence[ThreadDocument],
        analyses_by_post: Mapping[str, PostAnalysis],
        *,
        paths: Any | None = None,
        pro_consolidator: Any | None = None,
        model_mode: str | None = None,
    ) -> dict[str, Any]:
        registry = TopicRegistry(self._runs_root / ".topic-registry.json")
        combined_topics: list[dict[str, Any]] = []
        excluded_records: list[dict[str, str]] = []
        topic_failures: list[dict[str, str]] = []
        results: list[TopicAggregationResult] = []
        active_consolidator = pro_consolidator or self._pro_consolidator
        communities: list[Community] = list(config.communities)
        configured_keys = {community.name.casefold() for community in communities}
        for thread in threads:
            name = str(thread.post.subreddit or "").strip().removeprefix("r/")
            if name and name.casefold() not in configured_keys:
                communities.append(Community(
                    name=name,
                    category="keyword_discovered",
                    brand="跨社区柴油皮卡讨论",
                    status="observed",
                ))
                configured_keys.add(name.casefold())
        for community in communities:
            # Failed model extractions remain in the audit log, but cannot be
            # passed to the topic consolidator without a matching analysis.
            # Aggregate only the successfully analysed threads so one
            # transient DeepSeek failure does not crash the whole report.
            community_threads = tuple(
                thread
                for thread in threads
                if thread.post.subreddit.casefold() == community.name.casefold()
                and thread.post.post_id in analyses_by_post
            )
            community_analyses = tuple(analyses_by_post[thread.post.post_id] for thread in community_threads)
            if not community_threads:
                continue
            try:
                result = TopicAggregator(
                    pro=active_consolidator,
                    registry=registry,
                    as_of=self._now(),
                ).aggregate_threads(community.name, community_threads, community_analyses)
            except Exception as error:
                # A model timeout or malformed community response should not
                # discard topics already consolidated for other communities.
                # Keep the failure explicit so it can be retried from the run
                # state instead of silently producing an apparently complete
                # report.
                topic_failures.append({
                    "community": community.name,
                    "stage": "topic_consolidation",
                    "message": f"{type(error).__name__}: external operation failed",
                })
                continue
            results.append(result)
            combined_topics.extend(result.analysis.get("topics", []))
            excluded_records.extend(result.analysis.get("excluded_records", []))
        analyzed_threads = [thread for thread in threads if thread.post.post_id in analyses_by_post]
        all_analyses = [analyses_by_post[thread.post.post_id] for thread in analyzed_threads]
        comments = [
            {
                "post_id": thread.post.post_id,
                "comment_id": comment.comment_id,
                "body": comment.body,
                "url": comment.url,
                "author": comment.author,
            }
            for thread in analyzed_threads for comment in thread.comments
        ]
        community_library = build_community_library(
            [community for community in communities if any(
                thread.post.subreddit.casefold() == community.name.casefold() for thread in analyzed_threads
            )],
            combined_topics,
            config.community_catalog_version,
        )
        keyword_library = build_topic_keyword_library(
            [thread.post for thread in analyzed_threads], comments, all_analyses,
        )
        if paths is not None:
            write_keyword_library(paths, keyword_library)
        return {
            "analysis_version": "1.0",
            "generated_at": self._now().isoformat(),
            "communities": list(dict.fromkeys(thread.post.subreddit for thread in analyzed_threads)),
            "community_library": community_library,
            "keyword_library": keyword_library,
            "topics": combined_topics,
            "excluded_records": excluded_records,
            "topic_failures": topic_failures,
            "model_mode": model_mode or (
                "rule_based" if self._flash_rule_fallback_used or getattr(active_consolidator, "mode", "") == "rule_fallback"
                else getattr(active_consolidator, "mode", "injected_pro")
            ),
            "product_output_label": "opportunity hypothesis, not launch conclusion",
        }

    def _build_suggestions(
        self,
        run_id: str,
        analysis: Mapping[str, Any],
        catalog: CommunityCatalog,
        active_version_path: str,
    ) -> dict[str, Any]:
        known_slang = {
            community.name.casefold(): {term.casefold() for term in community.slang}
            for community in catalog.communities
        }
        suggestions: list[dict[str, Any]] = []
        for topic in analysis.get("topics", []):
            if not isinstance(topic, Mapping):
                continue
            community = str(topic.get("community", ""))
            label = str(topic.get("label_en", "")).strip().lower()
            if not community or not label or label in known_slang.get(community.casefold(), set()):
                continue
            evidence = topic.get("evidence", [])
            suggestions.append(
                {
                    "suggestion_id": f"{community.casefold()}-slang-{len(suggestions) + 1}",
                    "kind": "slang",
                    "community": community,
                    "value": label,
                    "reason": "Recurring approved-community topic label missing from the current slang list.",
                    "evidence": list(evidence[:3]),
                }
            )
        return {
            "run_id": run_id,
            "generated_at": self._now().isoformat(),
            "active_version_path": str(active_version_path),
            "suggestions": suggestions,
        }

    def _apply_suggestion(self, catalog: CommunityCatalog, suggestion: Mapping[str, Any]) -> CommunityCatalog:
        community_name = str(suggestion.get("community", ""))
        kind = str(suggestion.get("kind", ""))
        value = str(suggestion.get("value", "")).strip()
        if not community_name or not value:
            raise ValueError("suggestion must include community and value")
        updated_communities: list[Community] = []
        for community in catalog.communities:
            if community.name.casefold() != community_name.casefold():
                updated_communities.append(community)
                continue
            if kind == "slang":
                updated_communities.append(
                    Community(
                        name=community.name,
                        aliases=community.aliases,
                        include=community.include,
                        exclude=community.exclude,
                        category=community.category,
                        brand=community.brand,
                        slang=tuple(dict.fromkeys((*community.slang, value))),
                    )
                )
            else:
                raise ValueError(f"unsupported suggestion kind: {kind}")
        return CommunityCatalog(
            version=self._next_catalog_version(catalog.version),
            communities=tuple(updated_communities),
        )

    def _approved_catalog(self) -> CommunityCatalog:
        default_catalog = self._repo_root / "configs" / "community_catalog.v1.yaml"
        return load_community_catalog(default_catalog)

    def _resolve_catalog_path(self, config_path: Path) -> Path:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, Mapping):
            configured = raw.get("community_catalog_path")
            if isinstance(configured, str) and configured.strip():
                resolved = Path(configured.strip())
                if not resolved.is_absolute():
                    resolved = config_path.parent / resolved
                return resolved.resolve()
        return (self._repo_root / "configs" / "community_catalog.v1.yaml").resolve()

    def _dependency_status(self) -> dict[str, str]:
        modules = ("yaml",)
        result: dict[str, str] = {}
        for module_name in modules:
            try:
                importlib.import_module(module_name)
                result[module_name] = "ok"
            except ImportError:
                result[module_name] = "missing"
        return result

    def _reddit_checks(self, communities: Sequence[Community]) -> dict[str, Any]:
        report = {"status": "ok", "whoami": {"status": "ok"}, "seed_reads": []}
        try:
            whoami = json.loads(self._tool_runner(self._rewrite_opencli(("opencli", "reddit", "whoami", "-f", "json", *_opencli_session_flags()))))
            # OpenCLI versions return either a mapping or a table-like list
            # of ``field``/``value`` rows.  Both are valid authenticated
            # sessions; do not turn the latter into a false warning.
            username = ""
            if isinstance(whoami, Mapping):
                username = str(whoami.get("username", ""))
            elif isinstance(whoami, list):
                fields = {
                    str(row.get("field", "")).casefold(): str(row.get("value", ""))
                    for row in whoami
                    if isinstance(row, Mapping)
                }
                username = fields.get("username", "")
            report["whoami"] = {"status": "ok", "username": username}
        except Exception as error:
            report["status"] = "warning"
            report["whoami"] = {"status": "warning", "message": f"{type(error).__name__}: external operation failed"}
        end_date = self._now().date()
        start_date = end_date - timedelta(days=7)
        for community in communities[:4]:
            try:
                result = self._tool_runner(
                    self._rewrite_opencli(
                        (
                            "opencli",
                            "opportunity-reddit",
                            "range",
                            community.name,
                            "--start-date",
                            start_date.isoformat(),
                            "--end-date",
                            end_date.isoformat(),
                            "--limit",
                            "1",
                            "-f",
                            "json",
                            *_opencli_session_flags(),
                        )
                    )
                )
                payload = json.loads(result)
                if not isinstance(payload, list):
                    raise ValueError("range probe did not return a JSON list")
                report["seed_reads"].append({"community": community.name, "status": "ok"})
            except Exception as error:
                report["status"] = "warning"
                report["seed_reads"].append(
                    {
                        "community": community.name,
                        "status": "warning",
                        "message": f"{type(error).__name__}: external operation failed",
                    }
                )
        return report

    def _default_exporter(self, output_dir: Path, analysis: Mapping[str, Any], formats: tuple[str, ...]) -> TopicExportArtifacts:
        return export_topic_analysis(
            analysis,
            output_dir=output_dir,
            formats=formats,
            node_executable=self._find_executable("RADAR_NODE_EXE", "node"),
            environment=self._environment,
        )

    def _default_tool_runner(self, arguments: tuple[str, ...]) -> str:
        try:
            timeout_seconds = float(self._environment.get("RADAR_OPENCLI_TIMEOUT_SECONDS", "60"))
        except (TypeError, ValueError):
            timeout_seconds = 60.0
        run_id = self._active_run_id
        self._check_cancelled(run_id)
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._repo_root,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        if run_id:
            with self._cancel_lock:
                self._active_processes[run_id] = process
        deadline = time.monotonic() + max(5.0, timeout_seconds)
        try:
            while True:
                self._check_cancelled(run_id)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_process_tree(process)
                    raise subprocess.TimeoutExpired(arguments, max(5.0, timeout_seconds))
                try:
                    stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, arguments, output=stdout, stderr=stderr)
            return stdout
        except CollectionCancelled:
            self._terminate_process_tree(process)
            raise
        finally:
            if run_id:
                with self._cancel_lock:
                    if self._active_processes.get(run_id) is process:
                        self._active_processes.pop(run_id, None)

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        else:
            process.kill()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()

    def _http_transport(self, method: str, url: str, headers: dict[str, str], payload: dict[str, Any]) -> HttpResponse:
        import urllib.request
        import urllib.error

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in headers.items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return HttpResponse(response.status, response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read().decode("utf-8", errors="replace"))

    def _deepseek_environment(self) -> Mapping[str, str]:
        return {
            "DEEPSEEK_API_KEY": self._environment.get("DEEPSEEK_API_KEY", ""),
        }

    def _deepseek_base_url(self) -> str:
        return self._environment.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)

    def _deepseek_flash_model(self) -> str:
        return self._environment.get("DEEPSEEK_FLASH_MODEL", FLASH_MODEL)

    def _deepseek_pro_model(self) -> str:
        return self._environment.get("DEEPSEEK_PRO_MODEL", PRO_MODEL)

    def _generate_run_id(self) -> str:
        return self._now().strftime("%Y%m%dT%H%M%SZ")

    def _select_communities(
        self, config: RadarConfig, selected: Sequence[str]
    ) -> RadarConfig:
        if not selected:
            return config
        requested = {name.casefold() for name in selected}
        available = {community.name.casefold(): community for community in config.communities}
        unknown = sorted(requested - available.keys())
        if unknown:
            raise ValueError(f"unknown communities: {', '.join(unknown)}")
        communities = tuple(
            community for community in config.communities
            if community.name.casefold() in requested
        )
        return replace(config, communities=communities)

    def _scope_to_dict(self, scope: CollectionScope | None) -> dict[str, str] | None:
        if scope is None:
            return None
        return {
            "start_date": scope.start_date.isoformat(),
            "end_date": scope.end_date.isoformat(),
            "depth": scope.depth,
        }

    def _scope_from_dict(self, document: object) -> CollectionScope | None:
        if not isinstance(document, Mapping):
            return None
        return CollectionScope(
            start_date=date.fromisoformat(str(document["start_date"])),
            end_date=date.fromisoformat(str(document["end_date"])),
            depth=str(document.get("depth", "standard")),
        )

    def _base_state(
        self, run_id: str, config_path: Path, active_catalog_path: Path, config: RadarConfig
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "status": "running",
            "stage": "configured",
            "config_path": str(config_path),
            "active_version_path": str(active_catalog_path),
            "community_catalog_version": config.community_catalog_version,
            "completed_stages": [],
            "counts": {
                "community_count": len(config.communities),
                "candidate_count": 0,
                "shortlist_count": 0,
                "deep_read_count": 0,
                "analyzed_posts": 0,
                "topic_count": 0,
                "failure_count": 0,
                "eligible_post_count": 0,
                "excluded_post_count": 0,
                "comment_evidence_count": 0,
            },
            "artifacts": {},
            "failures": [],
        }

    def _load_saved_analyses(self, paths: Any) -> dict[str, PostAnalysis]:
        analyses: dict[str, PostAnalysis] = {}
        for checkpoint in paths.checkpoints_dir.glob("analysis__*.json"):
            document = json.loads(checkpoint.read_text(encoding="utf-8"))
            if document.get("status") != "success":
                continue
            analysis_document = document.get("analysis")
            if not isinstance(analysis_document, Mapping):
                continue
            if not analysis_document.get("topics") and not analysis_document.get("claims"):
                # Empty model responses are retryable; do not permanently checkpoint them as success.
                continue
            analyses[str(document["post_id"])] = self._post_analysis_from_dict(analysis_document)
        return analyses

    def _write_analysis_checkpoint(self, paths: Any, post_id: str, analysis: PostAnalysis) -> None:
        document = {
            "status": "success",
            "post_id": post_id,
            "analysis": asdict(analysis),
        }
        (paths.checkpoints_dir / f"analysis__{post_id}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _write_failed_analysis_checkpoint(self, paths: Any, post_id: str, message: str) -> None:
        document = {"status": "failed", "post_id": post_id, "message": message}
        (paths.checkpoints_dir / f"analysis__{post_id}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _post_analysis_from_dict(self, document: Mapping[str, Any]) -> PostAnalysis:
        topics = tuple(
            TopicCandidate(
                label=str(item.get("label", "")),
                evidence_ids=tuple(
                    value for value in item.get("evidence_ids", []) if isinstance(value, str)
                ),
            )
            for item in document.get("topics", [])
            if isinstance(item, Mapping)
        )
        claims = tuple(
            EvidenceClaim(
                claim=str(item.get("claim", "")),
                evidence_ids=tuple(
                    value for value in item.get("evidence_ids", []) if isinstance(value, str)
                ),
                urls=tuple(value for value in item.get("urls", []) if isinstance(value, str)),
                status=str(item.get("status", "supported")),
            )
            for item in document.get("claims", [])
            if isinstance(item, Mapping)
        )
        scalar_names = ("platform", "vehicle", "year", "scenario", "goal", "sentiment", "user_type")
        list_names = (
            "pain_points", "needs", "current_solutions", "gaps", "opportunity_hypotheses", "products",
            "brands", "competitors", "purchase_intent", "keyword_candidates", "topic_candidates",
            "pain_severity", "consequences", "supporting_views", "opposing_views",
        )
        scalar_fields = {name: self._saved_analysis_field(document.get(name)) for name in scalar_names}
        list_fields = {
            name: tuple(self._saved_analysis_field(item) for item in document.get(name, []) if isinstance(item, Mapping))
            if isinstance(document.get(name), list) else ()
            for name in list_names
        }
        return PostAnalysis(
            topics=topics, claims=claims,
            platform=scalar_fields["platform"], vehicle=scalar_fields["vehicle"], year=scalar_fields["year"],
            scenario=scalar_fields["scenario"], goal=scalar_fields["goal"], sentiment=scalar_fields["sentiment"],
            pain_points=list_fields["pain_points"], needs=list_fields["needs"], current_solutions=list_fields["current_solutions"],
            gaps=list_fields["gaps"], opportunity_hypotheses=list_fields["opportunity_hypotheses"], products=list_fields["products"],
            brands=list_fields["brands"], competitors=list_fields["competitors"], purchase_intent=list_fields["purchase_intent"],
            keyword_candidates=list_fields["keyword_candidates"], topic_candidates=list_fields["topic_candidates"],
            user_type=scalar_fields["user_type"], pain_severity=list_fields["pain_severity"],
            consequences=list_fields["consequences"], supporting_views=list_fields["supporting_views"],
            opposing_views=list_fields["opposing_views"],
        )

    @staticmethod
    def _saved_analysis_field(value: Any) -> AnalysisField:
        if not isinstance(value, Mapping) or not isinstance(value.get("value"), str):
            return AnalysisField()
        status = str(value.get("status", "unknown"))
        if status not in {"fact", "inference", "unknown"}:
            status = "unknown"
        ids = tuple(item for item in value.get("evidence_ids", []) if isinstance(item, str)) if isinstance(value.get("evidence_ids"), list) else ()
        return AnalysisField(value["value"].strip() or "unknown", ids if status != "unknown" else (), status)

    def _artifact_map(self, exported: TopicExportArtifacts, formats: Sequence[str]) -> dict[str, str]:
        artifact_map = {
            "analysis_json": str(exported.analysis_json),
            "community_topics_json": str(exported.community_topics_json),
        }
        if "xlsx" in formats:
            artifact_map["community_topics_xlsx"] = str(exported.workbook_path)
        if "html" in formats and exported.report_path is not None:
            artifact_map["report_html"] = str(exported.report_path)
            map_path = exported.report_path.parent / "community_topic_map.json"
            if map_path.exists():
                artifact_map["community_topic_map_json"] = str(map_path)
        return artifact_map

    def _failure_to_dict(self, failure: CollectionFailure) -> dict[str, str | None]:
        return {
            "community": failure.community,
            "post_id": failure.post_id,
            "stage": failure.stage,
            "message": failure.message,
        }

    def _write_state(self, path: Path, state: Mapping[str, Any]) -> None:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _read_state(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _merge_stages(self, existing: Sequence[str], *new_stages: str) -> list[str]:
        return list(dict.fromkeys([*existing, *new_stages]))

    def _validate_export_formats(self, formats: Sequence[str]) -> tuple[str, ...]:
        requested = tuple(dict.fromkeys(value.strip().lower() for value in formats if value and value.strip()))
        if not requested:
            raise ValueError("At least one export format is required")
        unsupported = [value for value in requested if value not in {"json", "xlsx", "html"}]
        if unsupported:
            raise ValueError(f"Unsupported export format: {unsupported[0]}")
        if "html" in requested and self._has_custom_exporter:
            raise ValueError("Unsupported export format for a custom exporter: html")
        return requested

    def _find_executable(self, env_name: str, command_name: str) -> Path | None:
        explicit = self._environment.get(env_name)
        if explicit:
            candidate = Path(explicit)
            if candidate.exists():
                return candidate
        discovered = shutil.which(command_name)
        if discovered:
            return Path(discovered)
        return None

    def _rewrite_opencli(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        if self._has_custom_tool_runner:
            return arguments
        if arguments and arguments[0] == "opencli":
            executable = self._find_executable("RADAR_OPENCLI_EXE", "opencli")
            if executable is not None:
                return (str(executable), *arguments[1:])
        return arguments

    def _resolve_root(self, explicit: str | Path | None, *, env_name: str, default_relative: str) -> Path:
        candidate = explicit if explicit is not None else self._environment.get(env_name, default_relative)
        path = Path(candidate)
        if not path.is_absolute():
            path = self._repo_root / path
        return path.resolve()

    def _resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._repo_root / candidate
        return candidate.resolve()

    def _config_snapshot_text(self, config_path: Path) -> str:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            return config_path.read_text(encoding="utf-8")
        configured = raw.get("community_catalog_path")
        if isinstance(configured, str) and configured.strip():
            resolved = Path(configured.strip())
            if not resolved.is_absolute():
                resolved = (config_path.parent / resolved).resolve()
            raw["community_catalog_path"] = str(resolved)
        return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)

    def _next_catalog_version(self, version: str) -> str:
        if version.endswith(".v1"):
            return version[:-1] + "2"
        if ".v" in version:
            prefix, suffix = version.rsplit(".v", 1)
            if suffix.isdigit():
                return f"{prefix}.v{int(suffix) + 1}"
        return version + ".v2"

    def _next_catalog_filename(self, name: str) -> str:
        path = Path(name)
        stem = path.stem
        if stem.endswith(".v1"):
            next_stem = stem[:-1] + "2"
        elif ".v" in stem and stem.rsplit(".v", 1)[1].isdigit():
            prefix, suffix = stem.rsplit(".v", 1)
            next_stem = f"{prefix}.v{int(suffix) + 1}"
        else:
            next_stem = stem + ".v2"
        return next_stem + path.suffix

    def _write_json_exports(self, output_dir: Path, analysis: Mapping[str, Any]) -> TopicExportArtifacts:
        return export_topic_analysis(
            analysis,
            output_dir=output_dir,
            formats=("json",),
            environment=self._environment,
        )

    def _invoke_exporter(
        self, output_dir: Path, analysis: Mapping[str, Any], formats: tuple[str, ...]
    ) -> TopicExportArtifacts:
        parameter_count = len(inspect.signature(self._exporter).parameters)
        if parameter_count >= 3:
            return self._exporter(output_dir, analysis, formats)
        return self._exporter(output_dir, analysis)


def _opencli_session_flags() -> tuple[str, ...]:
    return ("--window", "foreground", "--site-session", "persistent")


def _analysis_value(field: AnalysisField) -> str:
    value = getattr(field, "value", "")
    return str(value or "").strip()


def _analysis_values(fields: Sequence[AnalysisField]) -> list[str]:
    return [value for value in (_analysis_value(field) for field in fields) if value and value != "unknown"]


def _deepseek_proposals_from_document(document: Mapping[str, Any], signals: Sequence[Any]) -> tuple[ProTopicProposal, ...]:
    """Normalize DeepSeek gateway variants into the evidence-gated topic contract."""
    signal_by_id = {signal.post.post_id: signal for signal in signals}
    topics = document.get("topics")
    if not isinstance(topics, list):
        nested = document.get("analysis")
        topics = nested.get("topics") if isinstance(nested, Mapping) else []
    proposals: list[ProTopicProposal] = []
    for item in topics if isinstance(topics, list) else []:
        if not isinstance(item, Mapping):
            continue
        post_ids = tuple(dict.fromkeys(
            value for value in item.get("post_ids", [])
            if isinstance(value, str) and value in signal_by_id
        ))
        if not post_ids:
            continue
        summary_text = _deepseek_text(item.get("summary"))
        evidence = _deepseek_topic_evidence(item.get("evidence"), item, post_ids, signal_by_id, summary_text)
        if not evidence or not summary_text:
            continue
        summary = _deepseek_claim(item.get("summary"), summary_text, evidence, post_ids, signal_by_id, field="summary")
        if not summary.evidence:
            summary = replace(summary, evidence=evidence[:3])
        proposals.append(ProTopicProposal(
            canonical_key=str(item.get("canonical_key", "")).strip() or _topic_key_from_label(item.get("label_en") or item.get("label_zh")),
            label_en=str(item.get("label_en", "")).strip() or str(item.get("label_zh", "")).strip(),
            label_zh=str(item.get("label_zh", "")).strip() or str(item.get("label_en", "")).strip(),
            summary=summary,
            post_ids=post_ids,
            evidence=evidence,
            vehicles=_strings_from_any(item.get("vehicles")),
            platforms=_strings_from_any(item.get("platforms")),
            scenarios=_strings_from_any(item.get("scenarios")),
            pains=_deepseek_claims(item.get("pains"), evidence, post_ids, signal_by_id, "pains"),
            needs=_deepseek_claims(item.get("needs"), evidence, post_ids, signal_by_id, "needs"),
            current_solutions=_deepseek_claims(item.get("current_solutions"), evidence, post_ids, signal_by_id, "current_solutions"),
            gaps=_deepseek_claims(item.get("gaps"), evidence, post_ids, signal_by_id, "gaps"),
            opportunity_hypotheses=_deepseek_claims(item.get("opportunity_hypotheses"), evidence, post_ids, signal_by_id, "opportunity_hypotheses"),
            category_tags=_strings_from_any(item.get("category_tags")),
            brand_tags=_strings_from_any(item.get("brand_tags")),
            competitor_tags=_strings_from_any(item.get("competitor_tags")),
            confidence=max(0.0, min(1.0, _float_or_zero(item.get("confidence")))),
            validation_questions=_strings_from_any(item.get("validation_questions")),
            user_types=_strings_from_any(item.get("user_types")),
            consequences=_deepseek_claims(item.get("consequences"), evidence, post_ids, signal_by_id, "consequences"),
            risks=_deepseek_claims(item.get("risks"), evidence, post_ids, signal_by_id, "risks"),
            product_decision=str(item.get("product_decision", "no_product")) if str(item.get("product_decision", "no_product")) in {
                "improve_existing", "new_fitment_sku", "accessory_bundle", "new_product", "content_service", "no_product"
            } else "no_product",
            seller_insight=_deepseek_claim(item.get("seller_insight"), _deepseek_text(item.get("seller_insight")), evidence, post_ids, signal_by_id, field="seller_insight"),
            user_tasks=_deepseek_claims(
                _first_nonempty(item, "user_tasks", "jtbd_cards", "tasks"),
                evidence, post_ids, signal_by_id, "user_tasks",
            ),
            scene_details=_deepseek_claims(
                _first_nonempty(item, "scene_cards", "scenes", "scenarios", "scenario", "scene"),
                evidence, post_ids, signal_by_id, "scenes",
            ),
        ))
    return tuple(item for item in proposals if item.canonical_key)


def _strings_from_any(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("text", item.get("value", ""))
        text = str(item or "").strip()
        if text and text != "unknown" and text not in result:
            result.append(text)
    return tuple(result)


def _first_nonempty(item: Mapping[str, Any], *keys: str) -> Any:
    """Pick the first populated alias emitted by a gateway deployment."""
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], (), {}):
            return value
    return None


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _deepseek_text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("text", "value", "summary", "claim"):
            text = str(value.get(key, "") or "").strip()
            if text:
                return text
        # Scene/JTBD cards from the Higress deployment use descriptive keys
        # instead of the common ``text`` key.  Preserve that structure as one
        # Chinese claim so it can still be evidence-gated and displayed.
        parts = []
        for key, label in (("scene", "场景"), ("context", "条件"), ("goal", "目标"), ("task", "任务"), ("challenge", "挑战"), ("problem", "问题")):
            text = str(value.get(key, "") or "").strip()
            if text:
                parts.append(f"{label}：{text}")
        if parts:
            return "；".join(parts)
        return ""
    return str(value or "").strip()


def _topic_key_from_label(value: Any) -> str:
    """Create a stable, non-empty key when a gateway omits canonical_key."""
    text = " ".join(str(value or "").casefold().split())
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return key[:96] or "topic_unlabelled"


def _deepseek_refs(value: Any) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    raw = value.get("evidence") if isinstance(value, Mapping) else value
    if isinstance(raw, Mapping):
        raw = list(raw.keys())
    if not isinstance(raw, (list, tuple)):
        return refs
    for item in raw:
        if isinstance(item, Mapping):
            post_id = str(item.get("post_id", "")).strip()
            evidence_id = str(item.get("evidence_id", item.get("id", ""))).strip()
            if post_id and evidence_id:
                refs.append((post_id, evidence_id))
        elif isinstance(item, str):
            value = item.strip()
            if ":" in value:
                post_id, evidence_id = value.split(":", 1)
                refs.append((post_id, evidence_id))
            elif value:
                refs.append(("", value))
    return refs


def _deepseek_topic_evidence(raw: Any, item: Mapping[str, Any], post_ids: Sequence[str], signal_by_id: Mapping[str, Any], summary_text: str) -> tuple[TopicEvidence, ...]:
    rows: list[TopicEvidence] = []
    if isinstance(raw, list):
        for record in raw:
            if not isinstance(record, Mapping):
                continue
            post_id = str(record.get("post_id", "")).strip()
            evidence_id = str(record.get("evidence_id", "")).strip()
            signal = signal_by_id.get(post_id)
            # Several OpenAI-compatible gateway deployments echo the post ID
            # as the evidence ID for the post itself.  Normalize that wire
            # shape to our canonical ``post`` key before validating it.
            if signal is not None and evidence_id == post_id:
                evidence_id = "post"
            if signal is not None and ":" in evidence_id:
                prefix, suffix = evidence_id.split(":", 1)
                if prefix == post_id and suffix in signal.evidence_urls:
                    evidence_id = suffix
            if not post_id or not evidence_id or signal is None or evidence_id not in signal.evidence_urls:
                continue
            claim = str(record.get("claim", "") or "").strip() or _source_excerpt_for_signal(signal, evidence_id)
            translation = str(record.get("translation_zh", "") or "").strip() or summary_text
            rows.append(TopicEvidence(post_id, evidence_id, claim, str(record.get("stance", "supporting")), translation))
    elif isinstance(raw, Mapping):
        url_to_ref = {
            url: (signal.post.post_id, evidence_id)
            for signal in signal_by_id.values()
            for evidence_id, url in signal.evidence_urls.items()
        }
        for key, url in raw.items():
            post_id, evidence_id = url_to_ref.get(str(url), ("", str(key)))
            if post_id and evidence_id == post_id:
                evidence_id = "post"
            if not post_id:
                for candidate in post_ids:
                    signal = signal_by_id[candidate]
                    if evidence_id == candidate:
                        evidence_id = "post"
                    if evidence_id in signal.evidence_urls:
                        post_id = candidate
                        break
            signal = signal_by_id.get(post_id)
            if signal is None or evidence_id not in signal.evidence_urls:
                continue
            rows.append(TopicEvidence(post_id, evidence_id, _source_excerpt_for_signal(signal, evidence_id), "supporting", summary_text))
    # Do not let a model that omitted citations erase a topic which is plainly
    # grounded in the supplied post IDs.  We bind the fallback to the exact
    # source post and use only its title/body excerpt as evidence.
    if not rows:
        for post_id in post_ids[:3]:
            signal = signal_by_id.get(post_id)
            if signal is None:
                continue
            rows.append(TopicEvidence(
                post_id,
                "post",
                _source_excerpt_for_signal(signal, "post"),
                "supporting",
                summary_text or _source_excerpt_for_signal(signal, "post"),
            ))
    unique: dict[tuple[str, str], TopicEvidence] = {}
    for row in rows:
        unique.setdefault((row.post_id, row.evidence_id), row)
    return tuple(unique.values())


def _source_excerpt_for_signal(signal: Any, evidence_id: str) -> str:
    if evidence_id == "post":
        return str(signal.post.title or signal.post.body or "").strip()[:280]
    for comment in signal.comments:
        if comment.comment_id == evidence_id:
            return str(comment.body or "").strip()[:280]
    return str(signal.post.title or "").strip()[:280]


def _deepseek_claim(value: Any, text: str, evidence: Sequence[TopicEvidence], post_ids: Sequence[str], signal_by_id: Mapping[str, Any], *, field: str) -> EvidenceBackedClaim:
    if not text:
        return EvidenceBackedClaim("", ())
    refs = _deepseek_refs(value)
    selected: list[TopicEvidence] = []
    for ref_post, ref_id in refs:
        selected.extend(item for item in evidence if item.evidence_id == ref_id and (not ref_post or item.post_id == ref_post))
    if not selected:
        selected = list(evidence[:3])
    mapping = value if isinstance(value, Mapping) else {}
    return EvidenceBackedClaim(
        text=text,
        evidence=tuple(dict.fromkeys(selected)),
        status=str(mapping.get("status", "inference")) if str(mapping.get("status", "inference")) in {"fact", "inference", "unknown"} else "inference",
        field=field,
        post_ids=tuple(dict.fromkeys(item.post_id for item in selected)) or tuple(post_ids),
        author_ids=tuple(dict.fromkeys(signal_by_id[post_id].post.author.casefold() for post_id in post_ids if post_id in signal_by_id and signal_by_id[post_id].post.author)),
        frequency=_int_or_zero(mapping.get("frequency", len(selected)) or len(selected)) or len(selected),
        severity=str(mapping.get("severity", "unknown") or "unknown"),
        consequence=str(mapping.get("consequence", "unknown") or "unknown"),
        explanation=str(mapping.get("explanation", "") or "").strip(),
    )


def _deepseek_claims(value: Any, evidence: Sequence[TopicEvidence], post_ids: Sequence[str], signal_by_id: Mapping[str, Any], field: str) -> tuple[EvidenceBackedClaim, ...]:
    if isinstance(value, (str, Mapping)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[EvidenceBackedClaim] = []
    for item in value:
        text = _deepseek_text(item)
        claim = _deepseek_claim(item, text, evidence, post_ids, signal_by_id, field=field)
        if claim.text and claim.evidence:
            result.append(claim)
    return tuple(result)


class DeepSeekTopicConsolidator:
    """Use DeepSeek Pro to consolidate per-post signals into community topics."""

    def __init__(self, *, client: DeepSeekClient, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def mode(self) -> str:
        return "deepseek_pro"

    def consolidate(self, community: str, signals: Sequence[Any]) -> Sequence[ProTopicProposal]:
        signal_payload = [
            {
                "post_id": signal.post.post_id,
                "title": signal.post.title,
                "subreddit": signal.post.subreddit,
                "created_at": signal.post.created_at.isoformat(),
                "author": signal.post.author,
                "score": signal.post.score,
                "comment_count": signal.post.comment_count,
                "body": str(signal.post.body or "")[:1200],
                "topics": [topic.label for topic in signal.analysis.topics],
                "scenario": _analysis_value(signal.analysis.scenario),
                "goal": _analysis_value(signal.analysis.goal),
                "user_type": _analysis_value(signal.analysis.user_type),
                "pains": _analysis_values(signal.analysis.pain_points),
                "needs": _analysis_values(signal.analysis.needs),
                "solutions": _analysis_values(signal.analysis.current_solutions),
                "gaps": _analysis_values(signal.analysis.gaps),
                "consequences": _analysis_values(signal.analysis.consequences),
                "opportunities": _analysis_values(signal.analysis.opportunity_hypotheses),
                "products": _analysis_values(signal.analysis.products),
                "brands": _analysis_values(signal.analysis.brands),
                "evidence": signal.evidence_urls,
                "comments": [
                    {"evidence_id": comment.comment_id, "author": comment.author, "body": str(comment.body or "")[:500], "url": comment.url}
                    for comment in signal.comments[:8]
                ],
            }
            for signal in signals
        ]
        document = self._client.chat_json(
            (
                {"role": "system", "content": "你是北美柴油皮卡改装市场的VOC研究员。只根据输入证据归并社区话题，不能编造事实。"},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "community": community,
                            "signals": signal_payload,
                            "instruction": (
                                "返回JSON对象 {topics:[...] }，每个社区最多归并4个核心话题。只保留同类用户任务、问题或期望结果的话题，禁止other/general/rule话题。"
                                "每个话题必须包含 canonical_key、label_en、label_zh、post_ids、evidence、summary、seller_insight、"
                                "scene_cards、user_tasks、pains、needs、current_solutions、gaps、opportunity_hypotheses、"
                                "supporting_views、opposing_views、validation_questions、product_decision、confidence。"
                                "除车型、发动机、品牌、产品名和label_en外，所有叙述必须使用简体中文。"
                                "summary、seller_insight、scene_cards、user_tasks及每一条pains/needs/solutions/gaps/opportunity都必须引用证据。"
                                "断言格式为 {text,explanation,status,evidence:[{post_id,evidence_id}],frequency,severity,consequence}；"
                                "evidence格式为数组 [{post_id,evidence_id,claim,translation_zh,stance}]，claim必须是输入中的原文摘录或忠实概括。"
                                "所有证据ID必须来自输入，无法支持的内容不要输出。product_decision只能是 improve_existing、"
                                "new_fitment_sku、accessory_bundle、new_product、content_service、no_product。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                },
            ),
            model=self._model,
        )
        proposals = list(_deepseek_proposals_from_document(document, signals))
        if not proposals:
            raise DeepSeekError("DeepSeek Pro 未返回可验证的话题；保留检查点等待重试。")
        return proposals

    def _rule_fallback(self, signals: Sequence[Any]) -> Sequence[ProTopicProposal]:
        """Produce an evidence-linked local VOC analysis when Pro is unavailable.

        Topic specs remain matching lenses only.  The text shown in a report is
        synthesized from the selected post/comment evidence; the old version
        copied fixed pains, gaps and opportunity prose into every topic.
        """
        grouped: dict[str, list[Any]] = {spec["key"]: [] for spec in _LOCAL_TOPIC_SPECS}
        for signal in signals:
            # Topic membership is decided from the original post.  Comments
            # remain evidence and are used below, but letting every comment
            # keyword drive membership causes unrelated topics to bleed into
            # one another (for example a comment mentioning a turbo in a
            # transmission thread).
            text = _post_text(signal)
            matched_specs = [spec for spec in _LOCAL_TOPIC_SPECS if any(re.search(pattern, text) for pattern in spec["patterns"])]
            # Preserve an auditable bucket for posts that passed the diesel
            # gate but do not match one of the known opportunity lenses.
            if not matched_specs:
                matched_specs = [_LOCAL_TOPIC_SPECS[-1]]
            for spec in matched_specs[:3]:
                if signal not in grouped[spec["key"]]:
                    grouped[spec["key"]].append(signal)

        proposals: list[ProTopicProposal] = []
        for spec in _LOCAL_TOPIC_SPECS:
            topic_signals = grouped[spec["key"]]
            if not topic_signals:
                continue
            post_ids = tuple(signal.post.post_id for signal in topic_signals)
            topic_voc = synthesize_topic_voc(
                topic_signals,
                spec["key"],
                topic_patterns=spec["patterns"],
            )
            signal_by_id = {signal.post.post_id: signal for signal in topic_signals}
            claims = lambda field: tuple(
                _voc_claim_to_evidence_claim(claim, signal_by_id)
                for claim in topic_voc.claims.get(field, ())
            )
            pains = claims("pain")
            needs = claims("need")
            solutions = claims("current_solution")
            gaps = claims("solution_gap")
            consequences = claims("consequence")
            hypotheses = tuple(
                _voc_claim_to_evidence_claim(claim, signal_by_id)
                for claim in topic_voc.opportunity_hypotheses
            )
            evidence_for_claims = _topic_voc_evidence(topic_voc, signal_by_id)
            if not evidence_for_claims:
                evidence_for_claims = tuple(_rule_post_evidence(signal) for signal in topic_signals[:3])
            summary = EvidenceBackedClaim(
                _topic_voc_summary(topic_voc, len(post_ids), sum(len(getattr(s, "comments", ())) for s in topic_signals)),
                evidence_for_claims[: min(5, len(evidence_for_claims))],
            )
            proposals.append(
                ProTopicProposal(
                    canonical_key=f"local-{spec['key']}",
                    label_en=spec["label_en"],
                    label_zh=spec["label_zh"],
                    summary=summary,
                    post_ids=post_ids,
                    evidence=evidence_for_claims,
                    vehicles=_rule_values(topic_signals, "vehicle"),
                    platforms=_rule_values(topic_signals, "platform"),
                    scenarios=_rule_values(topic_signals, "scenario"),
                    pains=pains,
                    needs=needs,
                    current_solutions=solutions,
                    gaps=gaps,
                    opportunity_hypotheses=hypotheses,
                    category_tags=tuple(dict.fromkeys((*spec["tags"], "evidence_synthesized"))),
                    brand_tags=_rule_values(topic_signals, "brands"),
                    competitor_tags=_rule_values(topic_signals, "competitors"),
                    confidence=min(0.88, 0.35 + 0.08 * len(post_ids) + 0.01 * min(20, sum(len(getattr(s, "comments", ())) for s in topic_signals))),
                    validation_questions=_topic_validation_questions(topic_voc),
                    consequences=consequences,
                    product_decision=("emerging_product" if topic_voc.opportunity_status == "emerging_product" else "no_product"),
                )
            )
        return proposals


def _voc_claim_to_evidence_claim(claim: Any, signal_by_id: Mapping[str, Any]) -> EvidenceBackedClaim:
    evidence: list[TopicEvidence] = []
    for qualified_id in claim.evidence_ids:
        post_id, separator, source_id = str(qualified_id).partition(":")
        if not separator:
            post_id, source_id = (claim.post_ids[0] if claim.post_ids else ""), qualified_id
        signal = signal_by_id.get(post_id)
        if signal is None:
            continue
        url = signal.evidence_urls.get(source_id)
        if not url:
            continue
        evidence.append(TopicEvidence(
            post_id=post_id,
            evidence_id=source_id,
            claim=_source_excerpt(signal, source_id),
            stance="supporting",
            translation_zh=claim.text,
        ))
    return EvidenceBackedClaim(
        claim.text,
        tuple(evidence),
        status=claim.status,
        field=claim.field,
        post_ids=tuple(claim.post_ids),
        author_ids=tuple(claim.author_ids),
        frequency=int(claim.frequency),
        severity=claim.severity,
        consequence=claim.consequence,
    )


def _topic_voc_evidence(topic_voc: Any, signal_by_id: Mapping[str, Any]) -> tuple[TopicEvidence, ...]:
    values: list[TopicEvidence] = []
    seen: set[tuple[str, str]] = set()
    for claims in topic_voc.claims.values():
        for claim in claims:
            for item in _voc_claim_to_evidence_claim(claim, signal_by_id).evidence:
                key = (item.post_id, item.evidence_id)
                if key not in seen:
                    seen.add(key)
                    values.append(item)
    for claim in topic_voc.opportunity_hypotheses:
        for item in _voc_claim_to_evidence_claim(claim, signal_by_id).evidence:
            key = (item.post_id, item.evidence_id)
            if key not in seen:
                seen.add(key)
                values.append(item)
    return tuple(values)


def _source_excerpt(signal: Any, source_id: str) -> str:
    if source_id == "post":
        post = signal.post
        text = " — ".join(
            str(value or "").strip() for value in (post.title, post.body)
            if str(value or "").strip()
        )
    else:
        text = next(
            (str(getattr(comment, "body", "") or "").strip()
             for comment in getattr(signal, "comments", ()) or ()
             if str(getattr(comment, "comment_id", "") or "") == source_id),
            "",
        )
    return " ".join(text.split())[:420] or "未提供原文"


def _topic_voc_summary(topic_voc: Any, post_count: int, comment_count: int) -> str:
    parts: list[str] = []
    if topic_voc.scenario:
        parts.append("场景：" + "、".join(topic_voc.scenario[:3]))
    if topic_voc.user_task != "unknown":
        parts.append("用户任务：" + topic_voc.user_task)
    pains = topic_voc.claims.get("pain", ())
    if pains:
        parts.append("主要痛点：" + pains[0].text)
    if not parts:
        parts.append("当前帖子尚未形成可稳定归纳的具体任务或痛点")
    return "；".join(parts) + f"。基于 {post_count} 篇帖子和 {comment_count} 条评论的社区样本信号，不代表全市场占有率。"


def _topic_validation_questions(topic_voc: Any) -> tuple[str, ...]:
    questions: list[str] = []
    if not topic_voc.claims.get("pain"):
        questions.append("是否有更多独立作者描述同一具体问题？")
    if not topic_voc.claims.get("solution_gap"):
        questions.append("现有产品或维修办法具体缺少哪一项能力？")
    if topic_voc.claims.get("pain") and topic_voc.claims.get("solution_gap"):
        questions.append("同一车型、负载或安装条件下，问题是否会重复发生？")
    return tuple(dict.fromkeys(questions))


# Local, explainable VOC lenses.  The patterns are intentionally broad enough
# to discover needs outside the original five product categories, but each
# topic is still tied to exact Reddit evidence and shown as a hypothesis.
_LOCAL_TOPIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "turbo_compounds_egt",
        "label_en": "Turbo, compound setup and towing EGT",
        "label_zh": "涡轮/复合增压与拖挂排温",
        "patterns": (r"\bturbo\b|\bturbos\b|compound|drop[- ]?in|2nd gen|second gen|egt|exhaust gas temperature|spool|boost",),
        "summary": "用户在涡轮、复合增压和拖挂工况之间权衡响应、排温、排气制动及后续动力升级。",
        "pains": ("拖挂或爬坡时排气温度偏高、需要反复检查增压系统", "不同涡轮方案在低转响应与后续加油空间之间取舍困难"),
        "needs": ("按车型、载荷和动力配置给出可比较的涡轮/复合增压适配建议", "在日常响应、排气制动和拖挂可靠性之间取得平衡"),
        "solutions": ("改用 drop-in 或 second-gen swap", "通过检查增压管路、调整喷油/调校来处理排温"),
        "gaps": ("现有方案的适配、滞后表现和拖挂效果依赖个人经验，难以在购买前比较", "不同配件组合缺少按载荷工况验证的安装与调校说明"),
        "hypotheses": ("机会假设：按车型/载荷提供可核对的涡轮组合与排温验证指南，并配套适配件",),
        "scenarios": ("拖挂/长途", "性能改装"), "tags": ("performance", "towing", "rule_based"),
        "validation_questions": ("同一车型和载荷下，是否有更多用户遇到排温/响应取舍？", "用户愿意为成套适配和工况验证支付多少？"),
    },
    {
        "key": "tuning_fuel_fitment",
        "label_en": "Tuner, tune and fuel-system fitment",
        "label_zh": "调谐器/调校与供油系统适配",
        "patterns": (r"\btun(?:e|er|ing)\b|hydra|efi ?live|edge|firepunk|lift pump|airdog|fass|fuel bowl|injector|calibrat",),
        "summary": "用户询问调谐器、调校档位和供油系统如何匹配现有涡轮、喷油嘴及拖挂用途。",
        "pains": ("买到车辆后不清楚现有调谐器或档位对应的程序", "调校、喷油和供油升级之间的兼容关系不透明"),
        "needs": ("明确的车型/发动机/硬件到调校档位的适配矩阵", "在温和拖挂与更高动力之间可控切换，并能看懂当前档位"),
        "solutions": ("Hydra、EFI Live、PPEI、Starlite 等调校或调谐器", "原厂泵、FASS/AirDog 及 fuel-bowl delete 等供油方案"),
        "gaps": ("购买二手车后常缺少调校文件、档位说明和控制器可读性", "不同品牌方案的安装边界与后续维护成本缺少统一说明"),
        "hypotheses": ("机会假设：提供可识别当前配置、显示档位并按硬件校验的调谐器/供油套装",),
        "scenarios": ("二手车接手", "拖挂/日常驾驶"), "tags": ("tuning", "fuel_system", "rule_based"),
        "validation_questions": ("用户最常缺的是调校文件、控制器界面还是供油硬件适配？", "是否存在因档位/调校不清导致的退货或返工？"),
    },
    {
        "key": "coolant_oil_leak_repair",
        "label_en": "Coolant, oil and boost leak repair",
        "label_zh": "冷却液/机油/增压泄漏维修",
        "patterns": (r"\bleak\b|leaking|seep|coolant|radiator|water pump|oil pan|oil rail|hpop|hose|seal|rtv|gasket|air leak|boost leak",),
        "summary": "真实维修讨论集中在冷却液、机油、增压管路和密封反复渗漏，以及更换整套总成还是单个零件。",
        "pains": ("泄漏位置难定位，维修后短时间内再次渗漏", "零件目录常只提供整套软管/总成，用户想买单个接头或密封件"),
        "needs": ("按发动机代号和年份快速定位泄漏点与替换零件", "有明确密封面、紧固和复检要求的维修配件"),
        "solutions": ("更换整套软管、散热器、油盘或涡轮", "使用 RTV、垫片、卡箍并重新抽真空/复检"),
        "gaps": ("零件适配和密封方案分散在评论里，原厂与改装件选择缺少对照", "返工成本高，安装失误或零件质量问题不易区分"),
        "hypotheses": ("机会假设：开发按平台细分的泄漏维修小套件，附带定位、密封和复检清单",),
        "scenarios": ("故障维修", "改装后复检"), "tags": ("repair", "reliability", "rule_based"),
        "validation_questions": ("哪些泄漏点最常导致整套总成更换或二次返工？", "用户更愿意购买单点维修包还是整套升级件？"),
    },
    {
        "key": "transmission_towing_reliability",
        "label_en": "Transmission reliability for towing",
        "label_zh": "拖挂场景下的变速箱可靠性",
        "patterns": (r"transmission|\b47re\b|\b48re\b|\b68rfe\b|\b4r100\b|limp mode|shift|fluid|filter|torque converter|transfer case",),
        "summary": "用户把变速箱寿命、滤芯/油液维护和拖挂负载联系起来，并在维修、强化和换车之间做决策。",
        "pains": ("高里程或拖挂后变速箱故障成本高", "原厂维护信息与经销商建议不一致，难以判断是否需要强化"),
        "needs": ("按里程、负载和改装水平给出维护/强化优先级", "能与调校、涡轮和拖挂工况一起评估的可靠性方案"),
        "solutions": ("更换滤芯和油液、重建变速箱或安装强化件", "通过论坛经验和维修视频自行判断"),
        "gaps": ("不同平台和改装组合的维护边界不清晰", "产品、安装和后续调校经常需要多个供应商拼接"),
        "hypotheses": ("机会假设：按平台和拖挂等级提供变速箱维护/强化组合包及检查表",),
        "scenarios": ("拖挂", "高里程维修"), "tags": ("transmission", "towing", "rule_based"),
        "validation_questions": ("哪些拖挂里程或动力配置最容易触发强化需求？", "用户购买时最重视温度监测、滤芯维护还是内部强化？"),
    },
    {
        "key": "suspension_brake_tire_fitment",
        "label_en": "Lift, brake and tire fitment",
        "label_zh": "升高/制动/轮胎适配",
        "patterns": (r"brake|jack stand|lift|leveling|suspension|shock|tire|tyre|wheel|tow vehicle|fifth wheel|5th wheel|load",),
        "summary": "升高、制动和轮胎选择都围绕载荷、拖挂稳定性、安装安全和车型适配展开。",
        "pains": ("升高车辆维修和顶车时安全边界不明确", "拖挂车辆需要在耐久、负载和日常舒适之间选轮胎/悬挂"),
        "needs": ("适配升高高度、轮胎尺寸和拖挂负载的安装清单", "能够验证承载、间隙和制动安全的产品组合"),
        "solutions": ("更换轮胎、减震器、平衡块或升级前端部件", "参考社区经验和现场测量"),
        "gaps": ("商品页面常缺少升高高度、负载和工具/安全要求", "轮胎、悬挂和制动方案常被分开购买，缺少整体适配"),
        "hypotheses": ("机会假设：提供按升高/轮胎/拖挂等级组合的适配包和安全安装说明",),
        "scenarios": ("拖挂", "车库维修"), "tags": ("fitment", "safety", "rule_based"),
        "validation_questions": ("用户最常因间隙、承载还是安装工具问题返工？", "是否有明确的拖挂等级与轮胎/悬挂组合需求？"),
    },
    {
        "key": "used_truck_purchase_validation",
        "label_en": "Used diesel pickup purchase and inspection",
        "label_zh": "二手柴油皮卡购买与改装核验",
        "patterns": (r"buy|buying|purchase|seller|marketplace|what would you pay|worth|price|first diesel|mileage|miles|rust|value",),
        "summary": "首次购买者会同时核验里程、锈蚀、既有调谐器/涡轮/变速箱改装和后续维修预算。",
        "pains": ("卖家描述与实际改装状态可能不一致", "高里程、锈蚀和既有改装让价格与后续成本难判断"),
        "needs": ("看车时可执行的发动机、变速箱、锈蚀和改装核验清单", "将改装件品牌/状态与合理价格、维修预算关联起来"),
        "solutions": ("向社区提问、现场检查、读取故障码并参考同款交易价格", "购买后再逐步替换未知品牌或老化配件"),
        "gaps": ("产品和改装信息常缺少可验证凭证，购前无法确认适配与剩余寿命", "价格讨论与改装价值、维修风险没有结构化关联"),
        "hypotheses": ("机会假设：提供按平台/年份的改装识别与购前检查套件，降低接手未知配置的风险",),
        "scenarios": ("首次购车", "二手车验车"), "tags": ("purchase", "inspection", "rule_based"),
        "validation_questions": ("哪些未知改装最容易导致用户放弃购买或产生大额返工？", "用户愿意购买实体检查工具包还是数字化清单？"),
    },
    {
        "key": "general_diesel_signal",
        "label_en": "Other diesel-pickup repair and ownership signals",
        "label_zh": "其他柴油皮卡维修与使用信号",
        "patterns": (r"a^",),
        "summary": "该类帖子与柴油皮卡相关，但暂未稳定归入其他主题，保留用于后续词库发现。",
        "pains": ("问题场景、产品或车型信息仍需进一步补充",),
        "needs": ("更多同类帖子和评论来确认是否形成独立主题",),
        "solutions": ("社区问答或自行维修",),
        "gaps": ("当前证据不足以形成具体产品方向",),
        "hypotheses": ("机会假设：先扩充相关关键词和样本，再决定是否拆分为独立主题",),
        "scenarios": ("日常使用",), "tags": ("weak_signal", "rule_based"),
        "validation_questions": ("是否有更多帖子能将该信号归入明确的产品/场景？",),
    },
)


def _signal_text(signal: Any) -> str:
    parts = [str(getattr(signal.post, "title", "") or ""), str(getattr(signal.post, "body", "") or "")]
    parts.extend(str(getattr(comment, "body", "") or "") for comment in getattr(signal, "comments", ()) or ())
    return " ".join(parts).casefold()


def _post_text(signal: Any) -> str:
    return " ".join((str(getattr(signal.post, "title", "") or ""), str(getattr(signal.post, "body", "") or ""))).casefold()


def _rule_topic_evidence(signals: Sequence[Any], spec: Mapping[str, Any]) -> tuple[TopicEvidence, ...]:
    evidence: list[TopicEvidence] = []
    for signal in signals:
        post = signal.post
        title = str(post.title or "").strip() or "未知帖子"
        body = " ".join(str(post.body or "").split())
        excerpt = f"{title} — {body[:420]}" if body else title
        evidence.append(TopicEvidence(post.post_id, "post", excerpt, "supporting", f"原帖：{title}（原文已保留，中文分析见话题卡）"))
        matching_comments = []
        for comment in getattr(signal, "comments", ()) or ():
            comment_body = str(getattr(comment, "body", "") or "")
            if comment_body and any(re.search(pattern, comment_body.casefold()) for pattern in spec["patterns"]):
                matching_comments.append(comment)
        for comment in matching_comments[:2]:
            cid = str(getattr(comment, "comment_id", "") or "")
            if not cid:
                continue
            cbody = " ".join(str(getattr(comment, "body", "") or "").split())
            evidence.append(TopicEvidence(post.post_id, cid, cbody[:420], "supporting", "评论补充了该问题的具体表现与解决建议（原文链接可回溯）"))
    return tuple(evidence)


def _local_dynamic_claims(signals: Sequence[Any], spec: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    text = " ".join(_post_text(signal) for signal in signals)
    dynamic: dict[str, list[str]] = {"pains": [], "needs": [], "solutions": [], "gaps": []}
    if re.search(r"\bhigh egt|1200|1300|exhaust gas", text):
        dynamic["pains"].append("有用户报告无负载或爬坡时 EGT 达到 1200–1300°F，担心拖挂时继续升高")
    if re.search(r"fitment|clearance|doesn't fit|does not fit|whole hose|whole assembly", text):
        dynamic["gaps"].append("适配/间隙或零件供应方式导致用户考虑改装、加工或更换整套总成")
    if re.search(r"recommend|which|what should|advice|help", text):
        dynamic["needs"].append("用户希望在购买前得到针对具体车型、年份和用途的可执行建议")
    brands = []
    for name in ("Hydra", "FASS", "AirDog", "PPEI", "Starlite", "Mishimoto", "Fox", "Thuren", "Fleece", "EvilFab", "Stainless Diesel", "KC Turbo", "Kryptonite"):
        if re.search(rf"(?<![a-z]){re.escape(name.casefold())}(?![a-z])", text):
            brands.append(name)
    if brands:
        dynamic["solutions"].append("帖子提到的现有品牌/方案：" + "、".join(brands))
    if re.search(r"used|marketplace|bought|purchase|seller", text):
        dynamic["gaps"].append("二手车接手时既有改装状态和调校文件不透明，增加购后核验成本")
    return {key: tuple(values) for key, values in dynamic.items()}


def _rule_topic_key(label: str) -> str:
    value = " ".join(label.casefold().replace("power stroke", "powerstroke").split())
    aliases = {"egr cooler leak": "egr-leak", "downpipe fitment": "downpipe-fitment", "cold weather regen": "cold-regen"}
    return aliases.get(value, value.replace(" ", "-")[:80])


def _rule_label_zh(label: str) -> str:
    translations = {"egr cooler leak": "EGR冷却器渗漏", "downpipe fitment": "下降管适配", "cold weather regen": "低温再生"}
    return translations.get(label.casefold(), f"{label}（规则主题）")


def _rule_post_evidence(signal: Any) -> TopicEvidence:
    title = str(signal.post.title or "").strip() or str(signal.post.body or "").strip()[:240] or "未知帖子"
    return TopicEvidence(signal.post.post_id, "post", title, "supporting", f"原帖标题：{title}")


def _rule_claims(signals: Sequence[Any], field_name: str, evidence: Sequence[TopicEvidence]) -> tuple[EvidenceBackedClaim, ...]:
    values: list[str] = []
    for signal in signals:
        for field in getattr(signal.analysis, field_name, ()):
            value = str(getattr(field, "value", "") or "").strip()
            if value and value != "unknown" and value not in values:
                values.append(value)
    return tuple(EvidenceBackedClaim(value, evidence[:1]) for value in values[:5])


def _rule_values(signals: Sequence[Any], field_name: str) -> tuple[str, ...]:
    values: list[str] = []
    for signal in signals:
        raw = getattr(signal.analysis, field_name, None)
        fields = raw if isinstance(raw, tuple) else (raw,)
        for field in fields:
            value = str(getattr(field, "value", "") or "").strip()
            if value and value != "unknown" and value not in values:
                values.append(value)
    return tuple(values[:8])


def _rule_extract_post(thread: ThreadDocument, domain: Any) -> PostAnalysis:
    """Extract a small, auditable diesel signal without a model/API call."""
    text = f"{thread.post.title} {thread.post.body}".casefold()
    dictionaries = getattr(domain, "dictionaries", domain)

    def matched(values: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            str(value).strip() for value in values
            if str(value).strip() and re.search(rf"(?<![a-z0-9]){re.escape(str(value).casefold())}(?![a-z0-9])", text)
        ))

    platforms = matched(getattr(dictionaries, "platforms", ()))
    products = matched(getattr(dictionaries, "products", ()))
    vehicles = matched(getattr(dictionaries, "vehicle_terms", ()))
    scenarios = matched(getattr(dictionaries, "scenarios", ()))
    brands = matched(getattr(dictionaries, "brands", ()))
    pain_matches = tuple(
        label for pattern, label in (
            (r"leak|seep", "leak/seep"),
            (r"fail|failed|failure|broken(?!\s+in)|crack", "failure"),
            (r"fitment|fit|compatib", "fitment"),
            (r"install|installation|clearance", "installation complexity"),
            (r"regen|regeneration|dpf", "regeneration/DPF"),
            (r"clog|clogged", "clogging"),
        ) if re.search(pattern, text)
    )
    solution_matches = matched(("oem", "aftermarket", "replace", "replacement", "tune", "tuner", "clamp", "kit"))
    goal_matches = matched(("buy", "recommend", "need", "looking for", "what should"))
    topic_labels: list[str] = []
    for product in products[:2]:
        for pain in pain_matches[:2] or ("fitment",):
            topic_labels.append(f"{product} {pain}")
    if not topic_labels and products:
        topic_labels = list(products[:2])
    if not topic_labels and pain_matches and platforms:
        topic_labels = [f"{platforms[0]} {pain_matches[0]}"]
    evidence_ids = ("post",)
    claim_text = str(thread.post.title or thread.post.body or "").strip()[:500]
    claims = (EvidenceClaim(claim_text, evidence_ids, (thread.post.url,), "supported"),) if claim_text else ()

    def field(value: str, status: str = "fact") -> AnalysisField:
        return AnalysisField(value=value, evidence_ids=evidence_ids, status=status)

    pains = tuple(field(value) for value in pain_matches[:5])
    # Needs, gaps and opportunity directions are synthesized later from the
    # actual sentences across the topic.  Do not inject a generic claim for
    # every post at extraction time.
    needs = ()
    solutions = tuple(field(value) for value in solution_matches[:5])
    gaps = ()
    hypotheses = ()
    sentiment = field("negative", "inference") if pains else field("neutral", "inference")
    return PostAnalysis(
        topics=tuple(TopicCandidate(label, evidence_ids) for label in dict.fromkeys(topic_labels[:3])),
        claims=claims,
        platform=field(platforms[0]) if platforms else AnalysisField(),
        vehicle=field(vehicles[0]) if vehicles else AnalysisField(),
        scenario=field(scenarios[0]) if scenarios else AnalysisField(),
        goal=field(goal_matches[0]) if goal_matches else AnalysisField(),
        pain_points=pains,
        needs=needs,
        current_solutions=solutions,
        gaps=gaps,
        opportunity_hypotheses=hypotheses,
        products=tuple(field(value) for value in products[:8]),
        brands=tuple(field(value) for value in brands[:8]),
        purchase_intent=tuple(field(value, "inference") for value in goal_matches[:4]),
        sentiment=sentiment,
        keyword_candidates=tuple(field(value) for value in (*products[:4], *pain_matches[:4])),
        topic_candidates=tuple(field(value) for value in topic_labels[:3]),
    )
