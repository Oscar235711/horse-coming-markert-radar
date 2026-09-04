# Opportunity Radar workflow contract

## Inputs

```text
start_date, end_date       inclusive UTC calendar dates, at most 365 days
communities                one or more seed/catalog names; evidence-qualified discoveries join the next run automatically
keywords                   optional subset of active project keywords; empty means the configured diesel dictionary plus active library
depth                      quick, standard, deep, or complete
analysis_engine            deepseek for the production workflow; codex only for a local fallback explicitly selected by the user
```

## Stages and checkpoints

```text
configured
  → community_listings
  → keyword_search
  → normalized
  → deep_read
  → evidence_gate
  → post_analysis
  → topic_consolidation
  → exported
```

The run directory is `.local/runs/<run_id>/`. Raw files are immutable evidence. Checkpoint files make a failed page, model call, or browser lease retryable without discarding successful work. A single post failure is recorded in `failures.jsonl` and must not erase the rest of the run.

## Data expansion loop

The community catalog is the initial surface, not a claim that only four communities exist. Search results can record observed communities and DeepSeek/Codex can discover candidate terms, but those candidates remain in the project library as observed/review rows until the configured promotion rule is met. Every later run loads only active rows. A schedule therefore gets a growing, traceable vocabulary without editing code.

## Rate limiting

OpenCLI uses the authenticated Chrome session and Reddit's public web endpoints. HTTP 429, browser lease failure, or a missing cursor is not evidence of zero demand. Preserve the checkpoint, expose `retryable: true`, wait for the provider window to recover, and resume. Never report the listing count as the final keyword-expanded count until the keyword stage has actually merged and de-duplicated its records.

## Run commands

```powershell
radar doctor
radar run --config configs/diesel_90d.yaml --start-date 2025-09-01 --end-date 2026-08-31 --depth standard --analysis-engine deepseek --communities Cummins,Duramax,powerstroke,FordDiesels
radar status --run-id <run_id>
radar resume --run-id <run_id>
radar export --run-id <run_id> --formats json,xlsx,html
```
