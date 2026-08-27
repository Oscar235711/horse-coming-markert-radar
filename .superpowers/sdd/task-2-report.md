# Task 2 Report

## Scope

- Implemented the V1.2 product opportunity engine in `src/opportunity-engine.mjs`.
- Replaced legacy V1.1-style opportunity construction in `src/radar-analysis.mjs`.
- Kept Audience Map scoped to formal `opportunities` only; `candidate_signals` remain outside the formal product graph.

## RED Evidence

### Added/strengthened failing tests first

- `tests/opportunity-engine.test.mjs`
  - pain-only evidence never becomes a product opportunity
  - only `validated_entry`, `emerging_product`, and `adjacent_bundle` are allowed
  - `headlight assembly sealing optimization` is blocked as a non-sellable pain theme
  - contextual-demand-only evidence cannot qualify as a formal product opportunity
- `tests/radar-analysis.test.mjs`
  - rule analysis must output `candidate_signals` and `pain_points`
  - thin product mentions stay out of formal opportunities
  - condensation / assembly language does not become a direct opportunity

### Observed failing run before GREEN

Command:

```powershell
node --test tests/opportunity-engine.test.mjs tests/radar-analysis.test.mjs
```

Observed failures included:

- missing `validated_entry` classification
- pain-theme label not failing `concrete_product`
- old `analyzeDetails` still returning formal opportunities
- missing `candidate_signals` integration for product-context edge cases

## GREEN Evidence

### Implemented behavior

- Pain extraction and opportunity extraction are now separated.
- Formal opportunities are limited to `validated_entry`, `emerging_product`, and `adjacent_bundle`.
- Formal opportunity scoring uses only qualified Reddit evidence.
- Thin or weak evidence can still surface as `candidate_signals`, but not as formal opportunities.
- Non-sellable pain-theme labels such as `headlight assembly sealing optimization` fail the auditable `concrete_product` gate.
- `emerging_product` now requires solution/workaround evidence rather than contextual demand alone.
- `analyzeDetails` now runs the evidence gate, then feeds the opportunity engine, and returns:
  - `opportunities`
  - `candidate_signals`
  - `pain_points`
  - `competitors`

### Verification

Focused verification:

```powershell
node --test tests/opportunity-engine.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs
```

Result: 15 tests, 15 passed, 0 failed.

Full verification:

```powershell
node --test
```

Result: 59 tests, 59 passed, 0 failed.

## Review Fixes

### Additional RED Evidence from independent review

Command:

```powershell
node --test tests/opportunity-engine.test.mjs tests/radar-runner.test.mjs tests/schema-contract.test.mjs
```

Observed failures included:

- `contextual_demand` still counted toward qualified support for adjacent bundle scoring
- `runner` still injected `candidate_signals` into Audience Map as if they were formal opportunities
- `schemas/opportunities.schema.json` was too loose to enforce the auditable scoring and commercial contract

### Additional GREEN Evidence

- `src/opportunity-engine.mjs`
  - qualified support now requires `eligible: true`
  - `contextual_demand` no longer contributes to `qualified_evidence_ids`, qualified users, qualified communities, or formal opportunity scoring
- `src/radar-runner.mjs`
  - Audience Map now reads only formal `opportunities`
  - candidate backlog remains in `analysis.candidate_signals`, not in the graph
- `schemas/opportunities.schema.json`
  - score components now require the fixed seven audit dimensions
  - score penalties now require the fixed penalty fields plus `total`
  - threshold checks, commercial fields, competitor signals, count fields, and entry-gap fields are strongly constrained
- `tests/radar-analysis.test.mjs`
  - adjusted the regression assertion to reflect the stricter qualified-support gate

### Additional Verification

Focused verification after review fixes:

```powershell
node --test tests/radar-analysis.test.mjs tests/opportunity-engine.test.mjs tests/radar-runner.test.mjs tests/schema-contract.test.mjs
```

Result: 17 tests, 17 passed, 0 failed.

Final full verification after review fixes:

```powershell
node --test
git diff --check
```

Result:

- `node --test`: 60 tests, 60 passed, 0 failed
- `git diff --check`: no diff errors
