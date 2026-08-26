from datetime import UTC, datetime

import opportunity_radar
import pytest


def test_run_paths_create_isolated_artifact_locations_and_round_trip_a_manifest(tmp_path) -> None:
    """A shared artifact location or unreadable manifest prevents safe resume/status commands."""
    paths = opportunity_radar.create_run_paths(tmp_path / "runs", "20260831T120000Z-abc")
    manifest = opportunity_radar.RunManifest(
        run_id="20260831T120000Z-abc",
        started_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        config_sha256="a" * 64,
        status="collecting",
        completed_stages=("configured",),
    )

    opportunity_radar.write_manifest(paths, manifest)

    assert paths.run_dir == tmp_path / "runs" / "20260831T120000Z-abc"
    assert paths.raw_dir.is_dir()
    assert paths.checkpoints_dir.is_dir()
    assert opportunity_radar.read_manifest(paths) == manifest


def test_manifest_refuses_a_non_digest_config_reference(tmp_path) -> None:
    """Writing arbitrary config text into a manifest risks persisting sensitive configuration."""
    paths = opportunity_radar.create_run_paths(tmp_path / "runs", "safe-run")
    manifest = opportunity_radar.RunManifest(
        run_id="safe-run",
        started_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        config_sha256="not-a-digest",
        status="configured",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        opportunity_radar.write_manifest(paths, manifest)

    assert not paths.manifest_path.exists()
