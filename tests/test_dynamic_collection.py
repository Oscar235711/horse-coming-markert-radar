"""Contracts for user-selected collection windows and stratified deep reading."""

from datetime import UTC, date, datetime, timedelta
import json

import opportunity_radar
from opportunity_radar.cli import main
from opportunity_radar.cli_app import _run_coverage_status


def _listing(post_id: str, *, created_at: datetime, surface: str = "new") -> dict:
    return {
        "id": post_id,
        "permalink": f"/r/Cummins/comments/{post_id}/example/",
        "subreddit": "Cummins",
        "title": f"Specific towing failure {post_id}",
        "selftext": "Need help fixing a fitment problem after towing.",
        "author": f"owner-{post_id}",
        "created_utc": created_at.timestamp(),
        "score": 10,
        "num_comments": 6,
        "source_surface": surface,
    }


def test_final_coverage_status_is_partial_when_any_query_did_not_reach_boundary() -> None:
    scope = opportunity_radar.CollectionScope(
        start_date=date(2025, 9, 1), end_date=date(2026, 8, 31), depth="complete"
    )
    assert _run_coverage_status(scope, {"Cummins": {"status": "complete"}}, {"diesel": {"status": "partial"}}) == "partial"
    assert _run_coverage_status(scope, {"Cummins": {"status": "complete"}}, {"diesel": {"status": "complete"}}) == "completed"


def test_range_collection_emits_exact_dates_and_coverage(tmp_path) -> None:
    """Ignoring the selected dates would silently turn every task back into the old 90-day run."""
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    records = [
        _listing("first", created_at=datetime(2026, 1, 1, 12, tzinfo=UTC)),
        _listing("middle", created_at=datetime(2026, 4, 15, 12, tzinfo=UTC)),
        _listing("after", created_at=datetime(2026, 9, 1, 12, tzinfo=UTC)),
    ]
    calls: list[tuple[str, ...]] = []

    def runner(arguments: tuple[str, ...]) -> str:
        calls.append(arguments)
        return json.dumps(records)

    scope = opportunity_radar.CollectionScope(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 31),
        depth="standard",
    )
    paths = opportunity_radar.create_run_paths(tmp_path, "range-run")
    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (opportunity_radar.Community("Cummins"),),
        paths=paths,
        as_of=as_of,
        scope=scope,
    )

    assert calls == [
        (
            "opencli", "opportunity-reddit", "range", "Cummins",
            "--start-date", "2026-01-01", "--end-date", "2026-08-31",
            "--limit", "1000", "-f", "json", "--window", "foreground",
            "--site-session", "persistent",
        )
    ]
    assert {item.post.post_id for item in result.candidates} == {"t3_first", "t3_middle"}
    coverage = result.coverage["Cummins"]
    assert coverage.status == "complete"
    assert coverage.actual_start == date(2026, 1, 1)
    assert coverage.actual_end == date(2026, 4, 15)


def test_complete_collection_omits_listing_cap_and_deep_reads_every_candidate(tmp_path) -> None:
    """Complete mode may stop on date/exhaustion, never on a project quota."""
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    listing = [
        _listing("one", created_at=datetime(2026, 8, 1, 12, tzinfo=UTC)),
        _listing("two", created_at=datetime(2026, 7, 1, 12, tzinfo=UTC)),
    ]
    calls: list[tuple[str, ...]] = []

    def runner(arguments: tuple[str, ...]) -> str:
        calls.append(arguments)
        if "range" in arguments:
            return json.dumps(listing)
        return "[]"

    paths = opportunity_radar.create_run_paths(tmp_path, "complete-run")
    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (opportunity_radar.Community("Cummins"),),
        paths=paths,
        as_of=as_of,
        scope=opportunity_radar.CollectionScope(date(2026, 1, 1), date(2026, 8, 31), "complete"),
        deep_read=True,
    )

    range_call = calls[0]
    assert "--limit" not in range_call
    assert {item.post.post_id for item in result.shortlisted} == {"t3_one", "t3_two"}
    read_calls = [call for call in calls if "read" in call]
    assert len(read_calls) == 2
    assert all("--complete" in call for call in read_calls)


def test_range_collection_marks_partial_when_oldest_post_misses_requested_start(tmp_path) -> None:
    """A capped listing must never be presented as complete annual coverage."""
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    records = [_listing("recent", created_at=datetime(2026, 6, 1, 12, tzinfo=UTC))]
    paths = opportunity_radar.create_run_paths(tmp_path, "partial-run")
    result = opportunity_radar.OpenCliCollector(
        runner=lambda _: json.dumps(records), sleeper=lambda _: None
    ).collect(
        (opportunity_radar.Community("Cummins"),),
        paths=paths,
        as_of=as_of,
        scope=opportunity_radar.CollectionScope(
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31), depth="standard"
        ),
    )

    assert result.coverage["Cummins"].status == "partial"
    assert result.coverage["Cummins"].actual_start == date(2026, 6, 1)


