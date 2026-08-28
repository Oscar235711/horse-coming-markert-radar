import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  createRuntimeBudget,
  executeRadarRun,
  listCompletedArtifacts,
  parseCliArgs,
  resolveProfileConfigPath,
  selectTransportName,
  writeRuntimeStatus,
} from '../src/radar-cli.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('CLI parser exposes config, transport, run id, and output root', () => {
  const options = parseCliArgs(['--config', 'configs/light.json', '--transport', 'public-json', '--run-id', 'pilot-1', '--output-root', '.local/runs']);

  assert.equal(options.config, 'configs/light.json');
  assert.equal(options.transport, 'public-json');
  assert.equal(options.runId, 'pilot-1');
  assert.equal(options.outputRoot, '.local/runs');
});

test('CLI parser accepts overnight profile, runtime ceiling, and explicit LLM model', () => {
  const options = parseCliArgs([
    '--profile',
    'overnight',
    '--max-runtime-minutes',
    '600',
    '--llm-model',
    'dsv4pro',
    '--run-id',
    'overnight-1',
  ]);

  assert.equal(options.profile, 'overnight');
  assert.equal(options.maxRuntimeMinutes, 600);
  assert.equal(options.llmModel, 'dsv4pro');
  assert.equal(options.runId, 'overnight-1');
});

test('profile resolution selects the overnight config unless an explicit config overrides it', () => {
  assert.equal(
    resolveProfileConfigPath({ profile: 'overnight', config: 'configs/automotive_lighting_us_pilot.json' }),
    'configs/automotive_lighting_us_pilot.json',
  );
  assert.equal(
    resolveProfileConfigPath({ profile: 'overnight', config: '' }),
    'configs/automotive_lighting_us_overnight_v1.2.json',
  );
});

test('auto transport uses public JSON in CI and OpenCLI locally when available', () => {
  assert.equal(selectTransportName({ requested: 'auto', ci: true, openCliPath: 'opencli.cmd' }), 'public-json');
  assert.equal(selectTransportName({ requested: 'auto', ci: false, openCliPath: 'opencli.cmd' }), 'opencli');
  assert.equal(selectTransportName({ requested: 'auto', ci: false, openCliPath: '' }), 'public-json');
});

test('run-radar CLI exposes a stable help contract', () => {
  const output = execFileSync(process.execPath, [path.join(repoRoot, 'scripts', 'run-radar.mjs'), '--help'], { encoding: 'utf8' });

  assert.match(output, /--profile <overnight>/);
  assert.match(output, /--max-runtime-minutes <minutes>/);
  assert.match(output, /--llm-model <model>/);
  assert.match(output, /--transport <auto\|opencli\|public-json>/);
  assert.match(output, /--output-root/);
  assert.match(output, /automotive_lighting_us_overnight_v1\.2\.json/);
  assert.match(output, /automotive_lighting_us_pilot\.json/);
  assert.match(output, /Enforced wall-clock ceiling/i);
  assert.match(output, /runtime-status\.json/i);
});

test('overnight profile config preserves the Task 9 ceilings', async () => {
  const config = JSON.parse(await fs.readFile(path.join(repoRoot, 'configs', 'automotive_lighting_us_overnight_v1.2.json'), 'utf8'));

  assert.equal(config.limits.round_one_target_posts, 300);
  assert.equal(config.limits.posts, 400);
  assert.equal(config.limits.deep_dive_posts, 100);
  assert.equal(config.limits.comments_per_post, 20);
  assert.equal(config.limits.profile_users, 60);
  assert.equal(config.limits.profile_items_per_user, 50);
  assert.equal(config.limits.profile_activity_lookback_days, 180);
  assert.equal(config.limits.round_two_terms, 20);
  assert.equal(config.limits.round_two_posts_per_term, 10);
  assert.equal(config.limits.combined_candidate_posts, 500);
  assert.equal(config.analysis.llm.enabled_by_default, true);
  assert.equal(config.analysis.llm.default_model, 'dsv4pro');
});

test('runtime budget clamps operation windows and stops new work after the deadline', () => {
  let nowMs = Date.UTC(2026, 7, 28, 12, 0, 0);
  const budget = createRuntimeBudget({
    maxRuntimeMinutes: 10,
    now: () => nowMs,
    defaultOperationTimeoutMs: 30000,
  });

  assert.equal(budget.remainingMs(), 600000);
  assert.equal(budget.capTimeout(30000), 30000);
  nowMs += 590000;
  assert.equal(budget.capTimeout(30000), 10000);
  nowMs += 10000;
  assert.equal(budget.remainingMs(), 0);
  assert.throws(() => budget.throwIfExceeded('detail-fetch'), /10 minutes.*detail-fetch/i);
});

