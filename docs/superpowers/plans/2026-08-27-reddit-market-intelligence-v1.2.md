# Reddit Market Intelligence V1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing V1.1 branch to an auditable V1.2 Reddit market-intelligence pipeline with strict evidence filtering, product-level opportunity logic, author deep dives, exploratory keyword discovery, persona gates, a keyword cloud, and an executable Hermes/DSV4Pro handoff.

**Architecture:** Keep transport adapters and the runner, but split market intelligence into focused deterministic modules. Rules produce the authoritative baseline; DSV4Pro may enrich only schema-valid records that cite supplied evidence IDs. Every expensive stage writes an input-hashed checkpoint and the HTML remains a render-only consumer of JSON artifacts.

**Tech Stack:** Node.js 20 ESM, native `node:test`, PowerShell 7 entrypoints, JSON/JSONL artifacts, self-contained HTML/CSS/SVG/JavaScript, OpenAI-compatible DSV4Pro API.

## Global Constraints

- Continue on `codex/automotive-lighting-reddit-radar`; preserve `v1.1.0` and do not modify `main`.
- Use public, read-only Reddit data. Never commit Cookie, token, `.env`, user-specific absolute paths, or irrelevant author history.
- Universal hard exclusions and privacy protections cannot be weakened by a market override.
- Formal keywords are immutable during a run; exploratory terms may drive one bounded second round only.
- DSV4Pro uses model identifier `dsv4pro`; rules remain available after every model failure.
- Personas require 200 qualified evidence records, 60 qualified users, 30 deep-dived source-post authors, 12 users per cluster, and 3 representatives with 3 retained activities each.
- Self-declared age/state context is aggregate-only; income is represented by explicit budget/price behavior; race and health are never persona variables.
- Offline HTML uses tracked JSON as its only data source and has no external script/style dependency.
- Implement every behavior through a failing test first, then the smallest passing implementation.

---

### Task 1: Universal evidence-quality gate and schemas

**Files:**
- Create: `src/evidence-quality.mjs`
- Create: `schemas/evidence-quality.schema.json`
- Create: `configs/rules/universal_evidence_rules.json`
- Modify: `configs/automotive_lighting_us_pilot.json`
- Test: `tests/evidence-quality.test.mjs`
- Modify: `tests/schema-contract.test.mjs`

**Interfaces:**
- Consumes: canonical post/comment records with `id`, `author`, `body_original` or `title`, `subreddit`, `url`, `score`, and market config.
- Produces: `classifyEvidence(record, context) -> { evidence_role, quality_band, quality_score, eligible, hard_exclusion, components, penalties, reason_codes }`.
- Produces: `applyEvidenceGate(records, context) -> { qualified, excluded, distribution }`.

- [ ] **Step 1: Write failing fixtures for direct experience, practitioner detail, contextual demand, weak reaction, bot, affiliate, duplicate, URL-only, and off-market content**

```js
test('hard exclusions cannot be rescued by engagement or market overrides', () => {
  const result = applyEvidenceGate([
    { id: 'bot', author: 'AutoModerator', body_original: 'Community rules', score: 999 },
    { id: 'real', author: 'owner', body_original: 'I installed H11 LEDs on my F-150; they flickered until I added a CANbus adapter.', score: 2 },
  ], { market: { country: 'US' }, marketRules: { minimum_quality_score: 0 } });
  assert.deepEqual(result.qualified.map(item => item.id), ['real']);
  assert.equal(result.excluded[0].quality.hard_exclusion, true);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test tests/evidence-quality.test.mjs`

Expected: FAIL because `src/evidence-quality.mjs` does not exist.

- [ ] **Step 3: Implement deterministic role classification, component scoring, hard exclusions, market-rule merging, and reason codes**

```js
export function classifyEvidence(record, { market = {}, marketRules = {}, seenTexts = new Set() } = {}) { /* return the complete contract */ }
export function applyEvidenceGate(records, context = {}) { /* classify once and partition by eligible */ }
export function loadUniversalEvidenceRules(filePath) { /* parse and validate the tracked rule JSON */ }
```

The implementation must use explicit component caps from the design, normalize text for near-duplicate detection, and assign exactly one role from `direct_experience`, `qualified_practitioner`, `contextual_demand`, `market_observation`, `weak`, or `noise`.

