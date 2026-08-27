# Task 3 report — Topic aggregation and JSON/Excel export

## Delivered

- Per-community injected-Pro topic consolidation with a deterministic fixture mode, a three-topic-per-post cap, registry-backed stable IDs, evidence URL enforcement, formal/weak thresholds, 30/60-day trends, and 0–100 weighted heat scores.
- One canonical `analysis.json`, with `community_topics.json` and a seven-sheet Excel workbook derived directly from it without a second Pro call.
- Reusable `scripts/build_topic_workbook.mjs` built exclusively with `@oai/artifact-tool`; the workbook contains exactly: 运行概览、社区热点排行、话题分析卡、帖子及评论证据、弱信号观察区、排除与失败记录、候选社区与词表建议.

## RED / GREEN evidence

- RED: `python -m pytest tests/test_topic_export.py` — 3 expected failures: `TopicAggregator` did not yet exist.
- GREEN: focused run passed after the first minimal implementation: `3 passed`.
- RED: community-isolation acceptance test failed with `assert 2 == 1`, proving a foreign-community post incorrectly inflated the topic.
- GREEN: filtering input signals to the requested community gave `5 passed`.
- RED: bilingual-evidence acceptance test failed because an empty Chinese translation still entered a formal topic.
- GREEN: evidence validation now rejects it; targeted test passed.

## Verification commands

- `python -m pytest` — **34 passed in 21.65s**.
- `python -m compileall -q src` — exit 0.
- `git diff --check` — no whitespace errors (Git emitted only its standard CRLF warning for the pre-existing tracked `__init__.py`).
- Imported the generated `.xlsx`, inspected all seven named sheets, and rendered every sheet for visual review.

## Files

- `src/opportunity_radar/topics.py`
- `src/opportunity_radar/__init__.py`
- `scripts/build_topic_workbook.mjs`
- `tests/test_topic_export.py`
- `.superpowers/sdd/task-3-report.md`

## Commit

`9a107edd33acf1305c3d89530d2d16d9cf54e357` — `feat: add topic aggregation and evidence exports`.

## Concern

`@oai/artifact-tool` preserves Excel `HYPERLINK` formulas in the evidence-link column, which opens as clickable links in Excel. Its own PNG renderer does not calculate that formula and displays an “is not implemented” placeholder during visual inspection; the adjacent original URL remains visible and the automated workbook test checks the exported HYPERLINK formula and URL.

## Fix round 1/2 evidence

- RED: distinct commenter regression failed because `ThreadComment` dropped the public author field; artifact re-import verification was absent.
- GREEN: `ThreadComment.author` and `ThreadDocument.comment_authors` now preserve de-duplicated public authors excluding the OP; focused and full tests pass.
- GREEN: workbook builder re-imports the exported XLSX with `FileBlob`/`SpreadsheetFile.importXlsx` and inspects all seven sheet names before returning.
