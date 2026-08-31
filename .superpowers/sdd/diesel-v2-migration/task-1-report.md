# Task 1 — Diesel evidence and analysis contract report

## Status

Completed on `feature/community-radar`. This task adds the diesel-specific evidence-quality and post-analysis contract slice without changing collection, keyword expansion, Excel/HTML reporting, or the Node reference repository.

## Implementation

- Added `opportunity_radar.evidence` with deterministic diesel evidence roles: `direct_experience`, `qualified_practitioner`, `contextual_demand`, `market_observation`, `weak`, and `noise`.
- Added auditable component scores, penalties, quality bands, reason codes, hard exclusions, and a gate preserving both qualified and excluded records.
- Added hard boundaries for bot/moderation, promotional/coupon material, URL-only and low-information content, duplicates, and non-diesel/non-pickup terms such as motorcycle and gasoline passenger-car examples.
- Extended `PostAnalysis` compatibly: existing `topics` and `claims` are unchanged; new cited fields retain `fact`, `inference`, or `unknown` status for diesel platform, vehicle/year, scenario, goal, pains, needs, solutions, gaps, hypotheses, products, brands, competitors, purchase intent, sentiment, keywords, and topic candidates.
- Unsupported evidence IDs are downgraded to `unknown` and lose their citations. The pre-existing grounded-claim topic fallback remains, and now uses `dataclasses.replace` so it retains the new structured fields.
- DeepSeek remains Higress-compatible through `DEEPSEEK_BASE_URL`, `DEEPSEEK_API_KEY`, and `DEEPSEEK_FLASH_MODEL`; configuration records only environment-variable names, never values.
- Expanded `configs/diesel_90d.yaml` with diesel dictionaries, hard relevance exclusions, candidate-keyword search settings, report output settings, and `user_deep_dive.enabled: false`.
- Added `load_diesel_domain_config` and typed configuration values for the new configuration section.

## TDD evidence

1. Added `tests/test_diesel_evidence_contract.py` before production implementation.
2. Ran it red: four expected `AttributeError` failures for the missing evidence API, post-analysis fields, and domain config loader.
3. Implemented the minimum API and ran the focused suite green.
4. Added a regression test for the already-dirty DeepSeek topic-seed fallback; it failed as expected because fallback reconstruction erased V2 fields.
5. Changed only the fallback construction to `replace(...)`; focused suite became green.

## Verification

- `python -m pytest -q tests/test_diesel_evidence_contract.py` — 6 passed.
- `python -m pytest` — all collected tests passed (57 tests).
- `python -m compileall -q src` — passed.
- `git diff --check` — passed; only Windows line-ending warnings were emitted.

## Scope boundaries

- No external Reddit or DeepSeek calls were made.
- No HTML report, keyword-discovery pipeline, user-profile deep dive, or Node reference repository files were changed.
- Existing public compact analysis fixtures continue to construct `PostAnalysis(topics=..., claims=...)` unchanged.
