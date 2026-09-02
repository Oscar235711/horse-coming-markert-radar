"""Offline contracts for the vendored last30days discovery adapter."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_run_hot30_returns_the_server_artifact_shape_without_executing_network_commands(tmp_path: Path) -> None:
    output_dir = tmp_path / "run" / "artifacts"
    adapter = Last30DaysAdapter(project_root=project_root(), environment={"DEEPSEEK_API_KEY": "top-secret"})

    result = adapter.run_hot30("diesel towing", output_dir, emit="compact")

    assert result["status"] == "planned"
    assert result["stage"] == "hot30_protocol_planned"
    assert result["artifacts"] == {
        "brief_html": None,
        "brief_md": None,
        "trends": None,
        "source_status": None,
    }
    assert Path(result["paths"]["artifacts_dir"]) == output_dir.resolve()
    assert result["commands"]["nominate"][3] == "diesel towing"
    assert "top-secret" not in json.dumps(result)
