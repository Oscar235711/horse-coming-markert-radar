"""Rebuild secret-free discovery libraries from immutable saved radar runs.

The script never contacts Reddit or a model.  It backs up the three project
library documents before replacing them with records reconstructed from saved
analysis and normalized evidence.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

from opportunity_radar.library import update_project_library


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--runs-root", type=Path, default=root / ".local" / "runs")
    parser.add_argument("--library-root", type=Path, default=root / "library")
    parser.add_argument("--backup-root", type=Path, default=root / ".local" / "library-backups")
    args = parser.parse_args()

    runs_root = args.runs_root.resolve()
    library_root = args.library_root.resolve()
    backup_root = args.backup_root.resolve()
    _backup_and_clear(library_root, backup_root)
    rebuilt = 0
    for run_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda path: path.name) if runs_root.exists() else ():
        analysis_path = _analysis_path(run_dir)
        if analysis_path is None:
            continue
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(analysis, dict):
            continue
        posts, comments = _run_evidence(run_dir)
        update_project_library(
            library_root,
            analysis,
            run_id=run_dir.name,
            posts=posts,
            comments=comments,
            now=datetime.now(UTC),
        )
        rebuilt += 1
    print(json.dumps({"status": "rebuilt", "runs": rebuilt, "library_root": str(library_root)}, ensure_ascii=False))
    return 0


def _backup_and_clear(library_root: Path, backup_root: Path) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / stamp
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("communities.json", "keywords.json", "topics.json"):
        source = library_root / name
        if source.exists():
            shutil.copy2(source, destination / name)
            source.unlink()


def _analysis_path(run_dir: Path) -> Path | None:
    for candidate in (run_dir / "artifacts" / "analysis.json", run_dir / "analysis.json"):
        if candidate.is_file():
            return candidate
    return None


def _run_evidence(run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    posts: dict[str, dict[str, Any]] = {}
    comments: dict[str, dict[str, Any]] = {}
    for path in (run_dir / "normalized" / "posts.jsonl", run_dir / "posts.jsonl"):
        for record in _json_lines(path):
            post_id = str(record.get("post_id") or record.get("id") or "")
            if post_id:
                posts[post_id] = record
    for path in (run_dir / "normalized" / "comments.jsonl", run_dir / "comments.jsonl"):
        for record in _json_lines(path):
            comment_id = str(record.get("comment_id") or record.get("id") or "")
            if comment_id:
                comments[comment_id] = record
    for path in (run_dir / "raw" / "threads").glob("**/*.json") if (run_dir / "raw" / "threads").exists() else ():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        post = document.get("post")
        if isinstance(post, dict) and str(post.get("post_id") or post.get("id") or ""):
            posts.setdefault(str(post.get("post_id") or post.get("id")), post)
        for comment in document.get("comments", []):
            if isinstance(comment, dict) and str(comment.get("comment_id") or comment.get("id") or ""):
                comments.setdefault(str(comment.get("comment_id") or comment.get("id")), comment)
    return list(posts.values()), list(comments.values())


def _json_lines(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return ()
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