- [ ] **Step 4: Add schema/config contract assertions and run GREEN**

Run: `node --test tests/evidence-quality.test.mjs tests/schema-contract.test.mjs`

Expected: all tests pass; hard exclusions remain excluded under the permissive fixture override.

- [ ] **Step 5: Commit**

```powershell
git add src/evidence-quality.mjs schemas/evidence-quality.schema.json configs/rules/universal_evidence_rules.json configs/automotive_lighting_us_pilot.json tests/evidence-quality.test.mjs tests/schema-contract.test.mjs
git commit -m "feat: add universal Reddit evidence quality gate"
```

### Task 2: Product opportunity engine that separates pain from sellable concepts

**Files:**
- Create: `src/opportunity-engine.mjs`
- Create: `schemas/opportunities.schema.json`
- Test: `tests/opportunity-engine.test.mjs`
- Modify: `src/radar-analysis.mjs`
- Modify: `tests/radar-analysis.test.mjs`

**Interfaces:**
- Consumes: qualified evidence from Task 1 plus market product/competitor dictionaries.
- Produces: `extractPainRecords(evidence, config) -> PainRecord[]`.
- Produces: `buildOpportunityCandidates(evidence, pains, config) -> OpportunityCandidate[]`.
- Produces: `classifyOpportunities(candidates, config) -> { opportunities, candidate_signals, competitors }`.

- [ ] **Step 1: Write failing tests proving pain-only language cannot produce an opportunity and the three opportunity types require concrete product concepts**

```js
test('condensation remains a pain until evidence maps it to a sellable product', () => {
  const result = classifyOpportunities(buildOpportunityCandidates(fixtureEvidence, extractPainRecords(fixtureEvidence, config), config), config);
  assert.equal(result.opportunities.some(item => item.label === 'condensation'), false);
  assert.equal(result.opportunities.find(item => item.id === 'protective-headlight-film').opportunity_type, 'adjacent_bundle');
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/opportunity-engine.test.mjs`

Expected: FAIL because the opportunity engine does not exist.

- [ ] **Step 3: Implement product dictionaries, pain mapping, evidence minimums, competitor validation, type-specific scoring, and candidate-signal fallback**

```js
export function extractPainRecords(evidence, config = {}) { /* pain dimensions only */ }
export function buildOpportunityCandidates(evidence, painRecords, config = {}) { /* concrete sellable concepts */ }
export function classifyOpportunities(candidates, config = {}) { /* validated_entry, emerging_product, adjacent_bundle */ }
```

Every opportunity stores unique-user/community counts, supporting evidence IDs, facts, inferences, unknowns, existing-product/competitor signals, entry gaps, and the seven score components. A candidate below its type threshold goes to `candidate_signals`.

- [ ] **Step 4: Replace V1.1 opportunity construction in `analyzeDetails` and validate schemas**

Run: `node --test tests/opportunity-engine.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs`

Expected: old pain-only opportunity fixture is rejected; validated, emerging, and adjacent fixtures pass.

- [ ] **Step 5: Commit**

```powershell
git add src/opportunity-engine.mjs schemas/opportunities.schema.json src/radar-analysis.mjs tests/opportunity-engine.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs
git commit -m "feat: classify evidence-backed product opportunities"
```

### Task 3: Author eligibility, public activity adapters, and privacy retention

**Files:**
- Create: `src/author-deep-dive.mjs`
- Create: `schemas/author-activity.schema.json`
- Modify: `src/radar-pipeline.mjs`
- Modify: `src/radar-core.mjs`
- Test: `tests/author-deep-dive.test.mjs`
- Modify: `tests/radar-pipeline.test.mjs`

**Interfaces:**
- Adds adapter method: `fetchAuthorActivity(username, { limit, afterUtc, timeoutMs }) -> RawActivity[]`.
- Produces: `selectAuthors(qualifiedEvidence, limits) -> AuthorCandidate[]`.
- Produces: `retainRelevantActivity(items, context) -> { retained, excluded_count }`.
- Produces: `extractSelfDeclaredContext(activity, evidenceId) -> SelfDeclaredContext[]`.

- [ ] **Step 1: Write failing tests for author selection, activity limits, irrelevant-history discard, explicit self-declarations, and private/deleted profile continuation**

