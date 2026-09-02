"""Project-local orchestration for the vendored ``last30days`` skill.

The adapter deliberately owns only filesystem boundaries and command assembly.
The vendored engine remains an unmodified snapshot; discovery retrieval is
performed only when a caller explicitly executes one of the returned commands.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request


DEFAULT_HOT30_DOMAIN = "North American diesel pickup aftermarket"


@dataclass(frozen=True)
class VendorPaths:
    """Locations in the checked-in last30days snapshot."""

    skill_dir: Path
    script_path: Path


@dataclass(frozen=True)
class Hot30RunPaths:
    """Per-run, project-controlled files for the three discovery legs."""

    root: Path
    work_dir: Path
    artifacts_dir: Path
    judgments_path: Path
    angles_path: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "work_dir": str(self.work_dir),
            "artifacts_dir": str(self.artifacts_dir),
            "judgments_path": str(self.judgments_path),
            "angles_path": str(self.angles_path),
        }


@dataclass(frozen=True)
class Hot30Artifacts:
    """Stable Radar-facing names projected from the engine's final report."""

    source_status: Path
    brief: Path
    trends: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "source_status": str(self.source_status),
            "brief": str(self.brief),
            "trends": str(self.trends),
        }


@dataclass(frozen=True)
class Hot30Commands:
    """The three engine commands for host-judged discovery."""

    nominate: tuple[str, ...]
    judge: tuple[str, ...]
    finalize: tuple[str, ...]

    def as_tuple(self) -> tuple[tuple[str, ...], ...]:
        return (self.nominate, self.judge, self.finalize)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "nominate": list(self.nominate),
            "judge": list(self.judge),
            "finalize": list(self.finalize),
        }


def project_root() -> Path:
    """Return the repository root without consulting a user skill directory."""
    return Path(__file__).resolve().parents[2]


def resolve_vendor_paths(root: Path | None = None) -> VendorPaths:
    """Resolve and validate the project-local engine entrypoint."""
    base = (root or project_root()).resolve()
    skill_dir = base / "vendor" / "last30days"
    script_path = skill_dir / "scripts" / "last30days.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Vendored last30days entrypoint is missing: {script_path}")
    return VendorPaths(skill_dir=skill_dir, script_path=script_path)


def _validate_run_id(run_id: str) -> str:
    cleaned = str(run_id or "").strip()
    candidate = Path(cleaned)
    if not cleaned or candidate.name != cleaned or cleaned in {".", ".."}:
        raise ValueError("run_id must be a single, non-empty path segment")
    return cleaned


