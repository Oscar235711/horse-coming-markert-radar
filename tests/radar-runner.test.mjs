import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { runLightingRadar } from '../src/radar-runner.mjs';
import { validateAgainstSchemaFile } from './helpers/schema-validator.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const config = {
  schema_version: '1.0.0',
  name: 'runner-fixture',
  market: { country: 'US' },
  keywords: { anchors: Array.from({ length: 14 }, (_, index) => `anchor-${index}`), expanded: ['fog light'], candidate_only_brands: [] },
  query_groups: ['headlight issue'],
  subreddits: Array.from({ length: 10 }, (_, index) => `sub${index}`),
  limits: { posts: 30, comments_per_post: 20, search_results_per_query: 15 },
  transport: { request_interval_ms: 0, timeout_ms: 1000 },
};

test('runner produces normalized data, analysis, graph, and offline report in one run directory', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-runner-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const adapter = {
    name: 'fixture',
    async search() {
      return [{ id: 'p1', title: 'H11 LED headlight flicker on F-150', selftext: 'Texas. What should I buy under $100?', subreddit: 'sub0', score: 20, num_comments: 10, permalink: '/comments/p1/x' }];
    },
    async fetchDetails(post) {
      return { post: { id: post.post_id, title: post.title, selftext: post.body_original, subreddit: post.subreddit, score: post.score, num_comments: post.comment_count, permalink: post.url }, comments: [{ id: 'c1', body: 'CANbus fixed the flicker', score: 4, permalink: '/comments/p1/x/c1' }] };
    },
  };

  const result = await runLightingRadar({ config, adapter, runDir, runId: 'runner-run' });

  for (const name of ['manifest.json', 'candidates.json', 'analysis.json', 'audience_map.json', 'keyword_candidates.json', 'keyword_cloud.json', 'opportunities.json', 'personas.json', 'quality_evidence.jsonl', 'excluded_evidence.jsonl', 'optimization_backlog.jsonl', 'report.html']) {
    assert.equal(await exists(path.join(runDir, name)), true, name);
  }
  const manifest = JSON.parse(await fs.readFile(path.join(runDir, 'manifest.json'), 'utf8'));
  const opportunitiesArtifact = JSON.parse(await fs.readFile(path.join(runDir, 'opportunities.json'), 'utf8'));
  assert.equal(result.analysis.run_id, 'runner-run');
  assert.equal(result.analysis.opportunities.length, 0);
  assert.ok(result.analysis.candidate_signals.length >= 1);
  assert.equal(result.audienceMap.nodes.length, 0);
  assert.equal(result.audienceMap.edges.length, 0);
  assert.equal(result.keywordCloud.terms.length >= 1, true);
  assert.equal(result.manifest.status, 'complete');
  assert.equal(result.manifest.persona_status, 'insufficient_sample');
  assert.equal(result.manifest.artifacts.keyword_cloud, 'keyword_cloud.json');
  assert.equal(result.manifest.artifacts.personas, 'personas.json');
  assert.equal(result.manifest.artifacts.quality_evidence, 'quality_evidence.jsonl');
  assert.equal(manifest.artifacts.opportunities, 'opportunities.json');
  assert.equal(manifest.counts.keyword_cloud_terms, result.keywordCloud.terms.length);
  assert.deepEqual(await validateAgainstSchemaFile(repoRoot, 'run-manifest.schema.json', result.manifest), []);
  assert.deepEqual(await validateAgainstSchemaFile(repoRoot, 'run-manifest.schema.json', manifest), []);
  assert.equal(opportunitiesArtifact.run_id, 'runner-run');
  assert.ok(Array.isArray(opportunitiesArtifact.candidate_signals));
});

async function exists(filePath) {
  try { await fs.access(filePath); return true; } catch { return false; }
}
