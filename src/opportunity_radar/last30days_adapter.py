"""Project-local orchestration for the vendored ``last30days`` skill.

The adapter deliberately owns only filesystem boundaries and command assembly.
The vendored engine remains an unmodified snapshot; discovery retrieval is
performed only when a caller explicitly executes one of the returned commands.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


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
    ) -> None:
        self._project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.vendor = resolve_vendor_paths(self._project_root)
        self.runs_root = (runs_root or self._project_root / "outputs" / "hot30").resolve()
        self.environment = dict(environment or {})
        self.python_executable = python_executable or sys.executable

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


class Last30DaysAdapter(Hot30Adapter):
    """Compatibility wrapper consumed by the local server's Hot 30 mode.

    The wrapper intentionally prepares the host-judged protocol instead of
    silently starting a multi-platform network sweep. A worker can execute
    the returned commands, supply a DeepSeek judgment through
    :meth:`judge_and_write`, and call :meth:`project_finalize_output` after
    finalization. The stable artifact keys exist from the first response so
    callers need not special-case the planned state.
    """

    def run_hot30(
        self,
        topic: str,
        output_dir: Path | str,
        env: Mapping[str, str] | None = None,
        emit: str = "compact",
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
        # ``env`` stays in memory and is deliberately not copied to files or
        # command arguments. It allows an embedding worker to pass its own
        # process environment to a later command runner.
        _ = env
        commands = self.protocol_commands(run, domain=topic, emit=emit)
        return {
            "mode": "hot30",
            "status": "planned",
            "stage": "hot30_protocol_planned",
            "focus": " ".join(str(topic or "").split()),
            "paths": run.as_dict(),
            "commands": commands.as_dict(),
            "artifacts": {
                "brief_html": None,
                "brief_md": None,
                "trends": None,
                "source_status": None,
            },
        }
