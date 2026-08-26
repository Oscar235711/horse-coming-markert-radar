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
