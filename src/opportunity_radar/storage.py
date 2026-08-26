"""Local artifact paths and secret-free run state persistence."""

import json
import os
import re
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
    checkpoints_dir: Path
    artifacts_dir: Path
    manifest_path: Path


def create_run_paths(root: str | Path, run_id: str) -> RunPaths:
    """Create the isolated directories for a safe, resumable run."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a single non-empty path component")
    run_dir = Path(root) / run_id
    raw_dir = run_dir / "raw"
    checkpoints_dir = run_dir / "checkpoints"
    artifacts_dir = run_dir / "artifacts"
    for directory in (raw_dir, checkpoints_dir, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        run_dir=run_dir,
        raw_dir=raw_dir,
        checkpoints_dir=checkpoints_dir,
        artifacts_dir=artifacts_dir,
        manifest_path=run_dir / "manifest.json",
    )


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
