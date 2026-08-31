"""Compatibility checks for the Windows PowerShell wrapper."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_radar_powershell_keeps_paths_and_forwards_new_commands(tmp_path: Path) -> None:
    """Legacy commands should keep working while new CLI commands are forwarded verbatim."""
    tools_root = tmp_path / ".tools"
    agent_exe = tools_root / "agent-reach/.venv/Scripts/agent-reach.exe"
    opencli_exe = tools_root / "opencli/node_modules/.bin/opencli.cmd"
    agent_exe.parent.mkdir(parents=True, exist_ok=True)
    opencli_exe.parent.mkdir(parents=True, exist_ok=True)
    agent_exe.write_text("", encoding="utf-8")
    opencli_exe.write_text("", encoding="utf-8")

    capture_path = tmp_path / "captured-args.txt"
    fake_python = tmp_path / "fake-python.cmd"
    fake_python.write_text(
        textwrap.dedent(
            f"""\
            @echo off
            > "{capture_path}" echo %*
            exit /b 0
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["RADAR_TOOLS_ROOT"] = str(tools_root)
    env["RADAR_PYTHON_EXE"] = str(fake_python)

    paths = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts/radar.ps1"),
            "paths",
            "-ConfigPath",
            str(tmp_path / "missing.env"),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    parsed = json.loads(paths.stdout)
    assert parsed["agent_reach_exe"].endswith("agent-reach.exe")
    assert parsed["opencli_exe"].endswith("opencli.cmd")

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts/radar.ps1"),
            "communities-suggest",
            "-RunId",
            "fixture-run",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert capture_path.read_text(encoding="utf-8").strip() == "-m opportunity_radar communities suggest --run-id fixture-run"


def test_radar_powershell_doctor_forwards_to_python_and_injects_env_from_config(tmp_path: Path) -> None:
    """The PowerShell wrapper must pass `.env` values to the Python CLI child process."""
    capture_args = tmp_path / "captured-args.txt"
    capture_env = tmp_path / "captured-env.txt"
    config_path = tmp_path / ".env"
    config_path.write_text(
        "RADAR_RUNS_ROOT=.local\\runs-from-config\nDEEPSEEK_API_KEY=config-secret\n",
        encoding="utf-8",
    )
    fake_python = tmp_path / "fake-python.cmd"
    fake_python.write_text(
        textwrap.dedent(
            f"""\
            @echo off
            > "{capture_args}" echo %*
            > "{capture_env}" (
              echo RADAR_RUNS_ROOT=%RADAR_RUNS_ROOT%
              echo DEEPSEEK_API_KEY=%DEEPSEEK_API_KEY%
            )
            exit /b 0
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["RADAR_PYTHON_EXE"] = str(fake_python)

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts/radar.ps1"),
            "doctor",
            "-ConfigPath",
            str(config_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert capture_args.read_text(encoding="utf-8").strip() == "-m opportunity_radar doctor"
    captured_env = capture_env.read_text(encoding="utf-8")
    assert "RADAR_RUNS_ROOT=" in captured_env
    assert "DEEPSEEK_API_KEY=config-secret" in captured_env