```js
test('author history retains relevant public context but discards unrelated personal history', () => {
  const kept = retainRelevantActivity(authorItems, { productTerms: ['headlight', 'floor mat'], market: 'US' });
  assert.deepEqual(kept.retained.map(item => item.id), ['lighting-post', 'budget-comment']);
  assert.equal(kept.excluded_count, 2);
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/author-deep-dive.test.mjs`

Expected: FAIL because author deep-dive exports do not exist.

- [ ] **Step 3: Implement author selection and canonical activity/privacy functions**

```js
export function selectAuthors(qualifiedEvidence, { limit = 60 } = {}) { /* quality-first unique authors */ }
export function retainRelevantActivity(items, context = {}) { /* discard unrelated items before persistence */ }
export function extractSelfDeclaredContext(activity, evidenceId) { /* age_band/state/budget only under exact rules */ }
export async function collectAuthorActivity(authors, adapter, options) { /* checkpoint each author, continue failures */ }
```

Age becomes a band; state is accepted only from explicit first-person text; budget and price behavior replace income; race/health are ignored; representative-user output never exposes individual demographic fields.

- [ ] **Step 4: Implement OpenCLI and public Reddit author-activity transport methods with 50-item/180-day limits and checkpoint files**

Public JSON/RSS failure for an author must return a recorded item failure and continue. The OpenCLI executable remains externally resolved.

- [ ] **Step 5: Run GREEN**

Run: `node --test tests/author-deep-dive.test.mjs tests/radar-pipeline.test.mjs tests/radar-core.test.mjs`

Expected: all tests pass; no unrelated author text appears in persisted fixture artifacts.

- [ ] **Step 6: Commit**

```powershell
git add src/author-deep-dive.mjs schemas/author-activity.schema.json src/radar-pipeline.mjs src/radar-core.mjs tests/author-deep-dive.test.mjs tests/radar-pipeline.test.mjs tests/radar-core.test.mjs
git commit -m "feat: add privacy-bounded Reddit author deep dives"
```

### Task 4: Exploratory keyword discovery and bounded second-round search

**Files:**
- Create: `src/keyword-discovery.mjs`
- Create: `schemas/keyword-candidates.schema.json`
- Modify: `src/radar-pipeline.mjs`
- Test: `tests/keyword-discovery.test.mjs`
- Modify: `tests/radar-pipeline.test.mjs`

**Interfaces:**
- Produces: `extractKeywordCandidates(evidence, authorActivity, config) -> KeywordCandidate[]`.
- Produces: `scoreKeywordCandidates(candidates, config) -> KeywordCandidate[]`.
- Produces: `selectRoundTwoTerms(candidates, { maxTerms: 20, minimumScore: 65 }) -> string[]`.
- Pipeline stage writes `keyword_candidates.json` and a round-two checkpoint.

- [ ] **Step 1: Write failing tests for provenance, normalization, brand status, one-user penalties, cross-community scores, and 20-term/65-score limits**

```js
test('exploratory terms can drive round two without mutating formal keywords', () => {
  const before = structuredClone(config.keywords.anchors);
  const selected = selectRoundTwoTerms(scoreKeywordCandidates(extractKeywordCandidates(evidence, activity, config), config));
  assert.ok(selected.includes('headlight protective film'));
  assert.deepEqual(config.keywords.anchors, before);
  assert.equal(selected.length <= 20, true);
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/keyword-discovery.test.mjs`

Expected: FAIL because keyword-discovery exports do not exist.

- [ ] **Step 3: Implement deterministic phrase extraction, normalization, provenance, seven-component scoring, penalties, and lifecycle states**

```js
export function extractKeywordCandidates(evidence, authorActivity, config = {}) { /* evidence-linked candidates */ }
export function scoreKeywordCandidates(candidates, config = {}) { /* 0-100 auditable score */ }
export function selectRoundTwoTerms(candidates, options = {}) { /* one bounded expansion only */ }
```

- [ ] **Step 4: Add round-two orchestration and checkpoint invalidation**

The pipeline runs round two once, searches at most 10 posts per selected term, canonical-deduplicates against round one, reapplies the evidence gate, and never recursively derives a third round.

- [ ] **Step 5: Run GREEN**

Run: `node --test tests/keyword-discovery.test.mjs tests/radar-pipeline.test.mjs`

Expected: selected terms meet thresholds, candidate provenance is complete, and formal config remains byte-identical.

