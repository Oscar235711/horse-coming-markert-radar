"""Local artifact paths and secret-free run state persistence."""

import json
import os
import re
from collections.abc import Mapping
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import RunManifest, TopicRecord


@dataclass(frozen=True, slots=True)
class RunPaths:
    """The per-run filesystem layout used by collection and analysis stages."""

    run_dir: Path
    raw_dir: Path
    raw_listings_dir: Path
    raw_searches_dir: Path
    raw_threads_dir: Path
    normalized_dir: Path
    keywords_dir: Path
    keyword_library_path: Path
    keyword_candidates_path: Path
    failures_path: Path
    checkpoints_dir: Path
    artifacts_dir: Path
    manifest_path: Path
    state_path: Path
    config_snapshot_path: Path
    suggestions_dir: Path


def create_run_paths(root: str | Path, run_id: str) -> RunPaths:
    """Create the isolated directories for a safe, resumable run."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a single non-empty path component")
    run_dir = Path(root) / run_id
    raw_dir = run_dir / "raw"
    raw_listings_dir = raw_dir / "listings"
    raw_searches_dir = raw_dir / "searches"
    raw_threads_dir = raw_dir / "threads"
    normalized_dir = run_dir / "normalized"
    keywords_dir = run_dir / "keywords"
    checkpoints_dir = run_dir / "checkpoints"
    artifacts_dir = run_dir / "artifacts"
    for directory in (raw_dir, raw_listings_dir, raw_searches_dir, raw_threads_dir, normalized_dir, keywords_dir, checkpoints_dir, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)
    suggestions_dir = run_dir / "suggestions"
    suggestions_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        run_dir=run_dir,
        raw_dir=raw_dir,
        raw_listings_dir=raw_listings_dir,
        raw_searches_dir=raw_searches_dir,
        raw_threads_dir=raw_threads_dir,
        normalized_dir=normalized_dir,
        keywords_dir=keywords_dir,
        keyword_library_path=keywords_dir / "keyword_library.json",
        keyword_candidates_path=keywords_dir / "keyword_candidates.json",
        failures_path=run_dir / "failures.jsonl",
        checkpoints_dir=checkpoints_dir,
        artifacts_dir=artifacts_dir,
        manifest_path=run_dir / "manifest.json",
        state_path=run_dir / "state.json",
        config_snapshot_path=run_dir / "config.snapshot.yaml",
        suggestions_dir=suggestions_dir,
    )


def persist_thread(paths: RunPaths, post_id: str, raw_thread: object) -> Path:
    """Persist the raw deep-read response without exposing credentials."""
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(post_id).removeprefix("t3_")) or "unknown"
    target = paths.raw_threads_dir / f"{safe_id}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(raw_thread, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)
    return target


def append_failure(paths: RunPaths, failure: Mapping[str, object]) -> None:
    """Append one secret-free failure record for resume and reporting."""
    allowed = {key: failure.get(key) for key in ("community", "post_id", "stage", "error_type", "retryable")}
    with paths.failures_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(allowed, ensure_ascii=False, sort_keys=True) + "\n")


def write_normalized_records(paths: RunPaths, posts: object, comments: object) -> tuple[Path, Path]:
    """Write canonical post/comment records as JSONL projections."""
    posts_path = paths.normalized_dir / "posts.jsonl"
    comments_path = paths.normalized_dir / "comments.jsonl"
    _write_jsonl(posts_path, posts)
    _write_jsonl(comments_path, comments)
    return posts_path, comments_path


def write_keyword_library(paths: RunPaths, library: Mapping[str, object]) -> tuple[Path, Path]:
    """Persist the complete keyword snapshot and its review queue for this run."""
    document = dict(library)
    candidates = document.get("candidates", [])
    _write_json(paths.keyword_library_path, document)
    _write_json(paths.keyword_candidates_path, {
        "version": document.get("version", "topic-keywords.v1"),
        "candidates": candidates if isinstance(candidates, list) else [],
    })
    return paths.keyword_library_path, paths.keyword_candidates_path


def _write_jsonl(path: Path, records: object) -> None:
    values = records if isinstance(records, (list, tuple)) else ()
    lines = []
    for record in values:
        if hasattr(record, "__dataclass_fields__"):
            from dataclasses import asdict
            value = asdict(record)
        elif isinstance(record, Mapping):
            value = dict(record)
        else:
            value = {"value": str(record)}
        lines.append(json.dumps(value, ensure_ascii=False, default=str, sort_keys=True))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(document), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def write_manifest(paths: RunPaths, manifest: RunManifest) -> None:
    """Atomically persist run metadata without writing configuration secrets."""
    if paths.run_dir.name != manifest.run_id:
        raise ValueError("manifest run_id must match its run path")
    if re.fullmatch(r"[0-9a-f]{64}", manifest.config_sha256) is None:
        raise ValueError("manifest config_sha256 must be a lowercase SHA-256 digest")
    document = {
        "run_id": manifest.run_id,
        "started_at": manifest.started_at.isoformat(),
        "config_sha256": manifest.config_sha256,
        "status": manifest.status,
        "completed_stages": list(manifest.completed_stages),
    }
    temporary_path = paths.manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    os.replace(temporary_path, paths.manifest_path)


def read_manifest(paths: RunPaths) -> RunManifest:
    """Read a run manifest previously saved with :func:`write_manifest`."""
    document = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("run manifest must be a JSON object")
    started_at = datetime.fromisoformat(str(document["started_at"]).replace("Z", "+00:00"))
    stages = document.get("completed_stages", [])
    if not isinstance(stages, list) or not all(isinstance(stage, str) for stage in stages):
        raise ValueError("manifest completed_stages must be a list of strings")
    return RunManifest(
        run_id=str(document["run_id"]),
        started_at=started_at,
        config_sha256=str(document["config_sha256"]),
        status=str(document["status"]),
        completed_stages=tuple(stages),
    )


class TopicRegistry:
    """JSON-backed stable topic identities, scoped to individual communities."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._records = self._read_records()

    def get_or_create(
        self,
        *,
        community: str,
        canonical_key: str,
        label_en: str,
        label_zh: str,
    ) -> TopicRecord:
        """Return the existing identity or persist a deterministic new one."""
        normalized_community = _required_registry_text(community, "community").casefold()
        normalized_key = _required_registry_text(canonical_key, "canonical_key").casefold()
        identity = (normalized_community, normalized_key)
        existing = self._records.get(identity)
        if existing is not None:
            return existing

        record = TopicRecord(
            topic_id=f"topic_{sha256(f'{normalized_community}:{normalized_key}'.encode()).hexdigest()[:16]}",
            community=normalized_community,
            canonical_key=normalized_key,
            label_en=_required_registry_text(label_en, "label_en"),
            label_zh=_required_registry_text(label_zh, "label_zh"),
        )
        self._records[identity] = record
        self._write_records()
        return record

    def records(self) -> tuple[TopicRecord, ...]:
        """Return records in deterministic community/key order."""
        return tuple(self._records[key] for key in sorted(self._records))

    def _read_records(self) -> dict[tuple[str, str], TopicRecord]:
        if not self._path.exists():
            return {}
        document = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(document, list):
            raise ValueError("topic registry must be a JSON list")
        records: dict[tuple[str, str], TopicRecord] = {}
        for item in document:
            if not isinstance(item, dict):
                raise ValueError("topic registry records must be JSON objects")
            record = TopicRecord(
                topic_id=_required_registry_text(item.get("topic_id"), "topic_id"),
                community=_required_registry_text(item.get("community"), "community"),
                canonical_key=_required_registry_text(item.get("canonical_key"), "canonical_key"),
                label_en=_required_registry_text(item.get("label_en"), "label_en"),
                label_zh=_required_registry_text(item.get("label_zh"), "label_zh"),
            )
            key = (record.community.casefold(), record.canonical_key.casefold())
            if key in records:
                raise ValueError("topic registry contains duplicate community/topic keys")
            records[key] = record
        return records

    def _write_records(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = [
            {
                "topic_id": record.topic_id,
                "community": record.community,
                "canonical_key": record.canonical_key,
                "label_en": record.label_en,
                "label_zh": record.label_zh,
            }
            for record in self.records()
        ]
        temporary_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
        os.replace(temporary_path, self._path)


def _required_registry_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"topic registry {field_name} must be a non-empty string")
    return value.strip()
