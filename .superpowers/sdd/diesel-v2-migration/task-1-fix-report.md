# Task 1 reviewer follow-up — CLI evidence gate

## Completed fixes

- Wired `load_diesel_domain_config` and `apply_diesel_evidence_gate` into `RadarCliApp._continue_run`.
- The gate now evaluates every deep-read post and comment. Only eligible posts are sent to Flash and topic aggregation; comment decisions are retained for audit without discarding useful thread context.
- Each run writes `artifacts/evidence_gate.json`, exposed in state as `evidence_gate_json`. It records post/comment IDs, role, fact/inference/unknown status, deterministic score, weight, eligibility, hard-exclusion state, and reason codes.
- State now records `eligible_post_count`, `excluded_post_count`, and `comment_evidence_count`.
- Relevance uses the loaded diesel configuration dictionaries and exclusions. A record must come from an approved diesel community or name a configured diesel platform/vehicle term. Bare `downpipe` or `tuner` in generic automotive communities is rejected with `missing_diesel_context`.
- Added `downpipe` and `tuner` as configured product aliases, but their presence alone is never sufficient for generic-community relevance.
- `contextual_demand` is now eligible product-opportunity evidence with `opportunity_weight = 0.65`; direct experience, qualified practitioner, and market observation retain weight `1.0`.
- Changed direct-experience classification so intent such as “should I buy” is not misclassified as completed ownership experience.
- `DeepSeekClient.extract_post` accepts an explicit optional model. `RadarCliApp` passes `DEEPSEEK_FLASH_MODEL` to clients that accept a `model` keyword while remaining compatible with existing injected compact fixture clients.
- Flash analysis checkpoints now serialize and reload all V2 scalar and list fields, not just legacy `topics` and `claims`.

## Tests and TDD

1. Added failing tests for config-driven bare-product relevance and the real CLI gate/model path.
2. Observed expected failures: unsupported relevance parameters and missing `evidence_gate_json` artifact.
3. Added a malformed scalar/list Flash contract test; current parser passed because it already correctly rejects non-object scalars and non-array lists.
4. Implemented the minimum gate, persistence, relevance, and model-routing changes.
5. The pre-existing CLI resume test then failed because substantive approved-community market observation was incorrectly dropped. Adjusted that deterministic evidence role so a concrete approved-community failure/aftermarket observation remains eligible, then reran regression coverage.

## Verification

- Focused follow-up suites: 10 passed (`test_cli_workflow` resume, diesel integration, diesel evidence contract).
- Full suite: 60 passed.
- `python -m compileall -q src`: passed.
- `git diff --check`: passed; only Windows line-ending warnings were emitted.

## Scope boundary

No external Reddit or DeepSeek calls were made. No keyword-discovery or HTML-report behavior was added.