- [ ] **Step 6: Commit**

```powershell
git add src/keyword-discovery.mjs schemas/keyword-candidates.schema.json src/radar-pipeline.mjs tests/keyword-discovery.test.mjs tests/radar-pipeline.test.mjs
git commit -m "feat: add evidence-driven keyword expansion"
```

### Task 5: Persona eligibility, clustering, representatives, and aggregate self-declarations

**Files:**
- Create: `src/persona-engine.mjs`
- Modify: `schemas/user_profile.schema.json`
- Test: `tests/persona-engine.test.mjs`
- Modify: `src/radar-analysis.mjs`

**Interfaces:**
- Produces: `evaluatePersonaEligibility(evidence, authors) -> { status, counts, missing }`.
- Produces: `buildPersonas(evidence, authorActivity, config) -> PersonaResult`.
- Produces: `aggregateSelfDeclaredContext(authors, { minimumCohort: 10 }) -> AggregateContext`.

- [ ] **Step 1: Write failing boundary tests for 199/200 evidence, 59/60 users, 29/30 deep-dived authors, 11/12 cluster members, and representative activity counts**

```js
test('persona generation refuses insufficient samples with explicit missing counts', () => {
  const result = evaluatePersonaEligibility(makeFixture({ evidence: 199, users: 60, authors: 30 }));
  assert.equal(result.status, 'insufficient_sample');
  assert.deepEqual(result.missing, [{ metric: 'qualified_evidence', required: 200, actual: 199 }]);
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/persona-engine.test.mjs`

Expected: FAIL because persona-engine exports do not exist.

- [ ] **Step 3: Implement deterministic behavior-feature vectors, stable clustering, cluster suppression, representative ranking, and aggregate self-declarations**

```js
export function evaluatePersonaEligibility(evidence, authors, thresholds = DEFAULT_PERSONA_THRESHOLDS) { /* exact gates */ }
export function buildPersonas(evidence, authorActivity, config = {}) { /* behavior-only personas */ }
export function aggregateSelfDeclaredContext(authorActivity, { minimumCohort = 10 } = {}) { /* aggregate only */ }
```

No cluster may publish fewer than 12 users. Exactly 3 representatives are emitted only when each has 3 retained activities. Age bands/state/budget aggregates require 10 qualified users and never appear on individual representative cards.

- [ ] **Step 4: Run GREEN and schema validation**

Run: `node --test tests/persona-engine.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs`

Expected: boundary cases and privacy assertions pass.

- [ ] **Step 5: Commit**

```powershell
git add src/persona-engine.mjs schemas/user_profile.schema.json src/radar-analysis.mjs tests/persona-engine.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs
git commit -m "feat: gate and generate evidence-backed personas"
```

### Task 6: Keyword cloud JSON and expanded offline report

**Files:**
- Create: `src/keyword-cloud.mjs`
- Create: `schemas/keyword-cloud.schema.json`
- Modify: `src/radar-report.mjs`
- Modify: `src/radar-runner.mjs`
- Test: `tests/keyword-cloud.test.mjs`
- Modify: `tests/radar-report.test.mjs`
- Modify: `tests/radar-runner.test.mjs`

**Interfaces:**
- Produces: `buildKeywordCloud(keywordCandidates, evidence) -> KeywordCloud`.
- `writeReportArtifacts` additionally writes `keyword_cloud.json`, `opportunities.json`, `personas.json`, `quality_evidence.jsonl`, and `excluded_evidence.jsonl`.
- HTML adds `关键词词云`, `痛点`, `竞品/现有产品`, `邻近配套`, and `用户画像` views.

- [ ] **Step 1: Write failing tests for term weights, categories, filters, evidence backlinks, offline assets, pain/opportunity separation, and insufficient persona copy**

```js
test('keyword cloud weight uses qualified users and evidence, not raw frequency alone', () => {
  const cloud = buildKeywordCloud(candidates, evidence);
  assert.ok(cloud.terms.find(item => item.term === 'protective film').display_weight > 0);
  assert.deepEqual(cloud.terms.find(item => item.term === 'protective film').evidence_ids, ['e1', 'e2']);
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/keyword-cloud.test.mjs tests/radar-report.test.mjs`

Expected: FAIL because cloud exports and tabs do not exist.

- [ ] **Step 3: Implement keyword cloud aggregation and schema**

