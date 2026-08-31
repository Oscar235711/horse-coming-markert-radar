---
name: opportunity-radar
description: Run or continue the Reddit automotive-lighting opportunity radar with configurable evidence, keyword, and persona thresholds.
---

# Opportunity Radar

Use this skill when a researcher asks to run, resume, or analyze the Reddit market radar in this repository.

Before starting a new run, ask one compact configuration question covering:

- evidence strictness: strict (qualified evidence only) or exploratory (show qualified evidence plus clearly labelled candidates);
- persona thresholds: qualified evidence, qualified users, deep-dive authors, cluster members, representative users, and representative activities;
- keyword display thresholds: minimum unique users, threads, communities, and thread share;
- collection limits: post count, comments per post, author count, author activity window, and whether a second keyword round is enabled.

Show the resolved values and write them into the run's config snapshot before collection. If thresholds conflict with collection limits (for example, requiring more deep-dive authors than can be collected), warn and ask for a correction.

Evidence boundaries:

- Keep US, unknown, and non-US geography separate; unknown is not US.
- Keep direct experience, practitioner, demand, and noise roles separate.
- Do not turn a pain point into a product opportunity without a sellable concept and cited evidence.
- Do not infer product prices from unrelated dollar amounts. Product prices require an identified product and a source URL/date; missing official or Amazon data stays unknown.
- Do not invent manufacturing, shipping, return, market-size, supplier, or regulatory facts.

Report expectations:

- The Audience Map opens in the all-relations view and supports focused drill-down.
- The keyword cloud shows only terms meeting the configured display thresholds; the full candidate list remains available for audit.
- Pain cards show evidence-backed opportunity and solution links, including explicit "待验证" when a gate is not met.
- Evidence is grouped by community with three representative records visible on expansion. Use the report's CSV export for the complete normalized crawl fields.

Use `scripts/render-existing-report.mjs <run-directory>` only to regenerate a saved run without recollecting or calling an LLM. Never print credentials or upload `.local/` artifacts.
