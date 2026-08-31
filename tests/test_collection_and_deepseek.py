"""Offline contracts for the Reddit collector and DeepSeek boundary adapters."""

from datetime import UTC, datetime, timedelta
import json

import opportunity_radar
import pytest


def _listing(
    post_id: str,
    *,
    created_at: datetime,
    title: str = "Need a better part",
    subreddit: str = "diesel",
) -> dict:
    return {
        "id": post_id,
        "permalink": f"/r/diesel/comments/{post_id}/example/",
        "subreddit": subreddit,
        "title": title,
        "selftext": "The installed option failed after one winter.",
        "author": "owner",
        "created_utc": created_at.timestamp(),
        "score": 10,
        "num_comments": 4,
    }


class RecordingRunner:
    def __init__(self, listings: dict[str, str], reads: dict[str, list[object]] | None = None) -> None:
        self.listings = listings
        self.reads = reads or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments: tuple[str, ...]) -> str:
        self.calls.append(arguments)
        if arguments[2] == "read":
            response = self.reads[arguments[3]].pop(0)
            if isinstance(response, Exception):
                raise response
            return str(response)
        surface = arguments[5] if arguments[4] == "--sort" else arguments[2]
        if surface == "top":
            surface = f"top:{arguments[7]}"
        return self.listings[surface]


def test_collector_uses_all_listing_surfaces_preserves_raw_and_windows_candidates(tmp_path) -> None:
    """Changing an OpenCLI flag or discarding raw surfaces loses reproducible evidence."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    runner = RecordingRunner(
        {
            "hot": json.dumps([_listing("same", created_at=as_of - timedelta(days=7))]),
            "top:month": json.dumps([_listing("same", created_at=as_of - timedelta(days=7))]),
            "top:year": json.dumps([_listing("old", created_at=as_of - timedelta(days=91))]),
            "new": json.dumps([_listing("baseline", created_at=as_of - timedelta(days=60))]),
        }
    )
    paths = opportunity_radar.create_run_paths(tmp_path, "run-1")

    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (opportunity_radar.Community("diesel"),), paths=paths, as_of=as_of
    )

    assert runner.calls == [
            ("opencli", "reddit", "subreddit", "diesel", "--sort", "hot", "--limit", "50", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
            ("opencli", "reddit", "subreddit", "diesel", "--sort", "top", "--time", "month", "--limit", "50", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
            ("opencli", "reddit", "subreddit", "diesel", "--sort", "top", "--time", "year", "--limit", "100", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
            ("opencli", "reddit", "subreddit", "diesel", "--sort", "new", "--limit", "50", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
    ]
    assert [entry.post.post_id for entry in result.candidates] == ["t3_same", "t3_baseline"]
    assert result.candidates[0].post.source_surfaces == ("hot", "top_month")
    assert [entry.window for entry in result.candidates] == [
        opportunity_radar.PostWindow.CURRENT,
        opportunity_radar.PostWindow.BASELINE,
    ]
    assert (paths.raw_dir / "listings" / "diesel__top_year.json").exists()


def test_collector_checkpoints_successes_retries_failures_and_never_deep_reads_more_than_limit(tmp_path) -> None:
    """Resume must avoid wasting calls while retaining structured records for incomplete posts."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    listings = {surface: json.dumps([_listing("one", created_at=as_of - timedelta(days=2)), _listing("two", created_at=as_of - timedelta(days=3))]) for surface in ("hot", "top:month", "top:year", "new")}
    runner = RecordingRunner(listings, {"one": [RuntimeError("temporary failure"), json.dumps([{"id": "c1", "body": "It cracked after winter."}])], "two": [json.dumps([])]})
    paths = opportunity_radar.create_run_paths(tmp_path, "run-2")
    collector = opportunity_radar.OpenCliCollector(
        runner=runner,
        settings=opportunity_radar.CollectionSettings(request_interval_seconds=1.25),
        sleeper=lambda _: None,
    )

    first = collector.collect((opportunity_radar.Community("diesel"),), paths=paths, as_of=as_of, deep_read=True, shortlist_limit=1)
    second = collector.collect((opportunity_radar.Community("diesel"),), paths=paths, as_of=as_of, deep_read=True, shortlist_limit=1)

    assert len(first.deep_reads) == 0
    assert first.failures[0].post_id == "t3_one"
    assert len(second.deep_reads) == 1
    assert second.deep_reads[0].post.post_id == "t3_one"
    reads = [call for call in runner.calls if call[2] == "read"]
    assert reads == [
        ("opencli", "opportunity-reddit", "read", "one", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-rounds", "5", "--max-length", "5000"),
        ("opencli", "opportunity-reddit", "read", "one", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-rounds", "5", "--max-length", "5000"),
    ]
    assert json.loads((paths.checkpoints_dir / "t3_one.json").read_text(encoding="utf-8"))["status"] == "success"


def test_collector_caps_each_community_deep_read_at_thirty_posts(tmp_path) -> None:
    """A configured value above 30 must not turn deep reading into an unbounded scrape."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    records = [_listing(f"post{number}", created_at=as_of - timedelta(days=1), title=f"Post {number}") for number in range(31)]
    runner = RecordingRunner(
        {surface: json.dumps(records) for surface in ("hot", "top:month", "top:year", "new")},
        {f"post{number}": [json.dumps([])] for number in range(31)},
    )
    paths = opportunity_radar.create_run_paths(tmp_path, "run-3")

    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (opportunity_radar.Community("diesel"),), paths=paths, as_of=as_of, deep_read=True, shortlist_limit=99
    )

    assert len(result.shortlisted) == 30
    assert len([call for call in runner.calls if call[2] == "read"]) == 30


def test_collector_materializes_generator_communities_before_reusing_them(tmp_path) -> None:
    """Generator inputs must survive the second pass that windows, shortlists, and deep-reads posts."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    runner = RecordingRunner(
        {surface: json.dumps([_listing("one", created_at=as_of - timedelta(days=2))]) for surface in ("hot", "top:month", "top:year", "new")},
        {"one": [json.dumps([{"id": "c1", "body": "Still broken."}])]},
    )
    paths = opportunity_radar.create_run_paths(tmp_path, "run-generator")

    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (community for community in (opportunity_radar.Community("diesel"),)),
        paths=paths,
        as_of=as_of,
        deep_read=True,
    )

    assert [entry.post.post_id for entry in result.candidates] == ["t3_one"]
    assert [entry.post.post_id for entry in result.shortlisted] == ["t3_one"]
    assert [entry.post.post_id for entry in result.deep_reads] == ["t3_one"]


