# Task 4 Report

## Resume checkpoint

- Resumed from `HEAD 94dcc86` and preserved all existing in-progress files.
- Initial RED state was confirmed before implementation:
  - `node --test tests/keyword-discovery.test.mjs` failed because `headlight protective film` lost `bob` provenance.
  - `node --test tests/radar-pipeline.test.mjs` failed because round two never executed and the resume fixture stayed `complete` instead of `partial`.
  - `tests/schema-contract.test.mjs` was extended first, then run RED to prove the keyword-candidate schema/default contract was not yet enforced.

## Root causes

- `src/keyword-discovery.mjs` mixed alias matching with canonical output normalization. The alias `protective film` was expanded to `headlight protective film` before matching against source text, so valid evidence-linked provenance was silently dropped.
- The in-progress Task 4 pipeline fixture expected `bob` to be deep-dived even though the existing Task 3 author-selection contract admits only authors with at least one eligible high-quality record. The fixture had to be aligned with that contract instead of weakening author selection.
- Task 4 schema/default coverage was incomplete: the candidate artifact schema was too loose for audit purposes, and the pilot config did not track explicit round-two defaults.

## Changes made

- `src/keyword-discovery.mjs`
  - Split lexical match normalization from canonical candidate normalization.
  - Preserved alias matches like `protective film` while still outputting the canonical exploratory term `headlight protective film`.
  - Reused lexical normalization for tokenization and contains-term matching so provenance, user counts, and community counts stay consistent.
- `schemas/keyword-candidates.schema.json`
  - Tightened the artifact contract for candidate provenance, score breakdowns, penalties, source-quality tracking, and lifecycle status.
- `configs/automotive_lighting_us_pilot.json`
  - Added explicit round-two defaults: `round_two_terms=20`, `round_two_posts_per_term=10`, `round_two_minimum_score=65`, `round_two_minimum_users=2`, `round_two_minimum_communities=2`.
- `tests/schema-contract.test.mjs`
  - Added keyword-candidate schema/default contract coverage.
- `tests/radar-pipeline.test.mjs`
  - Updated Task 4 fixtures so author deep dives respect the existing Task 3 eligibility rules.
  - Kept the round-two assertions focused on one bounded second round, immutable formal keywords, and retry-only-unresolved exploratory queries.

## Verification

- Focused GREEN:
  - `node --test tests/keyword-discovery.test.mjs tests/radar-pipeline.test.mjs tests/schema-contract.test.mjs`
  - Result: `27` passing, `0` failing.
- Full GREEN:
  - `node --test`
  - Result: `80` passing, `0` failing.
- Diff check:
  - `git diff --check`
  - Result: no whitespace or patch-format errors; Git only reported LF/CRLF conversion warnings on existing working-copy files.

## Commit

- Pending local commit.
