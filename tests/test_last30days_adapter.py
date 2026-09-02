"""Offline contracts for the vendored last30days discovery adapter."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from threading import Event

from opportunity_radar.last30days_adapter import (
    Hot30Adapter,
    Last30DaysAdapter,
    project_root,
    resolve_vendor_paths,
)


def test_vendor_paths_are_resolved_from_the_project_not_a_personal_skill_directory() -> None:
    paths = resolve_vendor_paths(project_root())

    assert paths.skill_dir == project_root() / "vendor" / "last30days"
    assert paths.script_path == paths.skill_dir / "scripts" / "last30days.py"
    assert paths.script_path.is_file()
    assert "C:\\Users\\yaobi\\.codex\\skills" not in str(paths.script_path)


def test_prepare_run_creates_project_scoped_temporary_files_without_persisting_keys(tmp_path: Path) -> None:
    adapter = Hot30Adapter(project_root=project_root(), runs_root=tmp_path, environment={"DEEPSEEK_API_KEY": "top-secret"})

    run = adapter.prepare_run("hot30-fixture")

    assert run.root == tmp_path / "hot30-fixture"
    assert run.work_dir.is_dir()
    assert run.artifacts_dir.is_dir()
    assert run.judgments_path.parent == run.work_dir
    assert run.angles_path.parent == run.work_dir
    assert "top-secret" not in json.dumps(run.as_dict())
    assert all("top-secret" not in path.read_text(encoding="utf-8") for path in run.root.rglob("*") if path.is_file())


def test_finalize_projection_maps_source_status_brief_and_trends_artifacts(tmp_path: Path) -> None:
    adapter = Hot30Adapter(project_root=project_root(), runs_root=tmp_path)
    run = adapter.prepare_run("hot30-projection")
    engine_report = {
        "outcome": "ranked",
        "source_status": {"reddit": {"state": "ok"}, "hackernews": {"state": "no-results"}},
        "topics": [{"name": "Diesel towing EGT", "velocity": "rising"}],
    }

    artifacts = adapter.project_finalize_output(
        run,
        brief="# Hot 30\n\nDiesel towing EGT is rising.",
        trends=engine_report,
    )

    assert json.loads(artifacts.source_status.read_text(encoding="utf-8")) == engine_report["source_status"]
    assert json.loads(artifacts.trends.read_text(encoding="utf-8"))["topics"][0]["name"] == "Diesel towing EGT"
    assert artifacts.brief.read_text(encoding="utf-8").startswith("# Hot 30")


def test_protocol_commands_keep_secrets_out_of_arguments_and_use_a_shared_save_dir(tmp_path: Path) -> None:
    adapter = Hot30Adapter(project_root=project_root(), runs_root=tmp_path, environment={"DEEPSEEK_API_KEY": "top-secret"})
    run = adapter.prepare_run("hot30-commands")

    commands = adapter.protocol_commands(run, domain="North American diesel pickup aftermarket")

    assert commands.nominate[:3] == (adapter.python_executable, str(adapter.vendor.script_path), "--discover")
    assert "--nominate-only" in commands.nominate
    assert "--judgments" in commands.judge
    assert "--finalize" in commands.finalize
    assert all(str(run.work_dir) in command for command in commands.as_tuple())
    assert all("top-secret" not in " ".join(command) for command in commands.as_tuple())


class _FakeProcess:
    def __init__(self, argv, *, on_communicate=None) -> None:
        self.argv = tuple(argv)
        self.returncode = 0
        self.terminated = False
        self._on_communicate = on_communicate

    def communicate(self, timeout=None):
        if self._on_communicate:
            return self._on_communicate(self, timeout)
        return "# Hot 30\n\n中文热点简报", ""

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9


def _protocol_popen(calls: list[tuple[str, ...]]):
    def fake_popen(argv, **_kwargs):
        command = tuple(argv)
        calls.append(command)
        save_dir = Path(command[command.index("--save-dir") + 1])
        if "--nominate-only" in command:
            (save_dir / "discover-nominations.json").write_text(json.dumps({
                "bundle_id": "bundle-1",
                "nominations": [{
                    "id": "n1", "cluster_id": "cluster-1", "sources": ["reddit"],
                    "nomination": {"name": "柴油拖挂 EGT", "items": [{"url": "https://example.test/evidence", "source": "reddit"}]},
                }],
            }, ensure_ascii=False), encoding="utf-8")
        elif "--judgments" in command:
            (save_dir / "discover-pending.json").write_text(json.dumps({
                "bundle_id": "bundle-1",
                "report": {"source_status": {"reddit": {"state": "ok"}}, "topics": [{"name": "柴油拖挂 EGT"}]},
                "angle_inputs": {"n1": {"name": "柴油拖挂 EGT"}},
            }, ensure_ascii=False), encoding="utf-8")
        return _FakeProcess(command)
    return fake_popen


def test_run_hot30_executes_host_judged_protocol_and_projects_evidence_trends(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "中文 输出" / "artifacts"
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("opportunity_radar.last30days_adapter.subprocess.Popen", _protocol_popen(calls))
    adapter = Last30DaysAdapter(
        project_root=project_root(), environment={"DEEPSEEK_API_KEY": "top-secret"},
        judge=lambda nominations: {"bundle_id": nominations["bundle_id"], "judgments": []},
    )

    result = adapter.run_hot30("柴油 拖挂", output_dir, emit="compact")

    assert result["status"] == "completed"
    assert result["stage"] == "exported"
    assert ["--nominate-only" in command for command in calls] == [True, False, False]
    assert "--judgments" in calls[1]
    assert "--finalize" in calls[2]
    assert (output_dir / "brief.md").read_text(encoding="utf-8").startswith("# Hot 30")
    trends = json.loads((output_dir / "trends.json").read_text(encoding="utf-8"))
    assert trends["status"] == "ok"
    assert trends["trends"][0]["cluster_id"] == "cluster-1"
    assert trends["trends"][0]["evidence"][0]["url"] == "https://example.test/evidence"
    assert json.loads((output_dir / "source_status.json").read_text(encoding="utf-8"))["reddit"]["state"] == "ok"
    assert "top-secret" not in json.dumps(result)
    assert all("top-secret" not in path.read_text(encoding="utf-8") for path in output_dir.parent.rglob("*") if path.is_file())


def test_run_hot30_without_model_falls_back_once_without_inventing_trends(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "run" / "artifacts"
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("opportunity_radar.last30days_adapter.subprocess.Popen", _protocol_popen(calls))

    result = Last30DaysAdapter(project_root=project_root()).run_hot30("diesel towing", output_dir)

    assert result["status"] == "completed"
    assert len(calls) == 2
    assert "--nominate-only" in calls[0]
    assert "--nominate-only" not in calls[1]
    assert "--finalize" not in calls[1]
    trends = json.loads((output_dir / "trends.json").read_text(encoding="utf-8"))
    assert trends == {"status": "unknown", "trends": [], "reason": "host_judgment_unavailable"}


def test_run_hot30_terminates_the_active_subprocess_on_cancellation(tmp_path: Path, monkeypatch) -> None:
    cancelled = Event()
    processes: list[_FakeProcess] = []

    def fake_popen(argv, **_kwargs):
        def block(process, _timeout):
            cancelled.set()
            raise subprocess.TimeoutExpired(process.argv, 0.01)
        process = _FakeProcess(argv, on_communicate=block)
        processes.append(process)
        return process

    monkeypatch.setattr("opportunity_radar.last30days_adapter.subprocess.Popen", fake_popen)
    result = Last30DaysAdapter(project_root=project_root()).run_hot30(
        "diesel towing", tmp_path / "run" / "artifacts", cancel_event=cancelled,
    )

    assert result["status"] == "interrupted"
    assert result["stage"] == "cancelled"
    assert processes[0].terminated is True


def test_run_hot30_times_out_and_terminates_the_active_subprocess(tmp_path: Path, monkeypatch) -> None:
    processes: list[_FakeProcess] = []

    def fake_popen(argv, **_kwargs):
        process = _FakeProcess(argv, on_communicate=lambda item, timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired(item.argv, timeout)))
        processes.append(process)
        return process

    monkeypatch.setattr("opportunity_radar.last30days_adapter.subprocess.Popen", fake_popen)
    ticks = iter((0.0, 0.0, 1.0))
    adapter = Last30DaysAdapter(project_root=project_root(), command_timeout_seconds=0.5, clock=lambda: next(ticks))

    result = adapter.run_hot30("diesel towing", tmp_path / "run" / "artifacts")

    assert result["status"] == "failed"
    assert result["stage"] == "hot30_timed_out"
    assert processes[0].terminated is True
