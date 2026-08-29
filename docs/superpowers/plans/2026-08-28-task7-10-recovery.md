# V1.2 Task 7–10 Recovery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation tasks and keep each workstream independently testable.

**Goal:** Resolve the real-run failures documented in `docs/HANDOFF-report-run-2026-08-28.md`, finish Tasks 7–10, and publish a verified V1.2 branch without changing `main` or `v1.1.0`.

**Architecture:** Keep deterministic rules authoritative. Add stage-hashed checkpoints and append-only failure attempts first; add DSV4Pro only as schema/provenance-checked enrichment with rule fallback; expose one overnight CLI/handoff contract; then integrate and run a bounded real pilot. Shared pipeline/report files are changed only by the integration owner after workstream outputs are reviewed.

**Tech Stack:** Node.js 20 ESM, native `node:test`, PowerShell 7, JSON/JSONL artifacts, self-contained HTML, OpenAI-compatible `dsv4pro`.

## Global constraints

- Public Reddit read-only data only; individual item failures never stop unrelated work.
- Formal keywords remain immutable; discovered terms stay exploratory and require explicit gates.
- DSV4Pro cannot delete rule evidence, invent IDs, bypass thresholds, or turn unknown commercial fields into facts.
- No secrets, cookies, tokens, personal paths, or sensitive inferred demographics in repository artifacts.
- Preserve `main` and `v1.1.0`; use normal push only after all verification and user-authorized release steps.

## Workstream A — Task 7 checkpoint and failure audit

- Repair the Windows worktree `.git` pointer before any commit operation; verify branch and tag identities read correctly.
- Implement `src/checkpoint-store.mjs` with stable SHA-256 input hashes, atomic metadata/payload writes, exact-match reuse, and append-only `failure_attempts.jsonl`.
- Integrate unresolved-failure retry semantics into `src/radar-pipeline.mjs`: preserve historical attempts, keep `failures.jsonl` unresolved-only, retain immutable first config snapshot, detect drift, and separate technical status from `sample_status`/`persona_status`.
- Preserve synthetic OpenCLI comment IDs as deterministic but mark link precision as limited; never treat them as real IDs.
- Add tests for stale checkpoints, failed-then-successful resume, duplicate-success avoidance, config drift, low sample not complete, and manifest count consistency.

## Workstream B — Task 8 DSV4Pro and real-run quality

- Implement `validateEnrichment(result, allowedEvidenceIds)` and `schemas/dsv4pro-enrichment.schema.json`.
- Add bounded OpenAI-compatible retries (two attempts, 30-second wait), model identifier exactly `dsv4pro`, and fallback to rules for invalid JSON, schema errors, unknown evidence IDs, timeout, or rate limit.
- Preserve rule output and formal keyword immutability during merge.
- Evaluate the real-run quality problem without weakening universal hard exclusions: permit only auditable, explicitly configured market-level adjustments; retain uncertain geography as unknown unless DSV4Pro cites supplied evidence.
- Add tests for malformed output, unknown IDs, invented facts, valid enrichment, retry bounds, and rule fallback.

## Workstream C — Task 9 CLI and Hermes handoff

- Add `--profile overnight`, `--max-runtime-minutes 600`, `--llm-model dsv4pro`, and existing run/resume flags.
- Add `configs/automotive_lighting_us_overnight_v1.2.json` with round-one 300 target/400 hard max, deep dive 100, comments 20, authors 60, author activities 50/180 days, round-two 20 terms/10 posts, combined max 500.
- Write bilingual `.agents/HERMES_HANDOFF_V1.2.md`, `.agents/PROGRESS.md`, `.agents/OUTBOX.md` with exact repo/branch checks, secret-presence-only preflight, OpenCLI `--expand-more false`, retry waits (Reddit 15/45 seconds, DSV4Pro 30 seconds), stop/non-stop conditions, artifacts, acceptance commands, and no-push prohibition for Hermes.
- Add contract tests and dry-run every non-network command; no absolute personal paths.

## Integration — Task 10

- Reconcile workstream changes in the single runner/report owner; update README, data contract, baseline guide, and GitHub Actions artifact upload without write permissions.
- Run all Node tests plus portable runtime/config/project/UTF-8/interface checks and secret scan.
- Run a bounded public-transport pilot, then resume unresolved items and inspect JSON/HTML equality, evidence exclusions, opportunities, keyword cloud, personas, failures, and offline interactions.
- Run Hermes ambiguity self-review from a clean checkout; confirm technical completion versus business sample sufficiency.
- Confirm `v1.1.0` resolves to `5ed1de6`, create annotated `v1.2.0`, and push the existing feature branch and tag normally; never force-push or modify `main`.

## Execution order and review gates

1. Repair worktree pointer and dispatch A/B/C in parallel with disjoint file ownership.
2. Review each workstream independently; fix Critical/Important findings and re-review.
3. Integrate only after A/B/C are Ready; run Task 10 verification and bounded pilot.
4. Publish only after the final verification-before-completion gate passes.
