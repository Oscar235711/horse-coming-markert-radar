# Task 2 report — Reddit collector and DeepSeek client

## Delivered

- `src/opportunity_radar/collector.py`: injected OpenCLI boundary, the four fixed listing surfaces, raw surface artifacts, existing normalization/windowing/shortlisting reuse, a hard 30-post/community deep-read cap, persistent per-post checkpoints, and secret-free structured failures.
- `src/opportunity_radar/deepseek.py`: injected HTTP boundary for `https://api.deepseek.com/v1/chat/completions`, Flash/Pro model constants, JSON mode, safe 401/404/429 Chinese diagnostics, bounded transient/malformed-JSON retries, and evidence-grounded typed Flash extraction.
- `tests/test_collection_and_deepseek.py`: deterministic fake process/HTTP tests only; no network calls.

## TDD evidence

1. RED: `pytest tests/test_collection_and_deepseek.py -q` reported six expected failures because the new collector/DeepSeek public interfaces did not yet exist.
2. GREEN: after the minimal boundary implementations, the focused suite passed (`6 passed`).
3. RED: cap test reported `assert 31 == 30` after temporarily removing the hard cap.
4. GREEN: restoring the smallest cap implementation produced `7 passed`.
5. RED: rate-limit retry test reported `assert 1 == 3` before retrying HTTP 429.
6. GREEN: rate-limit retries then produced `7 passed`.

## Verification

- `pytest` — `22 passed in 0.14s`.
- `git diff --check` — no whitespace errors (only a Git line-ending warning for the pre-existing tracked `__init__.py`).
- Manual source audit confirms request headers are constructed only at the injected transport boundary and are never logged or persisted; checkpoints store only status, post identifiers, and thread JSON.

## Files for this task

- `src/opportunity_radar/__init__.py`
- `src/opportunity_radar/collector.py`
- `src/opportunity_radar/deepseek.py`
- `tests/test_collection_and_deepseek.py`
- `.superpowers/sdd/task-2-report.md`

## Follow-up concern

The exact OpenCLI command forms are based on the repository's established `reddit read` invocation; a live acceptance run is still appropriate once the user provides a controlled Chrome session. No live calls were made here.

## Fix round 1 — collector follow-ups

Committed behavioral fix as `582ff6a3d406ba19775f70b30d7adcbf7260e594` (`fix: harden collector checkpoint and failure handling`).

### RED / GREEN evidence

1. Per-requested-community shortlist cap
   - RED: `python -m pytest tests/test_collection_and_deepseek.py::test_collector_caps_deep_reads_per_requested_community_even_when_records_share_a_subreddit -v` — failed with `assert 30 == 60`; collector merged two requested communities into one 30-post bucket when the returned records shared a `subreddit` value.
   - GREEN: reran the same command — `1 passed in 0.12s`.
   - Full verification after the fix: `python -m pytest -q` — `27 passed`.

2. Production default sleeper and interval injection
   - RED: `python -m pytest tests/test_collection_and_deepseek.py::test_collector_uses_time_sleep_by_default_and_honors_default_and_configured_intervals -v` — failed with `ImportError: import error in opportunity_radar.collector.time`; the collector never bound `time.sleep`.
   - GREEN: reran the same command — `1 passed in 0.10s`; the default path now sleeps `3.0` seconds and injected test sleepers still record configured intervals such as `1.25`.
   - Full verification after the fix: `python -m pytest -q` — `27 passed`.

3. Raw listing persistence before JSON parsing
   - RED: in a temporary worktree pinned to `d7d0df8`, `python -m pytest -c pyproject.toml D:/zuop/malai/opportunity-radar-community-radar/tests/test_collection_and_deepseek.py::test_collector_preserves_raw_listing_text_before_json_parsing_failures -v` — failed with `FileNotFoundError` for `raw/listings/diesel__hot.json`; malformed JSON was not preserved.
   - GREEN: on the current branch, reran `python -m pytest tests/test_collection_and_deepseek.py::test_collector_preserves_raw_listing_text_before_json_parsing_failures -v` — `1 passed in 0.07s`.
   - Full verification after the fix: `python -m pytest -q` — `27 passed`.

4. Successful checkpoint reuse on a third run
   - RED: in a temporary worktree pinned to `d7d0df8`, `python -m pytest -c pyproject.toml D:/zuop/malai/opportunity-radar-community-radar/tests/test_collection_and_deepseek.py::test_collector_skips_successful_checkpoints_on_third_run_and_retries_failures -v` — failed with `assert ['t3_one.json', 't3_two.json'] == []`; successful checkpoints were still read again on the third pass.
   - GREEN: on the current branch, reran `python -m pytest tests/test_collection_and_deepseek.py::test_collector_skips_successful_checkpoints_on_third_run_and_retries_failures -v` — `1 passed in 0.15s`.
   - Full verification after the fix: `python -m pytest -q` — `27 passed`.

5. Explicit failure community field and failed-checkpoint serialization
   - RED: in a temporary worktree pinned to `d7d0df8`, `python -m pytest -c pyproject.toml D:/zuop/malai/opportunity-radar-community-radar/tests/test_collection_and_deepseek.py::test_collector_failure_records_and_failed_checkpoints_include_the_community -v` — failed with `TypeError: CollectionFailure.__init__() got an unexpected keyword argument 'community'`.
   - GREEN: on the current branch, reran `python -m pytest tests/test_collection_and_deepseek.py::test_collector_failure_records_and_failed_checkpoints_include_the_community -v` — `1 passed in 0.07s`.
   - Full verification after the fix: `python -m pytest -q` — `27 passed`.

### Final verification

- `python -m pytest tests/test_collection_and_deepseek.py -q` — `12 passed`.
- `python -m pytest -q` — `27 passed`.
- `git diff --check` — exit 0; Git emitted only LF->CRLF working-copy warnings for `src/opportunity_radar/collector.py` and `tests/test_collection_and_deepseek.py`.

### Changed files

- `src/opportunity_radar/collector.py`
- `tests/test_collection_and_deepseek.py`
- `.superpowers/sdd/task-2-report.md`

### Behavior delivered in this round

- Collector shortlisting is now explicitly scoped to each requested community, even when listing payloads share the same `subreddit` metadata.
- The default deep-read pacing path uses production `time.sleep`, while tests can still inject recording or no-op sleepers and verify the default `3.0` second interval.
- Raw listing text is written before JSON parsing so malformed payloads remain available for diagnosis.
- Successful checkpoints are cached after a successful retry and are not re-read on a third pass through the same collector instance; failed checkpoints still retry.
- Structured failures now carry an explicit `community` field, and failed checkpoint JSON stores that same community value.
