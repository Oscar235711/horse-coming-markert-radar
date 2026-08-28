"""The diesel evidence gate must protect the real CLI analysis path."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import opportunity_radar


AS_OF = datetime(2026, 8, 28, tzinfo=UTC)


class MixedCollector:
    def collect(self, communities, *, paths, as_of, deep_read=False, shortlist_limit=30):
        posts = (
            opportunity_radar.NormalizedPost(
                post_id="t3_good", url="https://reddit.example/good", subreddit="Cummins",
                title="Need an EGR cooler that does not seep when towing",
                body="I need a durable replacement for my 2018 6.7 Cummins.", author="owner",
                created_at=AS_OF, score=4, comment_count=1, source_surfaces=("hot",),
            ),
            opportunity_radar.NormalizedPost(
                post_id="t3_generic", url="https://reddit.example/generic", subreddit="AskCars",
                title="Downpipe and tuner", body="Which catless downpipe and tuner should I buy?", author="owner2",
                created_at=AS_OF, score=999, comment_count=1, source_surfaces=("hot",),
            ),
        )
        threads = tuple(
            opportunity_radar.ThreadDocument(
                post=post,
                comments=(opportunity_radar.ThreadComment(f"{post.post_id}-c", "Useful detail", post.url + "#comment"),),
            )
            for post in posts
        )
        candidates = tuple(opportunity_radar.WindowedPost(post, opportunity_radar.PostWindow.CURRENT) for post in posts)
        shortlist = tuple(opportunity_radar.ShortlistedPost(post, opportunity_radar.PostWindow.CURRENT, 90) for post in posts)
        return opportunity_radar.CollectionResult(candidates, shortlist, threads, ())


class RecordingFlash:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def extract_post(self, thread, *, model=None):
        self.calls.append((thread.post.post_id, model))
        return opportunity_radar.PostAnalysis(
            topics=(opportunity_radar.TopicCandidate("egr durability", ("post",)),),
            claims=(opportunity_radar.EvidenceClaim("Need durable EGR cooler.", ("post",), (thread.post.url,)),),
        )


class EmptyPro:
    mode = "fixture"

    def consolidate(self, community, signals):
        return ()


def _export(output_dir: Path, analysis: dict, formats: tuple[str, ...]):
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_json = output_dir / "analysis.json"
    topics_json = output_dir / "community_topics.json"
    workbook = output_dir / "community_topics.xlsx"
    analysis_json.write_text(json.dumps(analysis), encoding="utf-8")
    topics_json.write_text("{}", encoding="utf-8")
    workbook.write_bytes(b"xlsx")
    return opportunity_radar.TopicExportArtifacts(analysis_json, topics_json, workbook)


def test_run_gates_generic_posts_persists_audit_and_passes_configured_flash_model(tmp_path: Path) -> None:
    """Only relevant diesel posts reach Flash; excluded decisions remain reviewable."""
    flash = RecordingFlash()
    app = opportunity_radar.RadarCliApp(
        runs_root=tmp_path / "runs", config_versions_root=tmp_path / "versions",
        environment={"DEEPSEEK_API_KEY": "test-key", "DEEPSEEK_FLASH_MODEL": "company-flash"},
        collector=MixedCollector(), flash_client=flash, pro_consolidator=EmptyPro(), exporter=_export,
        now=lambda: AS_OF,
    )

    state = app.run("configs/diesel_90d.yaml", run_id="gate-run")
    audit = json.loads(Path(state["artifacts"]["evidence_gate_json"]).read_text(encoding="utf-8"))

    assert flash.calls == [("t3_good", "company-flash")]
    assert state["counts"]["eligible_post_count"] == 1
    assert state["counts"]["excluded_post_count"] == 1
    assert [entry["post_id"] for entry in audit["qualified_posts"]] == ["t3_good"]
    assert audit["excluded_posts"][0]["reason_codes"] == ["missing_diesel_context"]