def test_range_collection_accepts_plugin_complete_hint_when_subreddit_has_no_post_on_start_day(tmp_path) -> None:
    """Exhausting pagination is complete coverage even if nobody posted on the exact first day."""
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    record = _listing("later", created_at=datetime(2026, 2, 1, 12, tzinfo=UTC))
    record["coverage_status"] = "complete"
    paths = opportunity_radar.create_run_paths(tmp_path, "complete-hint-run")
    result = opportunity_radar.OpenCliCollector(
        runner=lambda _: json.dumps([record]), sleeper=lambda _: None
    ).collect(
        (opportunity_radar.Community("Cummins"),), paths=paths, as_of=as_of,
        scope=opportunity_radar.CollectionScope(date(2026, 1, 1), date(2026, 8, 31)),
    )

    assert result.coverage["Cummins"].status == "complete"


def test_keyword_search_persists_per_term_coverage_and_marks_provider_failures_incomplete(tmp_path) -> None:
    """A failed global query cannot disappear behind a completed community listing."""
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    paths = opportunity_radar.create_run_paths(tmp_path, "keyword-coverage")
    complete = _listing("search-hit", created_at=datetime(2026, 2, 1, 12, tzinfo=UTC))
    complete["coverage_status"] = "complete"

    def runner(arguments: tuple[str, ...]) -> str:
        term = arguments[3]
        if term == "broken search":
            raise RuntimeError("Reddit search returned HTTP 429")
        return json.dumps([complete])

    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect_round_two(
        ("complete search", "broken search"), paths=paths, as_of=as_of,
        scope=opportunity_radar.CollectionScope(date(2026, 1, 1), date(2026, 8, 31), "complete"),
    )

    assert result.coverage["complete search"]["status"] == "complete"
    assert result.coverage["complete search"]["actual_start"] == "2026-02-01"
    assert result.coverage["broken search"]["status"] == "incomplete"
    assert result.coverage["broken search"]["stop_reason"] == "provider_error"


def test_stratified_shortlist_retains_months_and_controversial_signal() -> None:
    """Pure score ranking would erase older months and low-score contentious discussions."""
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    posts = []
    for month in range(1, 9):
        post = opportunity_radar.NormalizedPost(
            post_id=f"t3_month{month}",
            url=f"https://reddit.com/r/Cummins/comments/month{month}/example",
            subreddit="Cummins",
            title=f"Towing problem month {month}",
            body="Specific failure and fitment question",
            author=f"owner-{month}",
            created_at=datetime(2026, month, 15, 12, tzinfo=UTC),
            score=200 if month == 8 else month,
            comment_count=100 if month == 8 else month,
            source_surfaces=("controversial",) if month == 1 else ("new",),
        )
        window = opportunity_radar.PostWindow.CURRENT if (as_of - post.created_at) <= timedelta(days=90) else opportunity_radar.PostWindow.BASELINE
        posts.append(opportunity_radar.WindowedPost(post=post, window=window))

    selected = opportunity_radar.score_stratified_shortlist(posts, limit=8)

    assert len(selected) == 8
    assert {item.post.created_at.month for item in selected} == set(range(1, 9))
    assert "t3_month1" in {item.post.post_id for item in selected}


def test_collection_scope_rejects_ranges_longer_than_one_year() -> None:
    """An unbounded browser task would create misleading coverage and uncontrolled runtime."""
    try:
        opportunity_radar.CollectionScope(
            start_date=date(2025, 8, 1), end_date=date(2026, 8, 31), depth="standard"
        )
    except ValueError as error:
        assert "365" in str(error)
    else:
        raise AssertionError("expected range validation")


def test_run_cli_passes_selected_scope_depth_engine_and_communities(capsys) -> None:
    """Dropping web-selected run options at the CLI boundary would execute the wrong research task."""
    class RecordingApp:
        def __init__(self) -> None:
            self.received = None

        def run(self, config, *, run_id=None, scope=None, analysis_engine=None, selected_communities=()):
            self.received = (config, run_id, scope, analysis_engine, selected_communities)
            return {"status": "accepted"}

    app = RecordingApp()
    exit_code = main(
        [
            "run", "--config", "configs/diesel_90d.yaml", "--run-id", "range-cli",
            "--start-date", "2026-01-01", "--end-date", "2026-08-31",
            "--depth", "deep", "--analysis-engine", "codex",
            "--communities", "Cummins,Duramax",
        ],
        app=app,
    )

    assert exit_code == 0
    assert app.received[0:2] == ("configs/diesel_90d.yaml", "range-cli")
    assert app.received[2] == opportunity_radar.CollectionScope(
        date(2026, 1, 1), date(2026, 8, 31), "deep"
    )
    assert app.received[3:] == ("codex", ("Cummins", "Duramax"))
    assert json.loads(capsys.readouterr().out)["status"] == "accepted"
