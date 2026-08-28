# Task 9 Report

Date: 2026-08-28

Scope:

- added the overnight V1.2 research profile and ceiling config;
- extended the CLI and PowerShell entrypoints for `--profile overnight`, `--max-runtime-minutes 600`, and `--llm-model dsv4pro`;
- added bilingual Hermes handoff, progress, and outbox contracts;
- added Task 9 contract tests and interface checks.

Verification commands:

```powershell
node --test tests/radar-cli.test.mjs tests/hermes-handoff-contract.test.mjs
.\tests\verify-lighting-interface.ps1
.\scripts\radar.ps1 paths
node --test "tests/*.test.mjs"
git diff --check
```

Notes:

- no personal absolute paths were added;
- no secrets were stored or printed;
- Hermes remains prohibited from `git push`, tagging, merging, or mutating formal keywords.
- focused Task 9 tests passed;
- interface smoke check passed and `.\scripts\radar.ps1 paths` remained non-network;
- full `node --test "tests/*.test.mjs"` still fails on pre-existing Task 7/8 gaps:
  - `tests/llm-client.test.mjs` expects `validateEnrichment` from `src/llm-client.mjs`;
  - `tests/schema-contract.test.mjs` expects `schemas/dsv4pro-enrichment.schema.json` and `manifest.required.includes('unresolved_failures')`;
  - `tests/radar-pipeline.test.mjs` still expects failure-attempt tracking and low-sample `partial` status semantics.
