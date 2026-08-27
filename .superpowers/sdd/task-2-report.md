# Task 2 Report

## Scope

- Implemented the V1.2 product opportunity engine in `src/opportunity-engine.mjs`.
- Replaced legacy V1.1-style opportunity construction in `src/radar-analysis.mjs`.
- Added one runner-side compatibility fallback in `src/radar-runner.mjs` so the Audience Map can visualize `candidate_signals` when formal opportunities are empty.

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
