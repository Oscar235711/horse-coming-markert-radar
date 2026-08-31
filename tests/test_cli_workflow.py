"""Offline end-to-end contracts for the Task 4 CLI workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import opportunity_radar


AS_OF = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


class ScriptedCollector:
    """Return deterministic shortlist/deep-read fixtures without network access."""

    def __init__(self) -> None:
        self.calls = 0

    def collect(self, communities, *, paths, as_of, deep_read=False, shortlist_limit=30):
        self.calls += 1
        posts = tuple(
            opportunity_radar.NormalizedPost(
                post_id=f"t3_fixture_{index}",
                url=f"https://www.reddit.com/r/Cummins/comments/fixture_{index}/example/",
                subreddit="Cummins",
                title=f"Winter crack {index}",
                body="Owners describe a winter crack problem and ask for stronger aftermarket options.",
                author=f"owner-{index}",
                created_at=as_of - timedelta(days=index + 1),
                score=25 - index,
                comment_count=4 + index,
                source_surfaces=("hot",),
            )
            for index in range(3)
        )
        candidates = tuple(
            opportunity_radar.WindowedPost(post=post, window=opportunity_radar.PostWindow.CURRENT)
            for post in posts
        )
        shortlisted = tuple(
            opportunity_radar.ShortlistedPost(
                post=post,
                window=opportunity_radar.PostWindow.CURRENT,
                priority_score=90 - index,
            )
            for index, post in enumerate(posts)
        )
        deep_reads = tuple(
            opportunity_radar.ThreadDocument(
                post=post,
                comments=(
                    opportunity_radar.ThreadComment(
                        f"c{index}",
                        "It cracked after winter towing.",
                        post.url + f"?comment={index}",
                        f"commenter-{index}",
                    ),
                ),
            )
            for index, post in enumerate(posts)
        )
        return opportunity_radar.CollectionResult(
            candidates=candidates,
            shortlisted=shortlisted,
            deep_reads=deep_reads,
            failures=(),
        )


class FlakyFlashClient:
    """Fail once for one post so resume must reuse saved checkpoints."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failed_once = False

    def extract_post(self, thread: opportunity_radar.ThreadDocument) -> opportunity_radar.PostAnalysis:
        self.calls.append(thread.post.post_id)
        if thread.post.post_id == "t3_fixture_1" and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("transient flash failure")
        return opportunity_radar.PostAnalysis(
            topics=(opportunity_radar.TopicCandidate("winter crack", ("post", "c0")),),
            claims=(
                opportunity_radar.EvidenceClaim(
                    "Owners report cracking after winter towing.",
                    ("post", "c0"),
                    (thread.post.url, thread.comments[0].url),
                ),
            ),
        )


class DeterministicPro:
    """Community-level consolidation fixture for offline workflow tests."""

    mode = "deterministic_fixture"

    def consolidate(self, community, signals):
        evidence = tuple(
            opportunity_radar.TopicEvidence(
                post_id=signal.post.post_id,
                evidence_id="post",
                claim="Owners report cracking after winter towing.",
                stance="supporting",
                translation_zh="车主反馈冬季拖拽后会开裂。",
            )
            for signal in signals
        )
        source = evidence[:1]
        return (
            opportunity_radar.ProTopicProposal(
                canonical_key="winter-crack",
                label_en="Winter crack",
                label_zh="冬季开裂",
                summary=opportunity_radar.EvidenceBackedClaim(
                    "Cummins owners want a more durable winter-ready replacement.",
                    source,
                ),
                post_ids=tuple(signal.post.post_id for signal in signals),
                evidence=evidence,
                category_tags=("durability",),
                brand_tags=("Cummins",),
                opportunity_hypotheses=(
                    opportunity_radar.EvidenceBackedClaim(
                        "Opportunity hypothesis: winter-ready reinforced replacement.",
                        source,
                    ),
                ),
                confidence=0.87,
            ),
        )