```js
export function buildKeywordCloud(keywordCandidates, evidence) { /* deterministic category and display_weight */ }
```

- [ ] **Step 4: Refactor the report into render-only tab sections and add interactive cloud controls**

The cloud uses local SVG/HTML elements, click details, category/status/minimum-score filters, search, reset, and representative evidence links. Product opportunity cards show only concrete opportunities; pain cards occupy their own section.

- [ ] **Step 5: Run GREEN and artifact consistency tests**

Run: `node --test tests/keyword-cloud.test.mjs tests/radar-report.test.mjs tests/radar-runner.test.mjs tests/schema-contract.test.mjs`

Expected: all JSON/HTML counts match; `rg '<script[^>]+src=|<link[^>]+href=' report.html` finds no dependency tag.

- [ ] **Step 6: Commit**

```powershell
git add src/keyword-cloud.mjs schemas/keyword-cloud.schema.json src/radar-report.mjs src/radar-runner.mjs tests/keyword-cloud.test.mjs tests/radar-report.test.mjs tests/radar-runner.test.mjs tests/schema-contract.test.mjs
git commit -m "feat: add keyword cloud and V1.2 report views"
```

### Task 7: Stage-hashed checkpoints, failure history, and sample status

**Files:**
- Create: `src/checkpoint-store.mjs`
- Modify: `src/radar-pipeline.mjs`
- Modify: `schemas/run-manifest.schema.json`
- Test: `tests/checkpoint-store.test.mjs`
- Modify: `tests/radar-pipeline.test.mjs`

**Interfaces:**
- Produces: `hashStageInput(value) -> string`.
- Produces: `readStageCheckpoint(runDir, stage, inputHash, schemaVersion) -> value|null`.
- Produces: `writeStageCheckpoint(runDir, stage, inputHash, schemaVersion, value) -> path`.
- Manifest exposes `status`, `sample_status`, `persona_status`, `unresolved_failures`, and `cumulative_attempts`.

- [ ] **Step 1: Write failing tests for hash invalidation, historical failure retention, retry-only-unresolved behavior, and independent technical/sample/persona statuses**

```js
test('a config change invalidates only dependent stage checkpoints', async () => {
  await writeStageCheckpoint(runDir, 'quality', hashStageInput(inputA), '2.0.0', value);
  assert.equal(await readStageCheckpoint(runDir, 'quality', hashStageInput(inputB), '2.0.0'), null);
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/checkpoint-store.test.mjs`

Expected: FAIL because checkpoint-store exports do not exist.

- [ ] **Step 3: Implement SHA-256 input hashing, atomic checkpoint metadata, stage reuse, and append-only attempt records**

```js
export function hashStageInput(value) { /* stable JSON plus SHA-256 */ }
export async function readStageCheckpoint(runDir, stage, inputHash, schemaVersion) { /* exact-match reuse */ }
export async function writeStageCheckpoint(runDir, stage, inputHash, schemaVersion, value) { /* metadata plus payload */ }
```

- [ ] **Step 4: Integrate stage checkpoints and status semantics into the pipeline**

`complete|partial|failed` remains technical status. `sample_status: sufficient|insufficient` and `persona_status: complete|insufficient_sample` are calculated independently. Attempts append to `failure_attempts.jsonl`; `failures.jsonl` contains unresolved items.

- [ ] **Step 5: Run GREEN**

Run: `node --test tests/checkpoint-store.test.mjs tests/radar-pipeline.test.mjs tests/schema-contract.test.mjs`

Expected: stale checkpoints are rejected and historical attempts remain after a successful resume.

- [ ] **Step 6: Commit**

```powershell
git add src/checkpoint-store.mjs src/radar-pipeline.mjs schemas/run-manifest.schema.json tests/checkpoint-store.test.mjs tests/radar-pipeline.test.mjs tests/schema-contract.test.mjs
git commit -m "feat: add stage-hashed resumable checkpoints"
```

### Task 8: DSV4Pro provenance/schema validation and safe fallback

**Files:**
- Modify: `src/llm-client.mjs`
- Create: `schemas/dsv4pro-enrichment.schema.json`
- Test: `tests/llm-client.test.mjs`
- Modify: `src/radar-analysis.mjs`
- Modify: `tests/radar-analysis.test.mjs`