def test_collector_caps_deep_reads_per_requested_community_even_when_records_share_a_subreddit(tmp_path) -> None:
    """Collector limits must be scoped to the approved communities being queried."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    shared_subreddit = "shared"
    diesel_records = [
        _listing(
            f"diesel{number}",
            created_at=as_of - timedelta(days=1),
            title=f"Diesel {number}",
            subreddit=shared_subreddit,
        )
        for number in range(31)
    ]
    powerstroke_records = [
        _listing(
            f"powerstroke{number}",
            created_at=as_of - timedelta(days=1),
            title=f"Powerstroke {number}",
            subreddit=shared_subreddit,
        )
        for number in range(31)
    ]
    runner = RecordingRunner(
        {
            "hot": json.dumps(powerstroke_records),
            "top:month": json.dumps(powerstroke_records),
            "top:year": json.dumps(powerstroke_records),
            "new": json.dumps(powerstroke_records),
        },
        {record["id"]: [json.dumps([])] for record in diesel_records + powerstroke_records},
    )
    community_surfaces = {
        "diesel": diesel_records,
        "powerstroke": powerstroke_records,
    }

    def per_community_runner(arguments: tuple[str, ...]) -> str:
        if arguments[2] == "read":
            return runner(arguments)
        community = arguments[3]
        runner.calls.append(arguments)
        return json.dumps(community_surfaces[community])

    paths = opportunity_radar.create_run_paths(tmp_path, "run-3b")

    result = opportunity_radar.OpenCliCollector(runner=per_community_runner, sleeper=lambda _: None).collect(
        (
            opportunity_radar.Community("diesel"),
            opportunity_radar.Community("powerstroke"),
        ),
        paths=paths,
        as_of=as_of,
        deep_read=True,
        shortlist_limit=99,
    )

    shortlisted_ids = [entry.post.post_id for entry in result.shortlisted]
    assert len(shortlisted_ids) == 60
    assert len([post_id for post_id in shortlisted_ids if post_id.startswith("t3_diesel")]) == 30
    assert len([post_id for post_id in shortlisted_ids if post_id.startswith("t3_powerstroke")]) == 30
    assert len([call for call in runner.calls if call[2] == "read"]) == 60


def test_collector_uses_time_sleep_by_default_and_honors_default_and_configured_intervals(tmp_path, monkeypatch) -> None:
    """Default production pacing must sleep three seconds unless a test injects its own sleeper."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    listings = {
        surface: json.dumps(
            [
                _listing("one", created_at=as_of - timedelta(days=2)),
                _listing("two", created_at=as_of - timedelta(days=3)),
            ]
        )
        for surface in ("hot", "top:month", "top:year", "new")
    }
    reads = {
        "one": [json.dumps([])],
        "two": [json.dumps([])],
    }
    default_sleeps: list[float] = []
    monkeypatch.setattr("opportunity_radar.collector.time.sleep", default_sleeps.append)

    default_paths = opportunity_radar.create_run_paths(tmp_path, "run-4a")
    opportunity_radar.OpenCliCollector(runner=RecordingRunner(listings, reads.copy())).collect(
        (opportunity_radar.Community("diesel"),),
        paths=default_paths,
        as_of=as_of,
        deep_read=True,
    )

    configured_sleeps: list[float] = []
    configured_paths = opportunity_radar.create_run_paths(tmp_path, "run-4b")
    opportunity_radar.OpenCliCollector(
        runner=RecordingRunner(
            listings,
            {
                "one": [json.dumps([])],
                "two": [json.dumps([])],
            },
        ),
        settings=opportunity_radar.CollectionSettings(request_interval_seconds=1.25),
        sleeper=configured_sleeps.append,
    ).collect(
        (opportunity_radar.Community("diesel"),),
        paths=configured_paths,
        as_of=as_of,
        deep_read=True,
    )

    assert default_sleeps == [3.0]
    assert configured_sleeps == [1.25]


