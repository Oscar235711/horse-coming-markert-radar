"""Portable packaging checks for the distributable Opportunity Radar skill."""

from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "opportunity-radar"


def test_skill_package_is_utf8_and_exposes_windows_deepseek_workflow(tmp_path: Path) -> None:
    """A clean skill package must be readable on Windows and describe the live engine."""
    copied = tmp_path / "opportunity-radar"
    shutil.copytree(SKILL_ROOT, copied)
    markdown = (copied / "SKILL.md").read_text(encoding="utf-8", errors="strict")

    assert markdown.startswith("---\nname: opportunity-radar\n")
    assert "scripts/run.ps1" in markdown
    assert "--analysis-engine deepseek" in markdown
    for file_path in copied.rglob("*"):
        if file_path.is_file():
            file_path.read_text(encoding="utf-8", errors="strict")


def test_skill_references_and_powershell_scripts_are_resolved() -> None:
    """Broken links or a PowerShell parse error make the shared skill unusable."""
    markdown = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for relative in re.findall(r"\]\((references/[^)]+)\)", markdown):
        assert (SKILL_ROOT / relative).is_file(), relative
    for script in (SKILL_ROOT / "scripts").glob("*.ps1"):
        command = "$content = Get-Content -Raw -Encoding UTF8 -LiteralPath $env:RADAR_TEST_SCRIPT; [scriptblock]::Create($content) | Out-Null"
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "RADAR_TEST_SCRIPT": str(script)},
        )
        assert result.returncode == 0, result.stderr