**Interfaces:**
- Produces: `validateEnrichment(result, allowedEvidenceIds) -> { valid, errors, value }`.
- `createOpenAiCompatibleAnalyzer` accepts `model: 'dsv4pro'`, two total attempts, one 30-second wait, and schema-constrained JSON.

- [ ] **Step 1: Write failing tests for invalid JSON, unknown evidence IDs, invented facts, timeout, retry count, and rule-result fallback**

```js
test('unknown evidence IDs invalidate enrichment and preserve rules', async () => {
  const result = await analyzeWithOptionalLlm(ruleAnalysis, async () => ({ opportunities: [{ evidence_ids: ['invented'] }] }));
  assert.equal(result.analysis_engine.active_result, 'rules');
  assert.match(result.analysis_engine.llm.reason, /unknown evidence/i);
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/llm-client.test.mjs tests/radar-analysis.test.mjs`

Expected: FAIL because provenance validation is absent.

- [ ] **Step 3: Implement schema/provenance validation, retry bounds, and merge-only enrichment**

```js
export function validateEnrichment(result, allowedEvidenceIds) { /* reject unknown IDs and invalid claims */ }
```

The LLM may add labels/explanations/candidate relationships but cannot remove rule evidence, alter formal keywords, bypass thresholds, or turn unknown commercial fields into facts.

- [ ] **Step 4: Run GREEN**

Run: `node --test tests/llm-client.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs`

Expected: valid enrichment merges; every invalid response records fallback and leaves rule output intact.

- [ ] **Step 5: Commit**

```powershell
git add src/llm-client.mjs schemas/dsv4pro-enrichment.schema.json src/radar-analysis.mjs tests/llm-client.test.mjs tests/radar-analysis.test.mjs tests/schema-contract.test.mjs
git commit -m "feat: validate DSV4Pro enrichment provenance"
```

### Task 9: V1.2 CLI profile and detailed Hermes handoff

**Files:**
- Modify: `src/radar-cli.mjs`
- Modify: `scripts/run-radar.mjs`
- Modify: `scripts/radar.ps1`
- Create: `configs/automotive_lighting_us_overnight_v1.2.json`
- Create: `.agents/HERMES_HANDOFF_V1.2.md`
- Create: `.agents/PROGRESS.md`
- Create: `.agents/OUTBOX.md`
- Create: `tests/hermes-handoff-contract.test.mjs`
- Modify: `tests/radar-cli.test.mjs`
- Modify: `tests/verify-lighting-interface.ps1`

**Interfaces:**
- CLI supports `--profile overnight`, `--max-runtime-minutes 600`, `--llm-model dsv4pro`, and the existing run/resume arguments.
- Hermes executes one documented PowerShell command and writes progress/outbox files in the exact documented format.

- [ ] **Step 1: Write failing contract tests that assert every command, environment variable name, retry ceiling, permission boundary, output file, stop condition, and final summary field**

```js
test('Hermes handoff is executable and forbids repository mutation', async () => {
  const text = await fs.readFile('.agents/HERMES_HANDOFF_V1.2.md', 'utf8');
  for (const token of ['dsv4pro', '600', 'RADAR_LLM_API_KEY', 'git push', 'PROHIBITED', 'failure_attempts.jsonl', 'keyword_cloud.json']) assert.match(text, new RegExp(token, 'i'));
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/hermes-handoff-contract.test.mjs tests/radar-cli.test.mjs`

Expected: FAIL because V1.2 handoff/profile does not exist.

- [ ] **Step 3: Implement the overnight config and CLI limits**

The config sets round-one target 300/hard max 400, deep-dive 100, comments 20, authors 60, author activities 50/180 days, round-two 20 terms/10 posts, combined max 500, and runtime 600 minutes.

- [ ] **Step 4: Write the complete Hermes handoff and empty structured progress/outbox templates**

The handoff contains exact repo/branch verification, preflight without secret values, command lines, stage order, checkpoint paths, retry waits (15/45 seconds Reddit; 30 seconds DSV4Pro), stop/non-stop conditions, prohibitions, acceptance commands, progress format, outbox format, and clean shutdown behavior.

- [ ] **Step 5: Dry-run every non-network handoff command and run GREEN**

Run: `node --test tests/hermes-handoff-contract.test.mjs tests/radar-cli.test.mjs; .\tests\verify-lighting-interface.ps1`