def test_collector_preserves_raw_listing_text_before_json_parsing_failures(tmp_path) -> None:
    """Malformed OpenCLI listing JSON must still be written to disk for diagnosis."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    malformed = "{not valid json"
    runner = RecordingRunner(
        {
            "hot": malformed,
            "top:month": json.dumps([]),
            "top:year": json.dumps([]),
            "new": json.dumps([]),
        }
    )
    paths = opportunity_radar.create_run_paths(tmp_path, "run-4c")

    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (opportunity_radar.Community("diesel"),),
        paths=paths,
        as_of=as_of,
    )

    assert len(result.failures) == 1
    assert result.failures[0].post_id is None
    assert result.failures[0].stage == "listing:diesel:hot"
    assert result.failures[0].message == "JSONDecodeError: external operation failed"
    assert (paths.raw_dir / "listings" / "diesel__hot.json").read_text(encoding="utf-8") == malformed


def test_collector_skips_successful_checkpoints_on_third_run_and_retries_failures(tmp_path, monkeypatch) -> None:
    """Successful deep reads should stop calling OpenCLI on later runs while failed checkpoints can recover."""
    import importlib

    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    listings = {
        surface: json.dumps(
            [
                _listing("one", created_at=as_of - timedelta(days=2)),
                _listing("two", created_at=as_of - timedelta(days=3)),
            ]
        )
        for surface in ("hot", "top:month", "top:year", "new")
    }
    runner = RecordingRunner(
        listings,
        {
            "one": [RuntimeError("temporary failure"), json.dumps([{"id": "c1", "body": "Recovered."}])],
            "two": [json.dumps([{"id": "c2", "body": "Succeeded first."}])],
        },
    )
    paths = opportunity_radar.create_run_paths(tmp_path, "run-4d")
    collector = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None)
    collector_module = importlib.import_module("opportunity_radar.collector")
    original_read_checkpoint = collector_module._read_checkpoint
    checkpoint_reads: list[str] = []

    def recording_read_checkpoint(path):
        checkpoint_reads.append(path.name)
        return original_read_checkpoint(path)

    monkeypatch.setattr(collector_module, "_read_checkpoint", recording_read_checkpoint)

    first = collector.collect(
        (opportunity_radar.Community("diesel"),),
        paths=paths,
        as_of=as_of,
        deep_read=True,
        shortlist_limit=2,
    )
    second = collector.collect(
        (opportunity_radar.Community("diesel"),),
        paths=paths,
        as_of=as_of,
        deep_read=True,
        shortlist_limit=2,
    )
    checkpoint_reads.clear()
    third = collector.collect(
        (opportunity_radar.Community("diesel"),),
        paths=paths,
        as_of=as_of,
        deep_read=True,
        shortlist_limit=2,
    )

    read_calls = [call for call in runner.calls if call[2] == "read"]
    assert [entry.post.post_id for entry in first.deep_reads] == ["t3_two"]
    assert [failure.post_id for failure in first.failures] == ["t3_one"]
    assert [entry.post.post_id for entry in second.deep_reads] == ["t3_one", "t3_two"]
    assert [entry.post.post_id for entry in third.deep_reads] == ["t3_one", "t3_two"]
    assert checkpoint_reads == []
    assert read_calls == [
        ("opencli", "opportunity-reddit", "read", "one", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-rounds", "5", "--max-length", "5000"),
        ("opencli", "opportunity-reddit", "read", "two", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-rounds", "5", "--max-length", "5000"),
        ("opencli", "opportunity-reddit", "read", "one", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-rounds", "5", "--max-length", "5000"),
    ]


def test_collector_failure_records_and_failed_checkpoints_include_the_community(tmp_path) -> None:
    """Failures need explicit community attribution both in memory and on disk."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    listings = {
        surface: json.dumps([_listing("one", created_at=as_of - timedelta(days=2), subreddit="shared")])
        for surface in ("hot", "top:month", "top:year", "new")
    }
    runner = RecordingRunner(listings, {"one": [RuntimeError("temporary failure")]})
    paths = opportunity_radar.create_run_paths(tmp_path, "run-4e")

    result = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None).collect(
        (opportunity_radar.Community("diesel"),),
        paths=paths,
        as_of=as_of,
        deep_read=True,
    )

    assert result.failures == (
        opportunity_radar.CollectionFailure(
            community="diesel",
            post_id="t3_one",
            stage="deep_read",
            message="RuntimeError: external operation failed",
        ),
    )
    assert json.loads((paths.checkpoints_dir / "t3_one.json").read_text(encoding="utf-8")) == {
        "community": "diesel",
        "message": "RuntimeError: external operation failed",
        "post_id": "t3_one",
        "stage": "deep_read",
        "status": "failed",
    }


