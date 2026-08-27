"""Task 4 application services for CLI orchestration and governance."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
import importlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import yaml

from .config import load_community_catalog, load_config, write_community_catalog
from .collector import CollectionFailure, OpenCliCollector, ThreadDocument
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
)
from .models import Community, CommunityCatalog, RadarConfig, RunManifest
from .storage import TopicRegistry, create_run_paths, read_manifest, write_manifest
from .topics import (
    EvidenceBackedClaim,
    ProTopicProposal,
    TopicAggregationResult,
    TopicAggregator,
    TopicEvidence,
    TopicExportArtifacts,
    export_topic_analysis,
)


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
        environment: Mapping[str, str] | None = None,
        tool_runner: ToolRunner | None = None,
        collector: OpenCliCollector | None = None,
        flash_client: FlashClient | None = None,
        pro_consolidator: Any | None = None,
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
        self._tool_runner = tool_runner or self._default_tool_runner
        self._has_custom_tool_runner = tool_runner is not None
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
        self._exporter = exporter or self._default_exporter
        self._now = now or (lambda: datetime.now(UTC))

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
            },
        }
        self._runs_root.mkdir(parents=True, exist_ok=True)
        self._config_versions_root.mkdir(parents=True, exist_ok=True)

        tool_paths = {
            "agent_reach": self._find_executable("RADAR_AGENT_REACH_EXE", "agent-reach"),
            "opencli": self._find_executable("RADAR_OPENCLI_EXE", "opencli"),
            "node": self._find_executable("RADAR_NODE_EXE", "node"),
        }
        checks["tools"] = {
            name: {"status": "ok" if path else "warning", "path": str(path) if path else ""}
            for name, path in tool_paths.items()
        }

        catalog = self._approved_catalog()
        checks["reddit"] = self._reddit_checks(catalog.communities)
        if checks["reddit"]["status"] != "ok":
            warnings.append("Reddit 采集环境未完全就绪：请检查 OpenCLI 登录态和社区访问。")

        deepseek = {
            "status": "ok",
            "base_url": self._deepseek_base_url(),
            "flash_model": self._deepseek_flash_model(),
            "pro_model": self._deepseek_pro_model(),
            "has_key": bool(self._environment.get("DEEPSEEK_API_KEY")),
        }
        if not deepseek["has_key"]:
            deepseek["status"] = "warning"
            warnings.append("未设置 DEEPSEEK_API_KEY；doctor 继续执行 Reddit 检查，但 run/resume 需要该配置。")
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

    def run(self, config_path: str | Path, *, run_id: str | None = None) -> dict[str, Any]:
        """Start a new run and persist resumable state under one run directory."""
        resolved_config = self._resolve_path(config_path)
        config = load_config(resolved_config)
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
        state["completed_stages"] = ["configured"]
        self._write_state(paths.state_path, state)
        return self._continue_run(paths, config, state)

    def resume(self, run_id: str) -> dict[str, Any]:
        """Continue a previously incomplete run from its saved checkpoints."""
        paths = create_run_paths(self._runs_root, run_id)
        state = self._read_state(paths.state_path)
        config = load_config(paths.config_snapshot_path)
        return self._continue_run(paths, config, state)

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

    def _continue_run(self, paths: Any, config: RadarConfig, state: dict[str, Any]) -> dict[str, Any]:
        collection = self._collector.collect(
            config.communities,
            paths=paths,
            as_of=self._now(),
            deep_read=True,
            shortlist_limit=config.shortlist_per_community,
        )
        state["counts"]["community_count"] = len(config.communities)
        state["counts"]["candidate_count"] = len(collection.candidates)
        state["counts"]["shortlist_count"] = len(collection.shortlisted)
        state["counts"]["deep_read_count"] = len(collection.deep_reads)
        state["completed_stages"] = self._merge_stages(state["completed_stages"], "configured", "collected")
        state["failures"] = [self._failure_to_dict(failure) for failure in collection.failures]

        analyses_by_post = self._load_saved_analyses(paths)
        flash_failures: list[CollectionFailure] = []
        for thread in collection.deep_reads:
            if thread.post.post_id in analyses_by_post:
                continue
            try:
                analysis = self._flash_client.extract_post(thread)
                analyses_by_post[thread.post.post_id] = analysis
                self._write_analysis_checkpoint(paths, thread.post.post_id, analysis)
            except Exception as error:
                flash_failures.append(
                    CollectionFailure(
                        community=thread.post.subreddit,
                        post_id=thread.post.post_id,
                        stage="flash_extract",
                        message=f"{type(error).__name__}: external operation failed",
                    )
                )
                self._write_failed_analysis_checkpoint(paths, thread.post.post_id, flash_failures[-1].message)

        state["counts"]["analyzed_posts"] = len(analyses_by_post)
        state["counts"]["failure_count"] = len(collection.failures) + len(flash_failures)
        state["failures"].extend(self._failure_to_dict(failure) for failure in flash_failures)
        if flash_failures:
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

        analysis = self._aggregate_run(config, collection.deep_reads, analyses_by_post)
        exported = self._invoke_exporter(paths.artifacts_dir, analysis, ("json", "xlsx"))
        state["artifacts"] = self._artifact_map(exported, ("json", "xlsx"))
        state["stage"] = "exported"
        state["status"] = "completed"
        state["completed_stages"] = self._merge_stages(
            state["completed_stages"], "configured", "collected", "flash_extract", "topic_consolidation", "exported"
        )
        state["counts"]["topic_count"] = len(analysis.get("topics", []))
        state["counts"]["failure_count"] = len(collection.failures)
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

    def _aggregate_run(
        self,
        config: RadarConfig,
        threads: Sequence[ThreadDocument],
        analyses_by_post: Mapping[str, PostAnalysis],
    ) -> dict[str, Any]:
        registry = TopicRegistry(self._runs_root / ".topic-registry.json")
        combined_topics: list[dict[str, Any]] = []
        excluded_records: list[dict[str, str]] = []
        results: list[TopicAggregationResult] = []
        for community in config.communities:
            community_threads = tuple(thread for thread in threads if thread.post.subreddit.casefold() == community.name.casefold())
            community_analyses = tuple(analyses_by_post[thread.post.post_id] for thread in community_threads)
            if not community_threads:
                continue
            result = TopicAggregator(
                pro=self._pro_consolidator,
                registry=registry,
                as_of=self._now(),
            ).aggregate_threads(community.name, community_threads, community_analyses)
            results.append(result)
            combined_topics.extend(result.analysis.get("topics", []))
            excluded_records.extend(result.analysis.get("excluded_records", []))
        return {
            "analysis_version": "1.0",
            "generated_at": self._now().isoformat(),
            "communities": [community.name for community in config.communities],
            "topics": combined_topics,
            "excluded_records": excluded_records,
            "model_mode": getattr(self._pro_consolidator, "mode", "injected_pro"),
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
            report["whoami"] = {"status": "ok", "username": str(whoami.get("username", ""))}
        except Exception as error:
            report["status"] = "warning"
            report["whoami"] = {"status": "warning", "message": f"{type(error).__name__}: external operation failed"}
        for community in communities[:4]:
            try:
                self._tool_runner(
                    self._rewrite_opencli(
                        ("opencli", "reddit", "hot", community.name, "--limit", "1", "-f", "json", *_opencli_session_flags())
                    )
                )
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
        completed = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._repo_root,
        )
        return completed.stdout

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
            "analysis": {
                "topics": [asdict(topic) for topic in analysis.topics],
                "claims": [asdict(claim) for claim in analysis.claims],
            },
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
        return PostAnalysis(topics=topics, claims=claims)

    def _artifact_map(self, exported: TopicExportArtifacts, formats: Sequence[str]) -> dict[str, str]:
        artifact_map = {
            "analysis_json": str(exported.analysis_json),
            "community_topics_json": str(exported.community_topics_json),
        }
        if "xlsx" in formats:
            artifact_map["community_topics_xlsx"] = str(exported.workbook_path)
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
        unsupported = [value for value in requested if value not in {"json", "xlsx"}]
        if unsupported:
            raise ValueError(f"Unsupported export format: {unsupported[0]}")
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


class DeepSeekTopicConsolidator:
    """Use DeepSeek Pro to consolidate per-post signals into community topics."""

    mode = "deepseek_pro"

    def __init__(self, *, client: DeepSeekClient, model: str) -> None:
        self._client = client
        self._model = model

    def consolidate(self, community: str, signals: Sequence[Any]) -> Sequence[ProTopicProposal]:
        signal_payload = [
            {
                "post_id": signal.post.post_id,
                "title": signal.post.title,
                "subreddit": signal.post.subreddit,
                "topics": [topic.label for topic in signal.analysis.topics],
                "claims": [claim.claim for claim in signal.analysis.claims if claim.status == "supported"],
                "evidence": signal.evidence_urls,
            }
            for signal in signals
        ]
        document = self._client.chat_json(
            (
                {"role": "system", "content": "You consolidate Reddit product signals into evidence-backed community topics."},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "community": community,
                            "signals": signal_payload,
                            "instruction": "Return JSON with topics[]. Each topic needs canonical_key, label_en, label_zh, post_ids, evidence, summary, category_tags, brand_tags, confidence.",
                        },
                        ensure_ascii=False,
                    ),
                },
            ),
            model=self._model,
        )
        proposals: list[ProTopicProposal] = []
        for item in document.get("topics", []) if isinstance(document.get("topics"), list) else []:
            if not isinstance(item, Mapping):
                continue
            post_ids = tuple(value for value in item.get("post_ids", []) if isinstance(value, str))
            evidence = tuple(
                TopicEvidence(
                    post_id=str(record.get("post_id", "")),
                    evidence_id=str(record.get("evidence_id", "")),
                    claim=str(record.get("claim", "")).strip(),
                    stance=str(record.get("stance", "supporting")),
                    translation_zh=str(record.get("translation_zh", "")).strip(),
                )
                for record in item.get("evidence", [])
                if isinstance(record, Mapping)
            )
            summary = item.get("summary", {})
            proposals.append(
                ProTopicProposal(
                    canonical_key=str(item.get("canonical_key", "")).strip(),
                    label_en=str(item.get("label_en", "")).strip(),
                    label_zh=str(item.get("label_zh", "")).strip(),
                    summary=EvidenceBackedClaim(
                        str(summary.get("text", "")).strip() if isinstance(summary, Mapping) else "",
                        evidence,
                    ),
                    post_ids=post_ids,
                    evidence=evidence,
                    category_tags=tuple(
                        value for value in item.get("category_tags", []) if isinstance(value, str)
                    ),
                    brand_tags=tuple(
                        value for value in item.get("brand_tags", []) if isinstance(value, str)
                    ),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                )
            )
        return proposals
