"""Offline contracts for the Reddit collector and DeepSeek boundary adapters."""

from datetime import UTC, datetime, timedelta
import json

import opportunity_radar
import pytest


def _listing(post_id: str, *, created_at: datetime, title: str = "Need a better part") -> dict:
    return {
        "id": post_id,
        "permalink": f"/r/diesel/comments/{post_id}/example/",
        "subreddit": "diesel",
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
        return self.listings[arguments[2] + (":" + arguments[5] if arguments[2] == "top" else "")]


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
        ("opencli", "reddit", "hot", "diesel", "--limit", "50", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
        ("opencli", "reddit", "top", "diesel", "--time", "month", "--limit", "50", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
        ("opencli", "reddit", "top", "diesel", "--time", "year", "--limit", "100", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
        ("opencli", "reddit", "new", "diesel", "--limit", "50", "-f", "json", "--window", "foreground", "--site-session", "persistent"),
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
        ("opencli", "reddit", "read", "one", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-more", "true", "--expand-rounds", "5", "--max-length", "5000"),
        ("opencli", "reddit", "read", "one", "-f", "json", "--window", "foreground", "--site-session", "persistent", "--sort", "best", "--limit", "100", "--depth", "3", "--replies", "20", "--expand-more", "true", "--expand-rounds", "5", "--max-length", "5000"),
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