test('runtime status writer records timeout state and completed artifacts from partial output', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-runtime-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  await fs.mkdir(path.join(runDir, 'raw', 'details'), { recursive: true });
  await fs.writeFile(path.join(runDir, 'config.snapshot.json'), '{}\n', 'utf8');
  await fs.writeFile(path.join(runDir, 'candidates.json'), '[]\n', 'utf8');
  await fs.writeFile(path.join(runDir, 'raw', 'details', 'p1.json'), '{}\n', 'utf8');

  const artifacts = await listCompletedArtifacts(runDir);
  assert.deepEqual(artifacts, ['candidates.json', 'config.snapshot.json', 'raw/details/p1.json']);

  const summary = await writeRuntimeStatus({
    runDir,
    runId: 'overnight-20260828-1200',
    runtimeLimitMinutes: 600,
    profile: 'overnight',
    transport: 'opencli',
    llmModel: 'dsv4pro',
    status: 'timed_out',
    reason: 'Max runtime of 600 minutes reached during detail-fetch.',
    startedAt: '2026-08-28T12:00:00.000Z',
    finishedAt: '2026-08-28T22:00:00.000Z',
    stage: 'detail-fetch',
  });

  assert.equal(summary.status, 'timed_out');
  assert.equal(summary.stage, 'detail-fetch');
  assert.deepEqual(summary.completed_artifacts, artifacts);
  assert.equal(summary.runtime_limit_minutes, 600);
  const saved = JSON.parse(await fs.readFile(path.join(runDir, 'runtime-status.json'), 'utf8'));
  assert.equal(saved.reason, 'Max runtime of 600 minutes reached during detail-fetch.');
  assert.deepEqual(saved.completed_artifacts, artifacts);
});

test('CLI runtime enforcement stops new work, preserves partial artifacts, and writes runtime status', async (t) => {
  const repoDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-cli-repo-'));
  const runId = 'overnight-20260828-1200';
  let nowMs = Date.UTC(2026, 7, 28, 12, 0, 0);
  const adapterCalls = [];

  t.after(() => fs.rm(repoDir, { recursive: true, force: true }));

  await assert.rejects(() => executeRadarRun({
    options: {
      config: 'configs/runtime-fixture.json',
      profile: '',
      transport: 'public-json',
      runId,
      outputRoot: '.local/runs',
      maxRuntimeMinutes: 10,
      llmModel: '',
      openCliPath: '',
    },
    repoRoot: repoDir,
    now: () => nowMs,
    environment: {},
    loadConfig: async () => ({
      transport: { timeout_ms: 30000 },
      analysis: { llm: { enabled_by_default: false } },
    }),
    createPublicJsonAdapter: () => ({
      name: 'fixture-public-json',
      async search(query, options = {}) {
        adapterCalls.push({ stage: 'round-one-search', query, timeoutMs: options.timeoutMs });
        nowMs += 10 * 60 * 1000;
        return [];
      },
      async fetchDetails() {
        throw new Error('fetchDetails should not run after the runtime deadline');
      },
    }),
    runLightingRadarImpl: async ({ adapter, runDir: activeRunDir }) => {
      await fs.mkdir(activeRunDir, { recursive: true });
      await fs.writeFile(path.join(activeRunDir, 'config.snapshot.json'), '{}\n', 'utf8');
      await fs.writeFile(path.join(activeRunDir, 'candidates.json'), '[]\n', 'utf8');
      await adapter.search('headlight flicker', { timeoutMs: 30000 });
      await adapter.fetchDetails({ post_id: 'p1', subreddit: 'mechanicadvice' }, { timeoutMs: 30000 });
    },
  }), /10 minutes.*detail-fetch/i);

  assert.deepEqual(adapterCalls, [{
    stage: 'round-one-search',
    query: 'headlight flicker',
    timeoutMs: 30000,
  }]);

  const statusPath = path.join(repoDir, '.local', 'runs', runId, 'runtime-status.json');
  const status = JSON.parse(await fs.readFile(statusPath, 'utf8'));
  assert.equal(status.status, 'timed_out');
  assert.equal(status.stage, 'detail-fetch');
  assert.equal(status.runtime_limit_minutes, 10);
  assert.match(status.reason, /detail-fetch/i);
  assert.deepEqual(status.completed_artifacts, ['candidates.json', 'config.snapshot.json']);
});