def test_collector_round_two_preserves_raw_deduplicates_and_retries_only_failed_terms(tmp_path) -> None:
    """A resumed expansion must reuse successful queries and never let one failed term stop its peers."""
    as_of = datetime(2026, 8, 26, tzinfo=UTC)
    calls: list[tuple[str, ...]] = []
    attempts = {"heavy duty clamp kit": 0, "egr coolant cap": 0}

    def runner(arguments: tuple[str, ...]) -> str:
        calls.append(arguments)
        term = arguments[3]
        attempts[term] += 1
        if term == "egr coolant cap" and attempts[term] == 1:
            raise RuntimeError("temporary throttle")
        identifier = "same" if term == "heavy duty clamp kit" else "new"
        return json.dumps([_listing(identifier, created_at=as_of - timedelta(days=2), subreddit="Cummins")])

    paths = opportunity_radar.create_run_paths(tmp_path, "round-two")
    collector = opportunity_radar.OpenCliCollector(runner=runner, sleeper=lambda _: None)
    first = collector.collect_round_two(
        ("heavy duty clamp kit", "egr coolant cap"), paths=paths, as_of=as_of
    )
    second = collector.collect_round_two(
        ("heavy duty clamp kit", "egr coolant cap"), paths=paths, as_of=as_of,
        existing_candidates=first.candidates,
    )

    assert [entry.post.post_id for entry in first.candidates] == ["t3_same"]
    assert [failure.stage for failure in first.failures] == ["keyword:egr coolant cap"]
    assert [entry.post.post_id for entry in second.candidates] == ["t3_same", "t3_new"]
    assert [call[3] for call in calls] == ["heavy duty clamp kit", "egr coolant cap", "egr coolant cap"]
    assert (paths.raw_dir / "listings" / "keyword__heavy_duty_clamp_kit.json").exists()
    checkpoint = json.loads((paths.checkpoints_dir / "round_two.json").read_text(encoding="utf-8"))
    assert checkpoint["queries"]["heavy duty clamp kit"]["status"] == "success"
    assert checkpoint["queries"]["egr coolant cap"]["status"] == "success"