Expected: all contracts pass; no command depends on a personal absolute path or prints a secret.

- [ ] **Step 6: Commit**

```powershell
git add src/radar-cli.mjs scripts/run-radar.mjs scripts/radar.ps1 configs/automotive_lighting_us_overnight_v1.2.json .agents/HERMES_HANDOFF_V1.2.md .agents/PROGRESS.md .agents/OUTBOX.md tests/hermes-handoff-contract.test.mjs tests/radar-cli.test.mjs tests/verify-lighting-interface.ps1
git commit -m "feat: add V1.2 overnight Hermes handoff"
```

### Task 10: Integration, real pilot, verification, versioning, and push

**Files:**
- Modify: `src/radar-runner.mjs`
- Modify: `README.md`
- Modify: `docs/DATA_CONTRACT.md`
- Modify: `docs/BASELINE_GUIDE.md`
- Modify: `.github/workflows/reddit-lighting-radar.yml`
- Modify: `tests/radar-runner.test.mjs`
- Modify: `tests/github-actions-contract.test.mjs`

**Interfaces:**
- `runLightingRadar` executes all V1.2 stages and writes the complete artifact contract.
- GitHub Actions remains read-only and uploads V1.2 artifacts; it does not replace the Hermes local overnight profile.

- [ ] **Step 1: Write a failing end-to-end fixture test for the complete artifact list, status separation, opportunity/pain separation, exploratory round, persona insufficiency, and HTML/JSON equality**

```js
test('V1.2 runner produces the complete auditable artifact contract', async () => {
  const result = await runLightingRadar(fixtureOptions);
  for (const file of ['quality_evidence.jsonl','excluded_evidence.jsonl','keyword_candidates.json','keyword_cloud.json','opportunities.json','personas.json','analysis.json','audience_map.json','manifest.json','report.html']) assert.equal(await exists(path.join(runDir, file)), true, file);
  assert.equal(result.manifest.status, 'complete');
  assert.equal(result.manifest.persona_status, 'insufficient_sample');
});
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/radar-runner.test.mjs tests/github-actions-contract.test.mjs`

Expected: FAIL until the runner and workflow expose the V1.2 contract.

- [ ] **Step 3: Integrate all modules, update documentation/workflow, and run GREEN**

Run: `node --test tests/*.test.mjs`

Expected: every Node test passes.

- [ ] **Step 4: Run Windows and security verification**

```powershell
.\tests\verify-portable-config.ps1
.\tests\verify-portable-runtime.ps1
.\tests\verify-project-tools.ps1
.\tests\verify-windows-utf8.ps1
.\tests\verify-lighting-interface.ps1
git diff --check
git grep -n -I -E '(Bearer |client_secret|refresh_token|reddit_session|RADAR_LLM_API_KEY=.+)' -- ':!docs/superpowers/**'
```

Expected: all portable/interface checks pass; secret scan returns no matched secret values.

- [ ] **Step 5: Run a bounded real Reddit pilot and inspect artifacts**

Run with a new V1.2 run ID and the public transport first. Resume unresolved items without deleting artifacts. Verify evidence exclusions, no pain-only opportunity, second-round provenance, keyword cloud, sample/persona status, and offline report interactions. If public Reddit blocks individual items, preserve the auditable partial result and continue unrelated items.

- [ ] **Step 6: Perform the Hermes handoff ambiguity self-review**

Execute every non-secret preflight/verification command from `.agents/HERMES_HANDOFF_V1.2.md` in a clean working directory. Confirm the document distinguishes expected item failures from fatal stop conditions and technical completion from sample sufficiency.

- [ ] **Step 7: Commit integration, request code review, and address Critical/Important findings**

```powershell
git add src/radar-runner.mjs README.md docs/DATA_CONTRACT.md docs/BASELINE_GUIDE.md .github/workflows/reddit-lighting-radar.yml tests/radar-runner.test.mjs tests/github-actions-contract.test.mjs
git commit -m "feat: complete V1.2 market intelligence pipeline"
```

- [ ] **Step 8: Verify and publish V1.2 without rewriting V1.1**

Confirm `v1.1.0` still resolves to `5ed1de6`. Create annotated tag `v1.2.0` only after all checks pass. Push the existing branch and tag normally; do not force-push and do not modify `main`.

