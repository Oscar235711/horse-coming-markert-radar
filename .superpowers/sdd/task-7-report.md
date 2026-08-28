# Task 7 Report

Date: 2026-08-28

## Scope

Implement Task 7 on top of `codex/automotive-lighting-reddit-radar` without disturbing existing branch history or unrelated worktree changes. The required slice was limited to stage-hashed checkpoints, append-only failure history, immutable config snapshot resume semantics, and manifest status/count reporting.

## What Changed

- Added `src/checkpoint-store.mjs` with deterministic SHA-256 input hashing plus atomic stage metadata/payload writes and exact-match reuse.
- Reworked `src/radar-pipeline.mjs` so first-round search, detail fetches, and round-two exploratory searches all reuse stage checkpoints when the input hash and schema version still match.
- Preserved `config.snapshot.json` as first-write immutable while detecting drift internally:
  - incomplete runs stay locked to the original snapshot and retry only unresolved work;
  - completed runs may reuse successful stage checkpoints and run only newly dependent queries.
- Introduced append-only `failure_attempts.jsonl` records with stable attempt counting, retryability, transport, and error-category metadata.
- Kept `failures.jsonl` as the current unresolved failure set only, so a later successful resume clears current failures without erasing history.
- Extended the run manifest contract with `unresolved_failures` and `cumulative_attempts`, and made pipeline `status`, `sample_status`, and `persona_status` independent.
- Added a guarded low-sample completion rule via `limits.minimum_complete_candidates` so operators can prevent under-target runs from being marked technically complete without overloading `deep_dive_posts`.

## TDD Evidence

- Added `tests/checkpoint-store.test.mjs` first, covering stable hashing and exact-match checkpoint reuse/invalidation.
- Extended `tests/radar-pipeline.test.mjs` first for:
  - append-only failure history with unresolved-only resume;
  - config drift that reruns only newly dependent search stages after a complete prior run;
  - incomplete-run snapshot freezing that preserves the first-round plan during resume;
  - low-sample runs that remain `partial` when `minimum_complete_candidates` is not met.
- Extended `tests/schema-contract.test.mjs` first for the new manifest fields.
- Verified RED with:
  - `node --test tests/checkpoint-store.test.mjs tests/radar-pipeline.test.mjs tests/schema-contract.test.mjs`
  - initial failure was the missing `src/checkpoint-store.mjs` module plus missing manifest semantics.

## Verification

- Focused Task 7 suite:
  - `node --test tests/checkpoint-store.test.mjs tests/radar-pipeline.test.mjs tests/schema-contract.test.mjs`
- Full Node suite:
  - `node --test`
  - Result: 118 tests passed, 0 failed.
- Diff hygiene:
  - `git diff --check`
  - Result: no whitespace errors; Git only reported Windows CRLF normalization warnings.

## Notes

- OpenCLI synthetic comment IDs remain deterministic and post-scoped; Task 7 did not change their identifier scheme or claim comment-level permalink precision that the upstream transport does not provide.
- No edits were made to `src/llm-client.mjs`, CLI files, Hermes handoff files, `main`, tags, or push state.
- The worktree still contains unrelated pre-existing changes outside Task 7 scope, including `src/llm-client.mjs`, `schemas/dsv4pro-enrichment.schema.json`, and `tests/llm-client.test.mjs`; they were preserved untouched.