def _json_file(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


Judge = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class Hot30Cancelled(RuntimeError):
    """The caller cancelled a running last30days command."""


class Hot30TimedOut(RuntimeError):
    """A last30days command exceeded the project-local deadline."""


class Hot30CommandFailed(RuntimeError):
    """A command exited unsuccessfully; its output is intentionally not persisted."""


class Hot30Adapter:
    """Assemble a project-scoped nominate -> judge -> finalize protocol.

    ``environment`` is read only for an optional caller-owned DeepSeek client.
    Secrets are neither added to command arguments nor serialized into run files.
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        runs_root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        python_executable: str | None = None,
        judge: Judge | None = None,
        command_timeout_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.vendor = resolve_vendor_paths(self._project_root)
        self.runs_root = (runs_root or self._project_root / "outputs" / "hot30").resolve()
        self.environment = dict(environment or {})
        self.python_executable = python_executable or sys.executable
        self._judge = judge
        self.command_timeout_seconds = max(0.1, float(command_timeout_seconds))
        self._clock = clock or time.monotonic

    def prepare_run(self, run_id: str) -> Hot30RunPaths:
        """Create an isolated run directory without writing configuration or keys."""
        root = self.runs_root / _validate_run_id(run_id)
        work_dir = root / "work"
        artifacts_dir = root / "artifacts"
        work_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return Hot30RunPaths(
            root=root,
            work_dir=work_dir,
            artifacts_dir=artifacts_dir,
            judgments_path=work_dir / "discover-judgments.json",
            angles_path=work_dir / "discover-angles.json",
        )

    def protocol_commands(
        self,
        run: Hot30RunPaths,
        *,
        domain: str = DEFAULT_HOT30_DOMAIN,
        emit: str = "brief",
    ) -> Hot30Commands:
        """Build safe argv tuples; the adapter does not launch them itself."""
        normalized_domain = " ".join(str(domain or "").split())
        base = (self.python_executable, str(self.vendor.script_path), "--discover")
        nominate = (*base, *( (normalized_domain,) if normalized_domain else () ), "--nominate-only", "--save-dir", str(run.work_dir))
        judge = (*base, "--judgments", str(run.judgments_path), "--save-dir", str(run.work_dir))
        finalize = (*base, "--finalize", "--angles", str(run.angles_path), f"--emit={emit}", "--save-dir", str(run.work_dir))
        return Hot30Commands(nominate=nominate, judge=judge, finalize=finalize)

    def deepseek_judge_request(self, nominations: Mapping[str, Any]) -> dict[str, Any]:
        """Return a DeepSeek-compatible JSON request without sending it.

        A configured HTTP client may submit this request and pass the parsed
        response to :meth:`write_judgments`; keeping that transport outside
        this adapter prevents credentials from entering the run directory.
        """
        return {
            "model": "deepseek-chat",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Judge discovery nominations. Return JSON only with bundle_id and judgments.",
                },
                {"role": "user", "content": json.dumps(nominations, ensure_ascii=False)},
            ],
        }

    def write_judgments(self, run: Hot30RunPaths, payload: Mapping[str, Any]) -> Path:
        """Persist host/DeepSeek judgments in the vendor handoff location."""
        return _json_file(run.judgments_path, payload)

    def write_angles(self, run: Hot30RunPaths, payload: Mapping[str, Any]) -> Path:
        """Persist host-written content angles for the finalization leg."""
        return _json_file(run.angles_path, payload)

    def judge_and_write(self, run: Hot30RunPaths, nominations: Mapping[str, Any], judge: Judge) -> Path:
        """Invoke an injected DeepSeek-compatible judge and write its JSON result."""
        return self.write_judgments(run, judge(self.deepseek_judge_request(nominations)))

    def project_finalize_output(
        self,
        run: Hot30RunPaths,
        *,
        brief: str,
        trends: Mapping[str, Any],
    ) -> Hot30Artifacts:
        """Project final output into stable artifact names for later UI work."""
        artifacts = Hot30Artifacts(
            source_status=run.artifacts_dir / "source_status.json",
            brief=run.artifacts_dir / "brief.md",
            trends=run.artifacts_dir / "trends.json",
        )
        _json_file(artifacts.source_status, dict(trends.get("source_status") or {}))
        _json_file(artifacts.trends, dict(trends))
        artifacts.brief.write_text(str(brief), encoding="utf-8")
        return artifacts

    @staticmethod
    def _write_html_brief(path: Path, brief: str) -> Path:
        """Render the engine's compact markdown as inert text in a local HTML view."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
            "<title>Hot 30 brief</title><body><pre>"
            f"{html.escape(brief)}"
            "</pre></body></html>",
            encoding="utf-8",
        )
        return path

    def _execution_environment(self, supplied: Mapping[str, str] | None) -> dict[str, str]:
        """Merge caller configuration only in memory for subprocesses and HTTPS."""
        merged = os.environ.copy()
        merged.update(self.environment)
        if supplied:
            merged.update({str(key): str(value) for key, value in supplied.items()})
        return merged

    @staticmethod
    def _stop_process(process: Any) -> None:
        """Terminate a child without exposing its stdout/stderr in an error path."""
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.communicate(timeout=1)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            process.kill()
        except OSError:
            return
        try:
            process.communicate(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _run_command(
        self,
        command: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        cancel_event: Event | None,
    ) -> str:
        """Run one protocol leg while observing cancellation and a bounded deadline."""
        if cancel_event is not None and cancel_event.is_set():
            raise Hot30Cancelled()
        process = subprocess.Popen(
            list(command),
            cwd=str(self.vendor.skill_dir),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = self._clock() + self.command_timeout_seconds
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._stop_process(process)
                raise Hot30Cancelled()
            remaining = deadline - self._clock()
            if remaining <= 0:
                self._stop_process(process)
                raise Hot30TimedOut()
            try:
                stdout, _stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0:
            # stderr can contain environment-dependent diagnostics. Keep the
            # persisted result safe and reproducible by recording only the code.
            raise Hot30CommandFailed(f"last30days exited with status {process.returncode}")
        return stdout

    @staticmethod
    def _read_object(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise Hot30CommandFailed(f"required handoff file was unavailable: {path.name}") from error
        if not isinstance(payload, dict):
            raise Hot30CommandFailed(f"required handoff file was not an object: {path.name}")
        return payload

    @staticmethod
    def _normalize_judgments(nominations: Mapping[str, Any], judged: Mapping[str, Any]) -> dict[str, Any]:
        rows = judged.get("judgments")
        return {
            "bundle_id": str(nominations.get("bundle_id") or ""),
            "judgments": [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else [],
        }

    @staticmethod
    def _model_angles(nominations: Mapping[str, Any], judged: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[str, Any]:
        """Keep only model supplied angle rows bound to surviving pending ids."""
        allowed = set((pending.get("angle_inputs") or {}).keys())
        rows = judged.get("angles")
        angles = [
            dict(row) for row in rows
            if isinstance(row, Mapping) and str(row.get("id") or "") in allowed
        ] if isinstance(rows, list) else []
        return {"bundle_id": str(nominations.get("bundle_id") or ""), "angles": angles}

    @staticmethod
    def _project_trends(nominations: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[str, Any]:
        """Deterministically expose only source evidence already present in handoffs."""
        report = pending.get("report")
        if not isinstance(report, Mapping):
            return {"status": "unknown", "trends": [], "reason": "pending_report_missing"}
        rows = nominations.get("nominations")
        if not isinstance(rows, list):
            return {"status": "unknown", "trends": [], "reason": "nomination_evidence_missing"}
        input_names = pending.get("angle_inputs")
        input_names = input_names if isinstance(input_names, Mapping) else {}
        cards: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identifier = str(row.get("id") or "")
            cluster_id = str(row.get("cluster_id") or "")
            nomination = row.get("nomination")
            items = nomination.get("items") if isinstance(nomination, Mapping) else None
            evidence = [
                {key: item[key] for key in ("url", "source", "title", "published_at") if key in item}
                for item in items if isinstance(item, Mapping) and item.get("url")
            ] if isinstance(items, list) else []
            if not identifier or not cluster_id or not evidence:
                continue
            name_hint = input_names.get(identifier)
            name = name_hint.get("name") if isinstance(name_hint, Mapping) else None
            if not name and isinstance(nomination, Mapping):
                name = nomination.get("name")
            cards.append({
                "id": identifier,
                "name": str(name or ""),
                "cluster_id": cluster_id,
                "evidence": evidence,
            })
        if not cards:
            return {"status": "unknown", "trends": [], "reason": "evidence_or_cluster_unavailable"}
        source_status = report.get("source_status")
        return {
            "status": "ok",
            "trends": cards,
            "source_status": dict(source_status) if isinstance(source_status, Mapping) else {},
        }

    @staticmethod
    def _http_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any]):
        from .deepseek import HttpResponse

        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return HttpResponse(response.status, response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read().decode("utf-8", errors="replace"))

    def _judge_nominations(self, nominations: Mapping[str, Any], environment: Mapping[str, str]) -> Mapping[str, Any]:
        if self._judge is not None:
            return self._judge(nominations)
        if not environment.get("DEEPSEEK_API_KEY"):
            raise Hot30CommandFailed("DeepSeek is not configured")
        from .deepseek import DeepSeekClient

        client = DeepSeekClient(transport=self._http_transport, environment=environment)
        response = client.chat_json((
            {"role": "system", "content": (
                "Judge the supplied discovery nominations. Return JSON only with a judgments list; "
                "each row has id, name, junk, worthiness. You may include an optional angles list "
                "with id, podcast, x_article. Never invent evidence."
            )},
            {"role": "user", "content": json.dumps(nominations, ensure_ascii=False)},
        ))
        return response


class Last30DaysAdapter(Hot30Adapter):
    """Execute the vendored, host-judged Hot 30 protocol for the local server."""

    def run_hot30(
        self,
        topic: str,
        output_dir: Path | str,
        env: Mapping[str, str] | None = None,
        emit: str = "compact",
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        artifact_dir = Path(output_dir).resolve()
        run = Hot30RunPaths(
            root=artifact_dir.parent,
            work_dir=artifact_dir.parent / "work",
            artifacts_dir=artifact_dir,
            judgments_path=artifact_dir.parent / "work" / "discover-judgments.json",
            angles_path=artifact_dir.parent / "work" / "discover-angles.json",
        )
        run.work_dir.mkdir(parents=True, exist_ok=True)
        run.artifacts_dir.mkdir(parents=True, exist_ok=True)
        commands = self.protocol_commands(run, domain=topic, emit=emit)
        environment = self._execution_environment(env)
        focus = " ".join(str(topic or "").split())
        fallback = (
            self.python_executable, str(self.vendor.script_path), "--discover",
            *( (focus,) if focus else () ), f"--emit={emit}", "--save-dir", str(run.work_dir),
        )

        def artifacts_for(brief: str, trends: Mapping[str, Any], source_status: Mapping[str, Any]) -> dict[str, str]:
            brief_md = run.artifacts_dir / "brief.md"
            brief_html = run.artifacts_dir / "brief.html"
            trends_path = run.artifacts_dir / "trends.json"
            source_path = run.artifacts_dir / "source_status.json"
            brief_md.write_text(brief, encoding="utf-8")
            self._write_html_brief(brief_html, brief)
            _json_file(trends_path, dict(trends))
            _json_file(source_path, dict(source_status))
            return {
                "brief_html": str(brief_html),
                "brief_md": str(brief_md),
                "trends": str(trends_path),
                "source_status": str(source_path),
            }

        try:
            # Leg 1 intentionally happens even without model access: it creates
            # the canonical handoff bundle and retains the vendor's discovery
            # behavior rather than replacing it with local heuristics.
            self._run_command(commands.nominate, environment=environment, cancel_event=cancel_event)
            nominations = self._read_object(run.work_dir / "discover-nominations.json")
            judged = self._judge_nominations(nominations, environment)
            judgments = self._normalize_judgments(nominations, judged)
            self.write_judgments(run, judgments)
            self._run_command(commands.judge, environment=environment, cancel_event=cancel_event)
            pending = self._read_object(run.work_dir / "discover-pending.json")
            angles = self._model_angles(nominations, judged, pending)
            self.write_angles(run, angles)
            brief = self._run_command(commands.finalize, environment=environment, cancel_event=cancel_event)
            trends = self._project_trends(nominations, pending)
            source_status = trends.get("source_status") if isinstance(trends.get("source_status"), Mapping) else {}
            return {
                "mode": "hot30", "status": "completed", "stage": "exported", "focus": focus,
                "paths": run.as_dict(), "artifacts": artifacts_for(brief, trends, source_status),
                "protocol": {"mode": "host_judged", "angles": "model" if angles["angles"] else "empty_no_safe_angle_generation"},
            }
        except Hot30Cancelled:
            return {
                "mode": "hot30", "status": "interrupted", "stage": "cancelled", "focus": focus,
                "paths": run.as_dict(), "progress": {"stage": "cancelled", "message": "热点研究已取消，已终止外部采集。"},
            }
        except Hot30TimedOut:
            return {
                "mode": "hot30", "status": "failed", "stage": "hot30_timed_out", "focus": focus,
                "paths": run.as_dict(), "failures": [{"stage": "hot30", "message": "last30days 执行超时，已终止外部采集。"}],
            }
        except Exception:
            # One (and only one) one-shot sweep is the documented recovery for
            # missing host judgment or a failed handoff leg. Its compact output
            # is a real engine brief, but it lacks trusted handoff evidence, so
            # trends are explicitly unknown instead of locally fabricated.
            try:
                brief = self._run_command(fallback, environment=environment, cancel_event=cancel_event)
            except Hot30Cancelled:
                return {
                    "mode": "hot30", "status": "interrupted", "stage": "cancelled", "focus": focus,
                    "paths": run.as_dict(), "progress": {"stage": "cancelled", "message": "热点研究已取消，已终止外部采集。"},
                }
            except Hot30TimedOut:
                return {
                    "mode": "hot30", "status": "failed", "stage": "hot30_timed_out", "focus": focus,
                    "paths": run.as_dict(), "failures": [{"stage": "hot30", "message": "last30days 执行超时，已终止外部采集。"}],
                }
            except Exception:
                return {
                    "mode": "hot30", "status": "failed", "stage": "hot30_failed", "focus": focus,
                    "paths": run.as_dict(), "failures": [{"stage": "hot30", "message": "last30days 多平台流程未能完成。"}],
                }
            trends = {"status": "unknown", "trends": [], "reason": "host_judgment_unavailable"}
            source_status = {"status": "unknown", "reason": "host_judgment_unavailable"}
            return {
                "mode": "hot30", "status": "completed", "stage": "exported", "focus": focus,
                "paths": run.as_dict(), "artifacts": artifacts_for(brief, trends, source_status),
                "protocol": {"mode": "one_shot_fallback", "angles": "not_generated_without_host_judgment"},
            }