def _write_fake_workbook(output_dir: Path, analysis: dict) -> opportunity_radar.TopicExportArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_json = output_dir / "analysis.json"
    topics_json = output_dir / "community_topics.json"
    workbook = output_dir / "community_topics.xlsx"
    analysis_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    topics_json.write_text(
        json.dumps({"topics": analysis.get("topics", [])}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    workbook.write_bytes(b"offline-xlsx")
    return opportunity_radar.TopicExportArtifacts(analysis_json, topics_json, workbook)


def test_run_resume_status_export_and_governance_round_trip_without_network(tmp_path: Path) -> None:
    """The new CLI workflow must persist resumable state and safe community suggestions offline."""
    app = opportunity_radar.RadarCliApp(
        runs_root=tmp_path / "runs",
        config_versions_root=tmp_path / "versions",
        environment={"DEEPSEEK_API_KEY": "very-secret-key"},
        collector=ScriptedCollector(),
        flash_client=FlakyFlashClient(),
        pro_consolidator=DeterministicPro(),
        exporter=_write_fake_workbook,
        now=lambda: AS_OF,
    )

    first = app.run("configs/diesel_90d.yaml", run_id="fixture-run")

    assert first["status"] == "incomplete"
    assert first["stage"] == "flash_extract"
    assert first["counts"]["analyzed_posts"] == 2
    assert (tmp_path / "runs" / "fixture-run" / "checkpoints" / "analysis__t3_fixture_0.json").exists()
    assert not (tmp_path / "runs" / "fixture-run" / "artifacts" / "analysis.json").exists()

    resumed = app.resume("fixture-run")

    assert resumed["status"] == "completed"
    assert resumed["completed_stages"] == [
        "configured",
        "collected",
        "flash_extract",
        "topic_consolidation",
        "exported",
    ]
    assert resumed["counts"]["topic_count"] == 1
    assert resumed["counts"]["failure_count"] == 0
    project_library = tmp_path / "library"
    assert (project_library / "communities.json").exists()
    assert (project_library / "topics.json").exists()
    assert (project_library / "keywords.json").exists()

    status = app.status("fixture-run")
    rendered_status = json.dumps(status, ensure_ascii=False)
    assert "very-secret-key" not in rendered_status
    assert status["artifacts"]["analysis_json"].endswith("analysis.json")
    assert status["counts"]["deep_read_count"] == 3

    exported = app.export("fixture-run", formats=("json", "xlsx"))
    assert Path(exported["artifacts"]["analysis_json"]).exists()
    assert Path(exported["artifacts"]["community_topics_xlsx"]).exists()

    suggested = app.communities_suggest("fixture-run")
    suggestion_path = Path(suggested["suggestion_path"])
    suggestion_document = json.loads(suggestion_path.read_text(encoding="utf-8"))
    assert suggestion_document["suggestions"][0]["kind"] == "slang"
    assert suggestion_document["suggestions"][0]["evidence"][0]["url"].startswith("https://www.reddit.com/")

    approved = app.communities_approve(
        suggestion_path,
        suggestion_id=suggestion_document["suggestions"][0]["suggestion_id"],
    )
    assert Path(approved["new_version_path"]).exists()
    assert approved["active_version_path"] != approved["new_version_path"]
    approved_document = opportunity_radar.load_community_catalog(approved["new_version_path"])
    cummins = next(community for community in approved_document.communities if community.name == "Cummins")
    assert "winter crack" in cummins.slang


def test_run_rejects_reusing_an_existing_run_id_without_resume(tmp_path: Path) -> None:
    """A fresh run must not inherit stale checkpoints or artifacts from an old run directory."""
    runs_root = tmp_path / "runs"
    existing = opportunity_radar.create_run_paths(runs_root, "fixture-run")
    existing.state_path.write_text("{}", encoding="utf-8")

    app = opportunity_radar.RadarCliApp(
        runs_root=runs_root,
        config_versions_root=tmp_path / "versions",
        environment={"DEEPSEEK_API_KEY": "very-secret-key"},
        collector=ScriptedCollector(),
        flash_client=FlakyFlashClient(),
        pro_consolidator=DeterministicPro(),
        exporter=_write_fake_workbook,
        now=lambda: AS_OF,
    )

    import pytest

    with pytest.raises(ValueError, match="already exists"):
        app.run("configs/diesel_90d.yaml", run_id="fixture-run")


def test_export_formats_control_json_and_xlsx_generation_and_reject_unknown_formats(tmp_path: Path) -> None:
    """`export --formats` must not silently depend on Node for JSON-only output or ignore unsupported formats."""
    run_id = "fixture-run"
    paths = opportunity_radar.create_run_paths(tmp_path / "runs", run_id)
    analysis = {
        "analysis_version": "1.0",
        "generated_at": AS_OF.isoformat(),
        "communities": ["Cummins"],
        "topics": [],
        "excluded_records": [],
    }
    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    (paths.artifacts_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    paths.state_path.write_text(json.dumps({"run_id": run_id, "completed_stages": [], "artifacts": {}, "counts": {}}), encoding="utf-8")
    opportunity_radar.write_manifest(
        paths,
        opportunity_radar.RunManifest(
            run_id=run_id,
            started_at=AS_OF,
            config_sha256="a" * 64,
            status="completed",
            completed_stages=("configured",),
        ),
    )
    calls: list[tuple[str, ...]] = []

    def exporter(output_dir: Path, export_analysis: dict, formats: tuple[str, ...]) -> opportunity_radar.TopicExportArtifacts:
        calls.append(formats)
        return _write_fake_workbook(output_dir, export_analysis)

    app = opportunity_radar.RadarCliApp(
        runs_root=tmp_path / "runs",
        config_versions_root=tmp_path / "versions",
        exporter=exporter,
        now=lambda: AS_OF,
    )

    result = app.export(run_id, formats=("json",))

    assert result["formats"] == ["json"]
    assert Path(result["artifacts"]["analysis_json"]).exists()
    assert Path(result["artifacts"]["community_topics_json"]).exists()
    assert "community_topics_xlsx" not in result["artifacts"]
    assert calls == []

    xlsx_result = app.export(run_id, formats=("xlsx",))
    assert Path(xlsx_result["artifacts"]["community_topics_xlsx"]).exists()
    assert calls == [("xlsx",)]

    import pytest

    with pytest.raises(ValueError, match="Unsupported export format"):
        app.export(run_id, formats=("html",))


class FakeTooling:
    """Minimal command adapter for doctor checks."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments: tuple[str, ...]) -> str:
        self.calls.append(arguments)
        if arguments[:3] == ("opencli", "reddit", "whoami"):
            return json.dumps([{"field": "Username", "value": "u/fixture-user"}])
        if arguments[:3] == ("opencli", "opportunity-reddit", "range"):
            return json.dumps([{"id": "probe", "title": "Probe", "permalink": "/r/test/comments/probe/example/", "subreddit": arguments[3], "selftext": "probe", "author": "fixture", "created_utc": AS_OF.timestamp(), "score": 1, "num_comments": 1}])
        raise AssertionError(f"unexpected doctor command: {arguments}")


def test_doctor_treats_deepseek_as_optional_and_checks_codex_reddit_excel(tmp_path: Path) -> None:
    """The default Codex workflow must not be blocked by a missing DeepSeek key."""
    opencli = FakeTooling()
    report = opportunity_radar.RadarCliApp(
        runs_root=tmp_path / "runs",
        config_versions_root=tmp_path / "versions",
        environment={},
        tool_runner=opencli,
        now=lambda: AS_OF,
    ).doctor()

    assert not any("DEEPSEEK_API_KEY" in warning for warning in report["warnings"])
    assert report["checks"]["deepseek"]["required"] is False
    assert report["checks"]["codex"]["status"] in {"ok", "warning"}
    assert report["checks"]["reddit"]["whoami"]["status"] == "ok"
    assert report["checks"]["excel"]["status"] in {"ok", "warning"}
    assert opencli.calls[0] == (
        "opencli",
        "reddit",
        "whoami",
        "-f",
        "json",
        "--window",
        "foreground",
        "--site-session",
        "persistent",
    )
    assert opencli.calls[1][:5] == (
        "opencli",
        "opportunity-reddit",
        "range",
        "Cummins",
        "--start-date",
    )
    assert opencli.calls[1][-6:] == (
        "-f",
        "json",
        "--window",
        "foreground",
        "--site-session",
        "persistent",
    )
