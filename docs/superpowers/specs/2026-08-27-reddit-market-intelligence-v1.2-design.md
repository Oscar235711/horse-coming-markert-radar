# Reddit Market Intelligence V1.2 Design

## 1. Version and delivery boundary

V1.2 extends the existing `codex/automotive-lighting-reddit-radar` branch. The branch advances by normal commits; history is not rewritten. Tag `v1.1.0` remains an immutable pointer to the current V1.1 implementation. After V1.2 implementation and verification, tag `v1.2.0` will point to the verified V1.2 commit. `main` and tag `v1.0.0` remain unchanged unless the user separately authorizes a pull request or merge.

Hermes will run V1.2 from the same branch after it is pushed. Hermes may collect public Reddit data, run DSV4Pro analysis, resume checkpoints, and write local run artifacts. Hermes must not push, merge, change tags, modify the formal keyword pool, or expose secrets.

## 2. Goals

V1.2 must:

1. Apply a reusable evidence-quality gate before any Reddit evidence is scored or shown.
2. Keep user pain points separate from product opportunities.
3. Identify three opportunity types across markets: validated categories with entry room, emerging products, and adjacent/bundle products.
4. Deep-dive high-quality public authors only after their source post passes the evidence gate.
5. Derive exploratory keywords from high-quality evidence and relevant author activity, then use approved exploratory terms in a bounded second search round.
6. Generate personas only when the agreed evidence and user thresholds are met.
7. Add an interactive market keyword cloud backed by a standalone JSON artifact.
8. Produce an unambiguous Hermes handoff for an overnight DSV4Pro run.
9. Preserve source evidence, failures, exclusions, inferences, unknowns, and configuration snapshots for audit.

V1.2 is market-generic. Automotive lighting remains the first test configuration, not a hard-coded product boundary.

## 3. Non-goals

- No seasonality prediction.
- No private Reddit data or login credential export.
- No inference of age, income, race, health, precise location, or other sensitive attributes.
- No automatic promotion of discovered terms into the formal keyword pool.
- No automatic marketplace ordering, supplier contact, purchasing, repository push, merge, or release by Hermes.
- No claim of market size from Reddit frequency alone.

## 4. Architecture

The processing sequence is fixed:

```text
Round-one Reddit discovery
  -> canonical normalization and deduplication
  -> universal evidence-quality gate
  -> qualified evidence pool
       -> pain and context extraction
       -> product/competitor/adjacency extraction
       -> high-quality author selection
            -> relevant public author activity deep dive
            -> exploratory keyword extraction and scoring
  -> bounded round-two discovery with exploratory terms
  -> evidence-quality gate and deduplication again
  -> product opportunity engine
  -> persona eligibility check and clustering
  -> seller report, Audience Map, keyword cloud, evidence library
```

The implementation will separate responsibilities into focused modules:

- `src/evidence-quality.mjs`: universal evidence classification, scoring, exclusion reasons, and market override application.
- `src/opportunity-engine.mjs`: pain records, product concepts, opportunity types, competitor signals, scoring, and evidence minimums.
- `src/author-deep-dive.mjs`: author eligibility, public activity collection contract, automotive/market relevance filtering, and privacy retention rules.
- `src/keyword-discovery.mjs`: candidate extraction, provenance graph, scoring, promotion state, and round-two query selection.
- `src/persona-engine.mjs`: sample eligibility, behavior-feature construction, clustering, representative users, and insufficient-sample results.
- `src/keyword-cloud.mjs`: keyword aggregation, category assignment, display weight, evidence backlinks, and cloud JSON.
- `src/radar-report.mjs`: render-only consumer of final JSON; it does not call DSV4Pro or mutate analysis.
- `src/radar-pipeline.mjs`: stage orchestration, checkpoints, retries, and failure continuation.

The existing adapters remain responsible for transport. Every transport must produce the same canonical post, comment, author-activity, and failure records.

## 5. Universal evidence-quality gate

### 5.1 Evidence roles

Every post and comment receives exactly one `evidence_role`:

- `direct_experience`: first-person ownership, purchase, installation, repair, usage, return, or product outcome.
- `qualified_practitioner`: concrete mechanic, installer, seller, or experienced-user diagnosis tied to a product, vehicle, symptom, or outcome.
- `contextual_demand`: a sufficiently detailed request containing a real vehicle/use case, need, budget, fitment, or attempted solution, but no outcome yet.
- `market_observation`: verifiable competitor/product availability or repeated community observation without a first-person outcome.
- `weak`: relevant but too vague to support opportunity scoring.
- `noise`: irrelevant, spam-like, duplicated, automated, or non-substantive.

