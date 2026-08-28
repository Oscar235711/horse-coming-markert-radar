# Task 2 implementation report — diesel keyword discovery and topic analysis

## Delivered

- Added deterministic exploratory keyword discovery from qualified diesel evidence, dictionary terms, 2–4 gram phrases, and Task 1 `PostAnalysis.keyword_candidates`.
- Formal input terms are read-only; exploratory candidates include evidence IDs, source post IDs, authors, communities, extraction methods, parent formal terms, category, score breakdown, penalties, score, and review status.
- Added bounded second-round selection: score >= 65, at least two authors and two communities, maximum 20 terms.
- Added `OpenCliCollector.collect_round_two`: writes raw keyword-search payloads, deduplicates against supplied round-one candidates, checkpoints successful and failed queries, and retries only failed queries when the same term signature resumes.
- Kept collection failure handling non-blocking per query and made no external calls in tests or implementation.
- Topic aggregation continues to use the established stable topic registry, formal/weak thresholds, 30-vs-60 day trends, and 0–100 normalized heat. Tag, platform, vehicle, scenario, and validation-question projections now retain accepted evidence payloads in `field_evidence`.

## TDD evidence

1. `tests/test_keyword_discovery.py` was added first and failed because `discover_diesel_keywords`, `KeywordCandidate`, and `select_round_two_terms` did not yet exist.
2. `tests/test_collection_and_deepseek.py -k round_two` was added first and failed because `OpenCliCollector.collect_round_two` did not yet exist.
3. `tests/test_topic_export.py -k tags_and_validation` was added first and failed because topic output lacked `field_evidence`.
4. Minimal implementations were then added and each focused test was rerun green.

## Verification

- `pytest tests/test_keyword_discovery.py` — 2 passed
- `pytest tests/test_collection_and_deepseek.py -k round_two` — 1 passed
- `pytest tests/test_topic_export.py -k tags_and_validation` — 1 passed
- `pytest` — 58 passed

## Scope and remaining integration note

`collect_round_two` is an explicit collector operation so legacy `collect()` callers and existing CLI fakes retain their public contract. The calling orchestration layer must pass only human-approved output from `select_round_two_terms` when `require_human_approval` is enabled; this task deliberately does not add automatic approval or a profile deep dive.