def test_thread_comments_preserve_author_ids_for_distinct_commenter_counts() -> None:
    """Deep-read normalization must retain public commenter authors, not only text and URLs."""
    post = opportunity_radar.NormalizedPost(
        post_id="t3_thread_fixture", url="https://www.reddit.com/r/diesel/comments/thread_fixture/example",
        subreddit="diesel", title="Fixture", body="Body", author="owner",
        created_at=datetime(2026, 8, 25, tzinfo=UTC), score=1, comment_count=1, source_surfaces=("hot",),
    )
    document = opportunity_radar.collector._thread_from_raw(
        [{"id": "c1", "author": "commenter-a", "body": "Useful reply", "permalink": "https://reddit.com/c1"}],
        post,
    )

    assert document.comments[0].author == "commenter-a"
    assert document.comment_authors == ("commenter-a",)


class FakeTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str], dict]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], payload: dict) -> object:
        self.calls.append((method, url, headers, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_deepseek_retries_malformed_json_then_filters_unsupported_claim_evidence() -> None:
    """Malformed model output and invented citations must not become evidence-backed conclusions."""
    post = opportunity_radar.NormalizedPost(
        post_id="t3_post", url="https://www.reddit.com/r/diesel/comments/post/example", subreddit="diesel",
        title="Broken part", body="My part failed.", author="owner", created_at=datetime(2026, 8, 25, tzinfo=UTC), score=1, comment_count=1, source_surfaces=("hot",),
    )
    thread = opportunity_radar.ThreadDocument(post=post, comments=(opportunity_radar.ThreadComment("c1", "It cracked after winter.", post.url + "?comment=c1"),))
    transport = FakeTransport([
        opportunity_radar.HttpResponse(200, '{not json'),
        opportunity_radar.HttpResponse(200, json.dumps({"choices": [{"message": {"content": json.dumps({"topics": [{"label": "winter durability", "evidence_ids": ["post", "c1"]}], "claims": [{"claim": "cracks in winter", "evidence_ids": ["c1"], "urls": [post.url + "?comment=c1"]}, {"claim": "unsupported", "evidence_ids": ["missing"], "urls": ["https://invented.example"]}]})}}]})),
    ])
    client = opportunity_radar.DeepSeekClient(transport=transport, environment={"DEEPSEEK_API_KEY": "very-secret-key"}, sleeper=lambda _: None)

    analysis = client.extract_post(thread)

    assert len(transport.calls) == 2
    assert transport.calls[0][0:2] == ("POST", "https://api.deepseek.com/v1/chat/completions")
    assert transport.calls[0][3]["model"] == "deepseek-v4-flash"
    assert transport.calls[0][3]["response_format"] == {"type": "json_object"}
    assert analysis.topics[0].evidence_ids == ("post", "c1")
    assert analysis.claims[0].evidence_ids == ("c1",)
    assert analysis.claims[1].status == "unknown"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "DEEPSEEK_API_KEY"), (404, "base URL"), (429, "频繁")],
)
def test_deepseek_errors_are_actionable_and_do_not_leak_the_key(status: int, message: str) -> None:
    """Diagnostic errors must help operators without putting credentials into logs or exceptions."""
    transport = FakeTransport([opportunity_radar.HttpResponse(status, "very-secret-key")] * (3 if status == 429 else 1))
    client = opportunity_radar.DeepSeekClient(transport=transport, environment={"DEEPSEEK_API_KEY": "very-secret-key"}, sleeper=lambda _: None)

    with pytest.raises(opportunity_radar.DeepSeekError, match=message) as error:
        client.chat_json([{"role": "user", "content": "hello"}])

    assert "very-secret-key" not in str(error.value)
    assert len(transport.calls) == (3 if status == 429 else 1)
