"""Repository-level secret hygiene checks for Task 4 artifacts."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT_PATTERNS = (
    re.compile(r"(?im)^[ \t]*DEEPSEEK_API_KEY[ \t]*=[ \t]*.+$"),
    re.compile(r"(?im)^[ \t]*RADAR_[A-Z0-9_]*COOKIE[A-Z0-9_]*[ \t]*=[ \t]*.+$"),
)


def test_repo_examples_keep_secret_placeholders_empty() -> None:
    """Tracked examples must never ship live credentials or persisted cookies."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY=" in example
    assert "DEEPSEEK_API_KEY=\n" in example.replace("\r\n", "\n")
    for pattern in ASSIGNMENT_PATTERNS:
        assert pattern.search(example) is None


def test_tracked_docs_code_and_configs_do_not_persist_api_keys_or_cookie_values() -> None:
    """The repository should stay safe to clone without scrubbing generated reports."""
    tracked_files = [
        *REPO_ROOT.glob("src/**/*.py"),
        *REPO_ROOT.glob("scripts/**/*.ps1"),
        *REPO_ROOT.glob("tests/**/*.py"),
        *REPO_ROOT.glob("configs/**/*.yaml"),
        REPO_ROOT / "README.md",
    ]

    for path in tracked_files:
        content = path.read_text(encoding="utf-8")
        for pattern in ASSIGNMENT_PATTERNS:
            assert pattern.search(content) is None, f"secret-like assignment found in {path}"