Only the first four roles may enter the evidence library. `weak` and `noise` records remain in exclusion statistics with reason codes but are not shown as supporting evidence and contribute zero opportunity score.

### 5.2 Hard exclusions

The following are excluded before quality scoring:

- deleted or removed body;
- AutoModerator, known bot, moderation boilerplate, or subreddit rule text;
- URL-only, image-only with no usable description, emoji-only, or reaction-only text;
- generic agreement or banter such as “same”, “this”, “lol”, “looks good”, or “nice” without a product result;
- affiliate, coupon, referral, seller solicitation, repeated promotional copy, or mass-posted link content;
- duplicate or near-duplicate text from the same run;
- news/headline reposts, memes, motorsport discussion, household lighting, or other off-market content without user product experience;
- unsupported hearsay presented without a concrete product, situation, or source;
- content outside the configured geography when the run requires a specific market.

Market overrides cannot disable these exclusions.

### 5.3 Quality score

Eligible records receive a 0–100 score using auditable components:

- first-person or qualified-practitioner evidence: 0–20;
- concrete product or solution identification: 0–15;
- vehicle, fitment, market, use-case, or installation context: 0–15;
- observable outcome, failure, comparison, return, or repeat purchase: 0–20;
- price, budget, purchase channel, or purchase intent: 0–10;
- diagnostic detail or attempted solution: 0–10;
- cross-record corroboration: 0–5;
- engagement metadata: 0–5 and never sufficient by itself.

Penalties apply for advertising language, low information density, quotation without personal context, uncertain geography, or suspected duplication. The output stores every component and reason code.

Quality bands are:

- `high`: 70–100;
- `medium`: 50–69;
- `weak`: 30–49;
- `noise`: 0–29 or a hard exclusion.

Only `high` and `medium` evidence may support product opportunities. High-quality evidence has weight `1.0`; medium-quality evidence has weight `0.5`. Contextual demand cannot substantiate a product-performance claim by itself.

### 5.4 Optional market rules

Every market config may contain an optional `market_rules` object. When absent, universal rules apply unchanged. A market override may add:

- geography signals;
- market-specific product, vehicle, fitment, competitor, retailer, slang, and stopword dictionaries;
- relevance expressions;
- bounded component-weight adjustments;
- minimum evidence thresholds that are stricter than the universal defaults;
- excluded communities or commercial spam patterns.

It may not remove hard exclusions, lower privacy protection, accept unsupported claims, or automatically promote formal keywords.

## 6. Product opportunity model

### 6.1 Pain is not an opportunity

Pain records such as condensation, glare, flicker, poor fitment, difficult installation, or premature failure are stored under `pain_points`. A pain record becomes part of an opportunity only when the analysis identifies a concrete product concept, product improvement, accessory, service, bundle, or purchase alternative that addresses it.

The report displays pain prevalence and evidence separately from product opportunities. “Headlight assembly and sealing optimization” is therefore a pain/improvement theme unless the system can name a sellable concept such as a replacement assembly with a specific sealing solution, a vent/membrane kit, a protective film, or another evidence-supported product.

### 6.2 Opportunity types

Each opportunity has one type:

- `validated_entry`: an existing popular category or competitor-opened category with continuing demand and a documented gap in quality, fitment, installation, price, availability, or support.
- `emerging_product`: a concrete sellable concept supported by repeated demand or workarounds, but with limited current product availability or validation.
- `adjacent_bundle`: a complementary product, low-cost add-on, gift, brand merchandise item, or basket-building product repeatedly associated with the core use case.

Examples for automotive lighting may include bulbs, housings, projectors, harnesses, adapters, protective film, cleaning/installation accessories, mats, vehicle interior small parts, storage accessories, or inexpensive branded gifts. The same logic applies to other market configurations.

### 6.3 Minimum evidence

Universal defaults are configurable upward by market:

- `validated_entry`: at least 8 unique qualified users, 2 communities, 3 direct-experience records, explicit evidence that products or competitors already exist, and at least one unresolved entry gap.
- `emerging_product`: at least 5 unique qualified users, 2 independent discussion contexts, a concrete product concept, and repeated demand, workaround, or attempted solution evidence.
- `adjacent_bundle`: at least 5 unique qualified users, association with at least 2 core product/use contexts, and a clear reason for add-on, gifting, protection, installation, storage, personalization, or convenience.

If these thresholds are not met, the concept remains a `candidate_signal` and appears only in the research backlog, not as a formal opportunity card.

