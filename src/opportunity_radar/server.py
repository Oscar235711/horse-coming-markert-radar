"""Localhost task page and JSON API for Opportunity Radar runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
from threading import RLock, Thread
from threading import Event
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
import webbrowser

from .models import CollectionScope
from .dashboard import dashboard_html
from .library import active_keywords, load_project_library
from .config import load_diesel_domain_config


FIXED_COMMUNITIES = ("Cummins", "Duramax", "powerstroke", "FordDiesels")


class RunManager:
    """Serialize Chrome-backed collections and expose secret-free run state."""

    def __init__(
        self,
        *,
        app: Any,
        config_path: str | Path,
        runs_root: str | Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._app = app
        self._config_path = str(config_path)
        self._runs_root = Path(runs_root).resolve()
        self._runs_root.mkdir(parents=True, exist_ok=True)
        self._now = now or datetime.now
        self._lock = RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, Thread] = {}
        self._cancel_events: dict[str, Event] = {}

    def create_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        mode, scope, communities, engine, keywords, focus = self._validate_payload(payload)
        with self._lock:
            if any(
                self._is_active_state(state)
                for state in self._states.values()
            ):
                raise RuntimeError("已有Reddit采集任务正在运行，请等待完成后再启动。")
            run_id = self._now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
            state = {
                "run_id": run_id,
                "mode": mode,
                "status": "queued",
                "stage": "queued",
                "start_date": scope.start_date.isoformat() if scope else None,
                "end_date": scope.end_date.isoformat() if scope else None,
                "depth": scope.depth if scope else "hot30",
                "analysis_engine": engine,
                "focus": focus,
                # Keep the legacy state field for API clients and older runs.
                "research_question": focus,
                "selected_communities": list(communities),
                "selected_keywords": list(keywords),
                "counts": {},
                "artifacts": {},
                "failures": [],
            }
            self._states[run_id] = state
            self._cancel_events[run_id] = Event()
            thread = Thread(
                target=self._execute,
                args=(run_id, mode, scope, communities, engine, keywords, focus),
                name=f"radar-{run_id}",
                daemon=True,
            )
            self._threads[run_id] = thread
            thread.start()
            return dict(state)

    def resume_run(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        with self._lock:
            if any(self._is_active_state(state) for state in self._states.values()):
                raise RuntimeError("已有Reddit采集任务正在运行，请等待完成后再继续。")
            state = self.snapshot(run_id)
            self._cancel_events.setdefault(run_id, Event()).clear()
            state["status"] = "queued"
            state["stage"] = "resume_queued"
            self._states[run_id] = state
            target = self._resume_hot30 if state.get("mode") == "hot30" else self._resume
            thread = Thread(target=target, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
            thread.start()
            return dict(state)

    def list_runs(self) -> list[dict[str, Any]]:
        run_ids = set(self._states)
        run_ids.update(path.name for path in self._runs_root.iterdir() if path.is_dir())
        rows = []
        for run_id in sorted(run_ids, reverse=True):
            try:
                rows.append(self.snapshot(run_id))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
        return rows

    def snapshot(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        with self._lock:
            memory = dict(self._states.get(run_id, {}))
        state_path = self._runs_root / run_id / "state.json"
        if state_path.exists():
            disk = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(disk, Mapping):
                memory = {**memory, **dict(disk)}
        if not memory:
            raise FileNotFoundError(run_id)
        # A browser/server restart cannot keep an in-memory worker alive. Do
        # not leave a stale disk snapshot looking like an active task that
        # blocks the whole dashboard; the saved checkpoints remain resumable.
        worker = self._threads.get(run_id)
        cancel_event = self._cancel_events.get(run_id)
        if cancel_event is not None and cancel_event.is_set():
            memory["status"] = "interrupted"
            memory["stage"] = "cancelled"
            memory.setdefault("progress", {})["message"] = "任务已取消，已保留检查点，可按需续跑。"
        if (
            memory.get("status") in {"running", "queued"}
            and memory.get("stage") != "hot30_adapter_unavailable"
            and (worker is None or not worker.is_alive())
        ):
            memory["status"] = "interrupted"
            memory["stage"] = "interrupted"
            memory.setdefault("failures", []).append({"stage": "server", "message": "本地服务重启，任务已暂停；可从检查点续跑。"})
        # Older CLI runs only write state after the whole collection pass.
        # Derive a best-effort live milestone from checkpoint files so the
        # browser can still show useful progress while that pass is running.
        memory = self._with_live_progress(memory, self._runs_root / run_id)
        return self._with_available_artifacts(memory)

    @staticmethod
    def _with_available_artifacts(state: dict[str, Any]) -> dict[str, Any]:
        """Expose only local artifact files the browser can actually open."""
        artifacts = state.get("artifacts")
        if not isinstance(artifacts, Mapping):
            return state
        state["artifacts"] = {
            str(name): str(path)
            for name, path in artifacts.items()
            if isinstance(path, (str, Path)) and str(path) and Path(path).is_file()
        }
        return state

    @staticmethod
    def _with_live_progress(state: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        if state.get("status") not in {"queued", "running"} or state.get("progress"):
            return state
        selected = state.get("selected_communities")
        communities = selected if isinstance(selected, list) and selected else list(FIXED_COMMUNITIES)
        scope = state.get("collection_scope") if isinstance(state.get("collection_scope"), Mapping) else {}
        depth = str(scope.get("depth", state.get("depth", "complete")))
        per_community = {"quick": 30, "standard": 80, "deep": 150}.get(depth)
        listings = list((run_dir / "raw" / "listings").glob("*.json"))
        threads = list((run_dir / "raw" / "threads").glob("*.json"))
        if threads:
            total = max(1, per_community * len(communities)) if per_community is not None else 0
            state["stage"] = "deep_read"
            state["progress"] = {
                "stage": "deep_read",
                "completed": min(len(threads), total) if total else len(threads),
                "total": total,
                "message": (
                    f"已获取 {min(len(threads), total)}/{total} 篇深读。"
                    if total else f"完整模式已获取 {len(threads)} 篇深读，继续至日期/平台边界。"
                ),
            }
            counts = dict(state.get("counts", {})) if isinstance(state.get("counts"), Mapping) else {}
            counts["deep_read_count"] = max(int(counts.get("deep_read_count", 0) or 0), len(threads))
            state["counts"] = counts
        elif listings:
            state["stage"] = "collecting"
            state["progress"] = {
                "stage": "collecting",
                "completed": min(len(listings), len(communities)),
                "total": len(communities),
                "message": "社区列表已返回，正在准备深读。",
            }
        return state

    def wait(self, run_id: str, *, timeout: float | None = None) -> None:
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout=timeout)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Cancel an active run, terminate its external work, and keep checkpoints."""
        self._validate_run_id(run_id)
        with self._lock:
            state = self.snapshot(run_id)
            if state.get("status") not in {"queued", "running", "interrupted"}:
                raise RuntimeError("只有排队中、运行中或已暂停的任务可以取消。")
            event = self._cancel_events.setdefault(run_id, Event())
            event.set()
            state["status"] = "interrupted"
            state["stage"] = "cancelled"
            state["cancel_requested"] = True
            state["progress"] = {
                **(state.get("progress") if isinstance(state.get("progress"), dict) else {}),
                "stage": "cancelled",
                "message": "任务已取消，已保留检查点，可按需续跑。",
            }
            self._states[run_id] = state
            self._persist_state(run_id, state)
            request_cancel = getattr(self._app, "request_cancel", None)
        if callable(request_cancel):
            request_cancel(run_id)
        return dict(state)

    def delete_run(self, run_id: str) -> None:
        """Delete one completed/failed/interrupted local run and its artifacts."""
        self._validate_run_id(run_id)
        with self._lock:
            state = self.snapshot(run_id)
            if self._is_active_state(state):
                raise RuntimeError("运行中的任务不能删除，请先等待或停止任务。")
            target = (self._runs_root / run_id).resolve()
            if target.parent != self._runs_root:
                raise ValueError("invalid run id")
            # A lightweight test/app may only have an in-memory state. In
            # that case deleting the state is still a valid no-op on disk.
            if target.is_dir():
                shutil.rmtree(target)
            self._states.pop(run_id, None)
            self._threads.pop(run_id, None)
            self._cancel_events.pop(run_id, None)

    def artifact_path(self, run_id: str, name: str) -> Path:
        state = self.snapshot(run_id)
        artifact_keys = {
            "report_html": "report_html",
            "analysis_json": "analysis_json",
            "workbook": "community_topics_xlsx",
            "brief_html": "brief_html",
            "brief_md": "brief_md",
            "trends": "trends",
            "source_status": "source_status",
        }
        if name not in artifact_keys:
            raise ValueError("unknown artifact")
        configured = state.get("artifacts", {}).get(artifact_keys[name]) if isinstance(state.get("artifacts"), Mapping) else None
        fallback_names = {
            "report_html": "report.html",
            "analysis_json": "analysis.json",
            "workbook": "community_topics.xlsx",
            "brief_html": "brief.html",
            "brief_md": "brief.md",
            "trends": "trends.json",
            "source_status": "source_status.json",
        }
        target = Path(str(configured)) if configured else self._runs_root / run_id / "artifacts" / fallback_names[name]
        target = target.resolve()
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target

    def _execute(
        self,
        run_id: str,
        mode: str,
        scope: CollectionScope | None,
        communities: tuple[str, ...],
        engine: str,
        keywords: tuple[str, ...] = (),
        focus: str = "",
    ) -> None:
        if mode == "hot30":
            self._execute_hot30(run_id, focus)
            return
        assert scope is not None
        self._set_state(run_id, status="running", stage="configured")
        try:
            result = self._app.run(
                self._config_path,
                run_id=run_id,
                scope=scope,
                analysis_engine=engine,
                selected_communities=communities,
                selected_keywords=keywords,
                research_question=focus,
            )
            if self._is_cancelled(run_id):
                self._mark_interrupted(run_id)
            else:
                self._replace_state(run_id, result)
        except Exception as error:
            if self._is_cancelled(run_id):
                self._mark_interrupted(run_id)
            else:
                self._set_state(
                    run_id,
                    status="failed",
                    stage="failed",
                    failures=[{"stage": "run", "message": f"{type(error).__name__}: {error}"}],
                )

    def _execute_hot30(self, run_id: str, topic: str) -> None:
        """Run the optional local multi-platform adapter without coupling Reddit runs to it."""
        self._set_state(
            run_id,
            status="running",
            stage="hot30_configured",
            progress={"stage": "hot30_configured", "message": "正在准备近30天多平台热点研究。"},
        )
        try:
            from .last30days_adapter import Last30DaysAdapter
        except ImportError:
            # Keep a visible configuration hint but do not count this dormant
            # optional integration as the active Chrome-backed Reddit worker.
            self._set_state(
                run_id,
                status="queued",
                stage="hot30_adapter_unavailable",
                progress={
                    "stage": "hot30_adapter_unavailable",
                    "message": "近30天多平台适配器尚未就绪；请完成本地 last30days 配置后重试。",
                },
            )
            return
        try:
            output_dir = self._runs_root / run_id / "artifacts"
            result = Last30DaysAdapter().run_hot30(
                topic,
                output_dir,
                emit="compact",
                cancel_event=self._cancel_events.get(run_id),
            )
            if not isinstance(result, Mapping):
                raise ValueError("Last30DaysAdapter 必须返回 JSON 对象")
            normalized = dict(result)
            artifacts = normalized.get("artifacts")
            if isinstance(artifacts, Mapping):
                normalized["artifacts"] = dict(artifacts)
            if self._is_cancelled(run_id):
                self._mark_interrupted(run_id)
            else:
                self._replace_state(run_id, normalized)
                self._persist_state(run_id, self._states[run_id])
        except Exception as error:
            if self._is_cancelled(run_id):
                self._mark_interrupted(run_id)
            else:
                self._set_state(
                    run_id,
                    status="failed",
                    stage="failed",
                    failures=[{"stage": "hot30", "message": f"{type(error).__name__}: {error}"}],
                )

    def _resume(self, run_id: str) -> None:
        self._set_state(run_id, status="running", stage="resuming")
        try:
            result = self._app.resume(run_id)
            if self._is_cancelled(run_id):
                self._mark_interrupted(run_id)
            else:
                self._replace_state(run_id, result)
        except Exception as error:
            if self._is_cancelled(run_id):
                self._mark_interrupted(run_id)
            else:
                self._set_state(run_id, status="failed", stage="failed", failures=[{"stage": "resume", "message": str(error)}])

    def _resume_hot30(self, run_id: str) -> None:
        """Retry the same multi-platform topic in its existing run directory."""
        state = self.snapshot(run_id)
        self._execute_hot30(run_id, str(state.get("focus") or state.get("research_question") or "北美柴油皮卡改装"))

    def _replace_state(self, run_id: str, result: Mapping[str, Any]) -> None:
        with self._lock:
            prior = self._states.get(run_id, {})
            self._states[run_id] = {**prior, **dict(result)}

    def _set_state(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            self._states[run_id] = {**self._states.get(run_id, {"run_id": run_id}), **changes}

    def _is_cancelled(self, run_id: str) -> bool:
        event = self._cancel_events.get(run_id)
        return event is not None and event.is_set()

    @staticmethod
    def _is_active_state(state: Mapping[str, Any]) -> bool:
        return (
            state.get("status") in {"queued", "running"}
            and state.get("stage") != "hot30_adapter_unavailable"
        )

    def _mark_interrupted(self, run_id: str) -> None:
        with self._lock:
            state = {**self._states.get(run_id, {}), "status": "interrupted", "stage": "cancelled", "cancel_requested": True}
            state["progress"] = {
                **(state.get("progress") if isinstance(state.get("progress"), dict) else {}),
                "stage": "cancelled",
                "message": "任务已取消，已保留检查点，可按需续跑。",
            }
            self._states[run_id] = state
            self._persist_state(run_id, state)

    def _persist_state(self, run_id: str, state: Mapping[str, Any]) -> None:
        path = self._runs_root / run_id / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _validate_payload(self, payload: Mapping[str, Any]) -> tuple[str, CollectionScope | None, tuple[str, ...], str, tuple[str, ...], str]:
        mode = str(payload.get("mode", "range")).casefold().strip()
        if mode not in {"range", "hot30"}:
            raise ValueError("mode 必须是 range 或 hot30。")
        raw_focus = payload.get("focus", payload.get("research_question", ""))
        if raw_focus is not None and not isinstance(raw_focus, str):
            raise ValueError("focus 必须是文本。")
        focus = " ".join(str(raw_focus or "").split()).strip()
        if len(focus) > 500:
            raise ValueError("focus 最多 500 个字符。")
        if mode == "hot30":
            scope = None
            if not focus:
                focus = "北美柴油皮卡改装"
        else:
            try:
                scope = CollectionScope(
                    date.fromisoformat(str(payload["start_date"])),
                    date.fromisoformat(str(payload["end_date"])),
                    str(payload.get("depth", "complete")),
                )
            except (KeyError, ValueError) as error:
                raise ValueError(f"无效采集日期或深度：{error}") from error
            if scope.end_date > self._now().date():
                raise ValueError("结束日期不能晚于今天。")
            # Older API clients omit the question. Preserve their established
            # default while treating focus as optional in the range UI.
            if not focus:
                focus = "柴油皮卡改装市场机会扫描"
        raw_communities = payload.get("communities", list(FIXED_COMMUNITIES))
        if not isinstance(raw_communities, (list, tuple)) or not raw_communities:
            raise ValueError("至少选择一个社区。")
        canonical = {item.casefold(): item for item in FIXED_COMMUNITIES}
        requested = tuple(dict.fromkeys(str(item).strip() for item in raw_communities if str(item).strip()))
        unknown = [item for item in requested if item.casefold() not in canonical]
        if unknown:
            raise ValueError(f"不支持的社区：{', '.join(unknown)}")
        communities = tuple(canonical[item.casefold()] for item in requested)
        engine = str(payload.get("analysis_engine", "deepseek"))
        if engine not in {"codex", "deepseek", "rules", "legacy"}:
            raise ValueError("分析方式必须是 deepseek、codex 或 rules。")
        raw_keywords = payload.get("keywords", [])
        if not isinstance(raw_keywords, (list, tuple)):
            raise ValueError("关键词必须是数组。")
        keywords = tuple(dict.fromkeys(" ".join(str(item).split()) for item in raw_keywords if str(item).strip()))
        return mode, scope, communities, engine, keywords, focus

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("invalid run id")


class ScheduleManager:
    """Persist and execute rolling Reddit jobs while the local server is open."""

    def __init__(self, run_manager: RunManager, path: str | Path, *, now: Callable[[], datetime] | None = None) -> None:
        self._runs = run_manager
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now().astimezone())
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._items: list[dict[str, Any]] = self._load()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="radar-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items]

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        item = self._validate(payload)
        item["schedule_id"] = "sch-" + uuid4().hex[:10]
        item["created_at"] = self._now().isoformat()
        item["next_run_at"] = self._next_run(self._now(), item["frequency"], item["at_time"]).isoformat()
        with self._lock:
            self._items.append(item)
            self._save()
        return dict(item)

    def toggle(self, schedule_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._find(schedule_id)
            item["enabled"] = not bool(item.get("enabled", True))
            if item["enabled"]:
                item["next_run_at"] = self._next_run(self._now(), item["frequency"], item["at_time"]).isoformat()
            self._save()
            return dict(item)

    def delete(self, schedule_id: str) -> None:
        with self._lock:
            before = len(self._items)
            self._items[:] = [item for item in self._items if item.get("schedule_id") != schedule_id]
            if len(self._items) == before:
                raise KeyError(schedule_id)
            self._save()

    def _loop(self) -> None:
        while not self._stop.wait(15):
            self._run_due()

    def _run_due(self) -> None:
        now = self._now()
        due: list[dict[str, Any]] = []
        with self._lock:
            for item in self._items:
                if not item.get("enabled", True):
                    continue
                try:
                    next_run = datetime.fromisoformat(str(item.get("next_run_at", "")))
                except ValueError:
                    next_run = now + timedelta(days=1)
                if next_run <= now:
                    due.append(item)
            for item in due:
                item["next_run_at"] = self._next_run(now, item["frequency"], item["at_time"]).isoformat()
            if due:
                self._save()
        for item in due:
            try:
                end = now.date()
                start = end - timedelta(days=int(item["window_days"]) - 1)
                state = self._runs.create_run({
                    "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "depth": item["depth"], "analysis_engine": item.get("analysis_engine", "deepseek"),
                    "research_question": item.get("research_question", "柴油皮卡改装市场机会扫描"),
                    "communities": list(item["communities"]),
                    "keywords": list(item.get("keywords", [])),
                })
                with self._lock:
                    item["last_run_id"] = state.get("run_id")
                    item["last_started_at"] = now.isoformat()
                    item.pop("last_error", None)
                    self._save()
            except Exception as error:
                with self._lock:
                    item["last_error"] = f"{type(error).__name__}: {error}"
                    self._save()

    def _find(self, schedule_id: str) -> dict[str, Any]:
        for item in self._items:
            if item.get("schedule_id") == schedule_id:
                return item
        raise KeyError(schedule_id)

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _next_run(now: datetime, frequency: str, at_time: str) -> datetime:
        hour, minute = (int(value) for value in at_time.split(":", 1))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now:
            return candidate
        if frequency == "daily":
            return candidate + timedelta(days=1)
        if frequency == "weekly":
            return candidate + timedelta(days=7)
        # Monthly schedules run on the current day where possible, otherwise
        # on the last day of the following month.
        month = candidate.month + 1
        year = candidate.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        import calendar
        day = min(now.day, calendar.monthrange(year, month)[1])
        return candidate.replace(year=year, month=month, day=day)

    @staticmethod
    def _validate(payload: Mapping[str, Any]) -> dict[str, Any]:
        name = " ".join(str(payload.get("name", "未命名任务")).split())[:80] or "未命名任务"
        frequency = str(payload.get("frequency", "weekly")).casefold()
        if frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("frequency must be daily, weekly or monthly")
        at_time = str(payload.get("at_time", "09:00"))
        try:
            hour, minute = (int(value) for value in at_time.split(":", 1))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("定时时间必须是 HH:MM") from None
        try:
            window_days = int(payload.get("window_days", 90))
        except (TypeError, ValueError):
            raise ValueError("window_days 必须是 1 至 365") from None
        if not 1 <= window_days <= 365:
            raise ValueError("window_days 必须是 1 至 365")
        depth = str(payload.get("depth", "complete"))
        if depth not in {"quick", "standard", "deep", "complete"}:
            raise ValueError("不支持的采集深度")
        research_question = " ".join(str(payload.get("research_question", "")).split()).strip()
        if not research_question:
            research_question = "柴油皮卡改装市场机会扫描"
        raw_communities = payload.get("communities", list(FIXED_COMMUNITIES))
        if not isinstance(raw_communities, (list, tuple)) or not raw_communities:
            raise ValueError("至少选择一个社区")
        canonical = {item.casefold(): item for item in FIXED_COMMUNITIES}
        communities = tuple(dict.fromkeys(canonical[str(item).strip().casefold()] for item in raw_communities if str(item).strip() and str(item).strip().casefold() in canonical))
        if not communities:
            raise ValueError("至少选择一个有效社区")
        keywords = payload.get("keywords", [])
        if not isinstance(keywords, (list, tuple)):
            raise ValueError("keywords 必须是数组")
        clean_keywords = list(dict.fromkeys(" ".join(str(item).split()) for item in keywords if str(item).strip()))
        analysis_engine = str(payload.get("analysis_engine", "deepseek"))
        if analysis_engine not in {"deepseek", "codex", "rules", "legacy"}:
            raise ValueError("分析方式必须是 deepseek、codex 或 rules")
        return {"name": name, "research_question": research_question, "frequency": frequency, "at_time": f"{hour:02d}:{minute:02d}", "window_days": window_days, "depth": depth, "analysis_engine": analysis_engine, "communities": list(communities), "keywords": clean_keywords, "enabled": True}


def build_server(
    manager: RunManager,
    *,
    schedule_manager: ScheduleManager | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path == "/":
                    library_root = getattr(manager._app, "_library_root", None)
                    keywords = active_keywords(library_root) if library_root else ()
                    if not keywords:
                        try:
                            domain = load_diesel_domain_config(manager._config_path)
                            keywords = tuple(dict.fromkeys((*domain.dictionaries.platforms, *domain.dictionaries.products)))
                        except (OSError, ValueError):
                            keywords = ()
                    return self._html(dashboard_html(FIXED_COMMUNITIES, keywords))
                if path == "/api/runs":
                    return self._json({"runs": manager.list_runs()})
                if path == "/api/schedules":
                    return self._json({"schedules": schedule_manager.list() if schedule_manager else []})
                if path == "/api/libraries":
                    library_root = getattr(manager._app, "_library_root", None)
                    library = load_project_library(library_root) if library_root else {"communities": [], "keywords": [], "topics": []}
                    return self._json({
                        "communities": library.get("communities", []),
                        "keywords": library.get("keywords", []),
                        "topics": library.get("topics", []),
                        "active_keyword_count": len(active_keywords(library_root)) if library_root else 0,
                    })
                parts = [part for part in path.split("/") if part]
                if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                    return self._json(manager.snapshot(parts[2]))
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "analysis":
                    return self._file(manager.artifact_path(parts[2], "analysis_json"), "application/json; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "report":
                    return self._file(manager.artifact_path(parts[1], "report_html"), "text/html; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "workbook":
                    return self._file(manager.artifact_path(parts[1], "workbook"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "brief":
                    return self._file(manager.artifact_path(parts[1], "brief_html"), "text/html; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "brief.md":
                    return self._file(manager.artifact_path(parts[1], "brief_md"), "text/markdown; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "trends":
                    return self._file(manager.artifact_path(parts[1], "trends"), "application/json; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "source-status":
                    return self._file(manager.artifact_path(parts[1], "source_status"), "application/json; charset=utf-8")
                return self._error(HTTPStatus.NOT_FOUND, "页面不存在")
            except FileNotFoundError:
                return self._error(HTTPStatus.NOT_FOUND, "任务或产物不存在")
            except ValueError as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path == "/api/runs":
                    return self._json(manager.create_run(self._read_json()), status=HTTPStatus.ACCEPTED)
                if path == "/api/schedules":
                    if schedule_manager is None:
                        return self._error(HTTPStatus.NOT_FOUND, "定时任务未启用")
                    return self._json(schedule_manager.create(self._read_json()), status=HTTPStatus.ACCEPTED)
                parts = [part for part in path.split("/") if part]
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "resume":
                    return self._json(manager.resume_run(parts[2]), status=HTTPStatus.ACCEPTED)
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
                    return self._json(manager.cancel_run(parts[2]), status=HTTPStatus.ACCEPTED)
                if len(parts) == 4 and parts[:2] == ["api", "schedules"] and parts[3] == "toggle":
                    if schedule_manager is None:
                        return self._error(HTTPStatus.NOT_FOUND, "定时任务未启用")
                    return self._json(schedule_manager.toggle(parts[2]))
                return self._error(HTTPStatus.NOT_FOUND, "接口不存在")
            except RuntimeError as error:
                return self._error(HTTPStatus.CONFLICT, str(error))
            except (ValueError, json.JSONDecodeError) as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            parts = [part for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                try:
                    manager.delete_run(parts[2])
                    return self._json({"status": "deleted", "run_id": parts[2]})
                except FileNotFoundError:
                    return self._error(HTTPStatus.NOT_FOUND, "任务不存在")
                except RuntimeError as error:
                    return self._error(HTTPStatus.CONFLICT, str(error))
                except ValueError as error:
                    return self._error(HTTPStatus.BAD_REQUEST, str(error))
            if len(parts) == 3 and parts[:2] == ["api", "schedules"] and schedule_manager is not None:
                try:
                    schedule_manager.delete(parts[2])
                    return self._json({"status": "deleted", "schedule_id": parts[2]})
                except KeyError:
                    return self._error(HTTPStatus.NOT_FOUND, "定时任务不存在")
            return self._error(HTTPStatus.NOT_FOUND, "接口不存在")

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _read_json(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("请求必须是JSON对象")
            return value

        def _json(self, value: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def _html(self, value: str) -> None:
            self._send(value.encode("utf-8"), "text/html; charset=utf-8", HTTPStatus.OK)

        def _file(self, path: Path, content_type: str) -> None:
            self._send(path.read_bytes(), content_type, HTTPStatus.OK)

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._json({"status": "error", "message": message}, status=status)

        def _send(self, body: bytes, content_type: str, status: HTTPStatus) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def serve_local(
    app: Any,
    *,
    config_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> dict[str, Any]:
    runs_root = getattr(app, "runs_root", Path.cwd() / ".local" / "runs")
    manager = RunManager(app=app, config_path=config_path, runs_root=runs_root)
    schedule_manager = ScheduleManager(manager, Path(runs_root).parent / "schedules.json")
    schedule_manager.start()
    server = build_server(manager, schedule_manager=schedule_manager, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        schedule_manager.stop()
    return {"status": "stopped", "url": url}


def _dashboard_html() -> str:
    communities = "".join(
        f'<label class="community"><input type="checkbox" name="community" value="{name}" checked> r/{name}</label>'
        for name in FIXED_COMMUNITIES
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Opportunity Radar</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f0ea;color:#24211e;font:14px system-ui,sans-serif}}main{{max-width:1080px;margin:0 auto;padding:38px 22px}}h1{{font:700 34px Georgia,serif;margin:0}}.sub{{color:#756f67;margin:8px 0 28px}}.panel{{background:#fff;border:1px solid #ded8cf;border-radius:16px;padding:22px;box-shadow:0 14px 35px #675b4a12}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.field label.title{{display:block;font-weight:650;margin-bottom:8px}}input[type=date],select{{width:100%;padding:11px;border:1px solid #d8d1c7;border-radius:9px;background:#fff}}.presets{{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}}button{{border:0;border-radius:9px;padding:10px 14px;cursor:pointer}}.preset{{background:#eee9e2;color:#5f584f}}.primary{{background:#d76d28;color:#fff;font-weight:700;font-size:15px}}.communities{{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}}.community{{padding:10px;border:1px solid #e3ddd5;border-radius:9px}}.actions{{display:flex;align-items:center;gap:12px;margin-top:20px}}#message{{color:#87602f}}.runs{{margin-top:24px}}.run{{background:#fff;border:1px solid #e0dad2;border-radius:12px;padding:15px;margin:9px 0;display:flex;justify-content:space-between;gap:15px}}.meta{{color:#787169;font-size:12px;margin-top:5px}}.progress{{color:#805a2d;font-size:12px;margin-top:5px}}.failure{{color:#a33f34;font-size:12px;margin-top:5px}}a{{color:#b85218;text-decoration:none;font-weight:650}}@media(max-width:700px){{.grid,.communities{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>Opportunity Radar</h1><div class="sub">选择社区和时间范围，OpenCLI 采集 Reddit；Higress DeepSeek 负责中文 VOC 分析和话题归并。</div><section class="panel"><div class="grid"><div class="field"><label class="title">时间范围</label><div class="presets"><button class="preset" data-days="30">最近30天</button><button class="preset" data-days="90">最近90天</button><button class="preset" data-days="180">最近180天</button><button class="preset" data-days="365">最近365天</button></div><div class="grid"><input id="start" type="date"><input id="end" type="date"></div></div><div class="field"><label class="title">采集深度</label><select id="depth"><option value="quick">快速 · 30篇/社区</option><option value="standard" selected>标准 · 80篇/社区</option><option value="deep">深度 · 150篇/社区</option><option value="complete">完整 · 按日期采完并深读全部相关帖</option></select><p class="meta">完整模式不设项目数量上限；遇到Reddit不再返回下一页、日期边界、限流或取消时停止，并显示实际覆盖情况。</p></div><div class="field"><label class="title">种子社区</label><div class="communities">{communities}</div><p class="meta">任务还会用关键词库做全站检索，并把有足够证据的新社区写入社区库。</p></div><div class="field"><label class="title">分析方式</label><select id="analysis-engine"><option value="deepseek" selected>Higress DeepSeek · 中文 VOC（推荐）</option><option value="codex">本机 Codex · 中文 VOC</option></select><p class="meta">采集仍由 OpenCLI 完成；DeepSeek 只接收已保存的帖子和评论，不访问 Reddit 页面。</p></div></div><div class="actions"><button id="start-run" class="primary">开始采集并分析</button><span id="message"></span></div></section><section class="runs"><h2>任务记录</h2><div id="runs"></div></section></main><script>
const iso=d=>d.toISOString().slice(0,10);function preset(days){{const end=new Date(),start=new Date();start.setDate(end.getDate()-days+1);document.querySelector('#start').value=iso(start);document.querySelector('#end').value=iso(end)}}document.querySelectorAll('[data-days]').forEach(b=>b.onclick=()=>preset(Number(b.dataset.days)));preset(90);
async function refresh(){{const data=await fetch('/api/runs').then(r=>r.json());document.querySelector('#runs').innerHTML=(data.runs||[]).map(r=>`<div class="run"><div><b>${{r.run_id}}</b><div class="meta">${{r.start_date||r.collection_scope?.start_date||''}} → ${{r.end_date||r.collection_scope?.end_date||''}} · ${{r.depth||r.collection_scope?.depth||''}} · ${{r.stage||''}}</div><div class="progress">${{r.progress?.message||''}} ${{r.progress?.total?`(${{r.progress.completed||0}}/${{r.progress.total}})`:''}}</div><div class="failure">${{(r.failures||[]).slice(0,2).map(f=>f.message||f.stage).join('；')}}</div></div><div>${{r.status==='completed'?`<a href="/runs/${{r.run_id}}/report">打开报告</a> · <a href="/runs/${{r.run_id}}/workbook">下载Excel</a>`:r.status}}</div></div>`).join('')||'<div class="meta">尚无任务</div>'}}
document.querySelector('#start-run').onclick=async()=>{{const message=document.querySelector('#message');message.textContent='正在创建任务…';const payload={{start_date:document.querySelector('#start').value,end_date:document.querySelector('#end').value,depth:document.querySelector('#depth').value,analysis_engine:document.querySelector('#analysis-engine').value,communities:[...document.querySelectorAll('[name=community]:checked')].map(x=>x.value)}};const response=await fetch('/api/runs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});const result=await response.json();message.textContent=response.ok?'任务已启动，可在下方查看进度':result.message;refresh()}};refresh();setInterval(refresh,2500);
</script></body></html>"""