### 6.4 Opportunity score

The 0–100 opportunity score contains:

- qualified demand: 0–25;
- existing market or competitor validation: 0–20;
- unresolved entry gap: 0–20;
- purchase and price signals: 0–10;
- cross-community and cross-user diversity: 0–10;
- adjacency or bundle logic: 0–10;
- evidence quality: 0–5.

Penalties apply for one-user concentration, one-community concentration, ambiguous geography, promotional contamination, missing product concept, or evidence dominated by contextual questions. Reddit score and comment count are descriptive metadata, not the primary opportunity score.

Every opportunity separates facts, inferences, and unknowns. Pricing, supply chain, MOQ, manufacturing complexity, shipping risk, legal requirements, and return risk remain unknown unless supported by a cited source or explicitly supplied dataset.

## 7. Author deep dive and persona eligibility

### 7.1 Author selection

Authors become deep-dive candidates only when they created a `high` quality post or multiple `high`/`medium` records. Deleted authors, bots, moderators acting in an official capacity, obvious commercial accounts, and authors whose relevance depends only on a weak comment are excluded.

The selector prioritizes evidence quality, product specificity, purchase/ownership detail, cross-topic value, and whether the author may reveal adjacent products or vocabulary. Engagement is a minor tie-breaker.

### 7.2 Public activity collection

For each selected author, adapters may read up to 50 public Reddit activities from the most recent 180 days. Only activity relevant to the configured market, product ecosystem, purchase behavior, usage scenario, installation, repair, accessories, adjacent categories, or community vocabulary is retained. Irrelevant personal history is discarded immediately and never written to run artifacts.

The canonical author-activity record includes public username, activity type, subreddit, timestamp, permalink, original text, relevance reasons, quality result, product concepts, pain points, and discovered terms. No sensitive demographic inference is permitted.

### 7.3 Persona gate

Personas are generated only when all agreed minimums are satisfied:

- at least 200 qualified evidence records;
- at least 60 unique qualified users;
- at least 30 high-quality source-post authors available for deep dive;
- at least 12 users in every published cluster;
- exactly 3 representative users per published cluster;
- every representative user has at least 3 relevant retained public activities.

If any global threshold fails, the report emits `persona_status: insufficient_sample` and explains each missing count. If a cluster fails its local threshold, that cluster is suppressed.

Personas describe observable behavior only: product interests, vehicle/platform context, DIY versus professional-install preference, purchase criteria, recurring pain points, explored solutions, related communities, and vocabulary. Each representative user links to the retained public evidence that makes the user representative.

## 8. Exploratory keyword algorithm

### 8.1 Two keyword pools

- The formal pool contains user-approved anchor and controlled-expansion terms. It is versioned in the market config and cannot be changed by a run.
- The exploratory pool contains derived product phrases, solution phrases, pain phrases, fitment terms, competitor/brand terms, retailer terms, community slang, use cases, and adjacent-product phrases.

### 8.2 Candidate extraction

Candidates are extracted only from qualified evidence and retained author activity. Extraction combines deterministic phrase patterns, normalized n-grams, product/brand dictionaries, co-occurrence windows, and optional DSV4Pro structured extraction. Every candidate preserves provenance: source evidence IDs, authors, communities, parent formal terms, and the extraction method.

Candidates are normalized for case, singular/plural variants, punctuation, common Reddit formatting, and obvious spelling variants. Fitment terms remain tags unless they form part of a meaningful product query. Brand terms never enter the formal pool automatically.

### 8.3 Candidate score

The 0–100 discovery score contains:

- unique-user repetition: 0–25;
- cross-community coverage: 0–15;
- product or solution specificity: 0–15;
- purchase-intent association: 0–15;
- pain or workaround association: 0–10;
- co-occurrence with a formal term or validated product concept: 0–10;
- novelty relative to the formal pool: 0–10.

Penalties apply for one-user dominance, one-thread dominance, brand-only mentions, promotional language, generic language, and excluded evidence. The report shows the complete score breakdown.

### 8.4 Bounded second round

At most 20 exploratory terms with score at least 65 may enter round-two search. A market override may raise the threshold or lower the term cap. The second round uses the same evidence gate and canonical deduplication. There is no third recursive round in V1.2, preventing uncontrolled query expansion.

Round-two use does not promote a term. Each candidate ends in one of: `formal`, `exploratory_used`, `candidate_review`, `rejected`, or `promoted_by_human`. Only a future explicit human action may create `promoted_by_human`.

## 9. Keyword cloud

V1.2 adds a `关键词词云` tab alongside the seller report, Audience Map, evidence library, and persona view. It is powered only by `keyword_cloud.json` and works offline under `file://`.

The cloud includes qualified formal and exploratory terms. Font size represents normalized display weight derived from qualified evidence weight, unique users, cross-community coverage, and purchase/pain association. Color represents term category: product, solution, pain, fitment, competitor/brand, use case, or adjacent product.

Clicking a term shows its score components, status, source users count, communities, related product concepts, parent seed terms, and representative Reddit evidence. Controls include category filters, formal/exploratory status filters, search, minimum score, and reset. The cloud never treats raw frequency as market size.

## 10. Report and data artifacts

Every run produces:

- `config.snapshot.json`;
- `candidates.json`;
- `quality_evidence.jsonl`;
- `excluded_evidence.jsonl` with exclusion reasons;
- `raw/details/*.json`;
- `raw/authors/<username>.json` containing only retained relevant public activity;
- `keyword_candidates.json`;
- `keyword_cloud.json`;
- `opportunities.json`;
- `personas.json` or an insufficient-sample record;
- `analysis.json` as the report source of truth;
- `audience_map.json`;
- `failures.jsonl`;
- `optimization_backlog.jsonl`;
- `manifest.json`;
- one offline `report.html`.

The HTML does not call DSV4Pro or the network. Numeric totals and evidence IDs must match the JSON artifacts. The report separates:

1. seller verdict and product opportunities;
2. pain-point landscape;
3. competitor and existing-product evidence;
4. adjacent/bundle opportunities;
5. Audience Map;
6. keyword cloud;
7. persona clusters and representatives, or the insufficient-sample explanation;
8. qualified evidence library;
9. exclusions, failures, unknowns, scope, formal terms, exploratory terms, and optimization backlog.

## 11. DSV4Pro integration

DSV4Pro is an optional OpenAI-compatible structured-analysis layer. Rules always run first. DSV4Pro may enrich role classification, extract product/competitor/adjacent concepts, normalize phrases, and explain candidate relationships.

DSV4Pro output must validate against a tracked JSON Schema and may reference only evidence IDs supplied in its request. It cannot delete the rule result, invent evidence, change formal keywords, bypass minimum sample thresholds, or convert an unknown commercial field into a fact without a cited input. Invalid JSON, unknown evidence IDs, timeout, rate limit, or schema failure causes a recorded fallback to the rule result.

The handoff uses model identifier `dsv4pro` exactly as provided by the user. Endpoint and key values are environment variables; their values never appear in the handoff, logs, report, or repository.

The V1.2 overnight profile uses these explicit collection ceilings:

- round-one candidate-post target: 300, with a hard maximum of 400 before deduplication;
- high-signal post deep dive: 100 posts;
- comment limit: 20 retained comments per post;
- author deep-dive target: 60 eligible authors;
- author activity limit: 50 public activities per author from the most recent 180 days;
- round-two expansion: at most 20 terms and 10 candidate posts per term;
- combined round-one and round-two candidate hard maximum: 500 after canonical deduplication;
- Hermes wall-clock ceiling: 600 minutes, after which it writes checkpoints and a partial summary and exits cleanly.

These are ceilings, not claims that every source will return that volume. Evidence and persona sufficiency are evaluated from qualified retained records, not requested counts.

## 12. Hermes handoff contract

Implementation will create `.agents/HERMES_HANDOFF_V1.2.md`, `.agents/PROGRESS.md`, and `.agents/OUTBOX.md`. The handoff must be executable without interpreting unstated intent and contain:

1. Repository URL, required branch, expected tag/commit, and a command that verifies the checked-out revision.
2. Goal: run the V1.2 automotive-lighting US research overnight, not develop features or change repository history.
3. Model: `dsv4pro`; exact environment variable names; a preflight that reports presence without printing values.
4. Reddit transport priority and fallback behavior.
5. Exact PowerShell and Node commands, working-directory rules, run ID convention, and output directory.
6. Stage order: preflight, round-one search, quality gate, author selection, public author deep dive, keyword discovery, round-two search, analysis, personas, graph/cloud/report generation, verification.
7. Checkpoint files and resume command. Successful stages are not repeated; unresolved queries and authors are retried within limits.
8. Rate-limit policy: each Reddit query, post, or author receives at most 3 total attempts with 15-second and 45-second waits; each DSV4Pro request receives at most 2 total attempts with a 30-second wait. Retry-After is honored when present but capped at 120 seconds. A single item exhausting retries becomes an unresolved failure and does not stop unrelated items.
9. Stop conditions: missing repository, wrong branch/commit, missing required runtime, schema corruption, privacy-rule failure, or repeated fatal failure after the configured retry ceiling.
10. Non-stop conditions: one unavailable post, deleted author, private/suspended profile, individual 403/429, DSV4Pro timeout, insufficient persona sample, or an exploratory term rejected by quality rules.
11. Safety: public read-only Reddit access; no messages, votes, follows, account changes, secret output, formal-keyword mutation, git push, tag, merge, or PR.
12. Acceptance checks and expected output files, including JSON/HTML consistency and zero unsupported evidence links.
13. Required final summary format in `.agents/OUTBOX.md`: run status, counts by stage, evidence-quality distribution, excluded reasons, author-deep-dive counts, keyword candidates, second-round additions, opportunities by type, persona eligibility, artifact paths, unresolved failures, and recommended human decisions.
14. Progress logging format and timestamp/time-zone requirements in `.agents/PROGRESS.md`.
15. A clean shutdown instruction that preserves checkpoints and never deletes partial artifacts.

The handoff must distinguish “pipeline complete” from “business sample sufficient.” A run may finish technically while still reporting insufficient evidence, users, communities, or persona coverage.

## 13. Checkpoints, retries, and failure semantics

Each stage has its own immutable input snapshot and resumable output. A stage is reused only when its input hash and schema version match. Configuration changes require a new stage result; they cannot silently reuse stale candidates.

Failures contain stage, item/query/author identifier, attempt number, transport/model, timestamp, error category, retryability, and message. Resuming retries unresolved failures without erasing historical attempts. The manifest reports both current unresolved failures and cumulative attempts.

The manifest technical status is:

- `complete`: all required stages completed and no unresolved retryable failures remain;
- `partial`: report generated but unresolved collection/model failures remain;
- `failed`: no valid report can be generated because a required contract, privacy, or runtime condition failed.

Business sufficiency is reported separately as `sample_status: sufficient|insufficient`, with missing counts. Persona output separately uses `persona_status: complete|insufficient_sample`. A technically complete run may therefore have `status: complete`, `sample_status: insufficient`, and `persona_status: insufficient_sample` without contradiction.

## 14. Testing and acceptance

### 14.1 Evidence quality

- A labeled fixture set covers direct experience, practitioner advice, contextual demand, hearsay, joke, bot, affiliate, duplicate, URL-only, and off-market content.
- Hard exclusions always remain excluded under market overrides.
- Engagement alone cannot promote noise.
- Every included and excluded record has auditable reason codes.

### 14.2 Opportunity model

- Pain-only fixtures never become product opportunities.
- All formal opportunity cards contain a concrete sellable concept and meet their type-specific evidence minimum.
- Validated, emerging, and adjacent fixtures classify independently.
- Competitor and product-existence claims require evidence.
- Facts, inferences, and unknowns remain separated.

### 14.3 Author and persona logic

- Only authors of qualified evidence are deep-dived.
- Irrelevant public history is discarded before persistence.
- The 200-evidence, 60-user, and 30-author gates are enforced.
- Every published cluster has at least 12 users and exactly 3 qualifying representatives.
- Insufficient samples generate an explanation instead of personas.

### 14.4 Keyword discovery and cloud

- Candidate normalization, provenance, one-user penalties, cross-community scoring, and the 20-term/65-score round-two bounds are deterministic.
- No discovered term mutates the formal pool.
- `keyword_cloud.json` totals, term weights, filters, and evidence links match the HTML.
- The cloud and all report tabs work offline with no external scripts.

### 14.5 Pipeline and Hermes

- Stage input hashes prevent stale checkpoint reuse.
- A single query, post, author, or DSV4Pro failure is recorded and does not stop unrelated work.
- Resume preserves failure history and retries only unresolved items.
- No Cookie, token, `.env`, personal absolute path, unrelated author history, or sensitive inference is tracked.
- The Hermes handoff commands pass in a clean clone with documented environment variables.
- The final full run reports technical status separately from sample sufficiency.

## 15. V1.2 completion criteria

V1.2 is ready to push only when:

1. All new and existing automated tests pass.
2. A fixed fixture run proves every quality, opportunity, keyword, author, persona, and report contract.
3. A real Reddit pilot completes or produces an auditable partial result without unsupported opportunity claims.
4. The report opens offline and its JSON counts match.
5. The Hermes handoff passes a command-by-command dry run and ambiguity self-review.
6. `git diff --check` and secret/path scans pass.
7. The branch advances normally, `v1.1.0` remains unchanged, and `v1.2.0` is created only after verification.
