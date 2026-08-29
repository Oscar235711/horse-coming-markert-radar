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
  const outputRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-runtime-root-'));
  const runId = 'overnight-20260828-1200';
  const runDir = path.join(outputRoot, runId);
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  await fs.mkdir(path.join(runDir, 'raw', 'details'), { recursive: true });
  await fs.writeFile(path.join(runDir, 'config.snapshot.json'), '{}\n', 'utf8');
  await fs.writeFile(path.join(runDir, 'candidates.json'), '[]\n', 'utf8');
  await fs.writeFile(path.join(runDir, 'raw', 'details', 'p1.json'), '{}\n', 'utf8');

  const artifacts = await listCompletedArtifacts(runDir);
  assert.deepEqual(artifacts, ['candidates.json', 'config.snapshot.json', 'raw/details/p1.json']);

  const summary = await writeRuntimeStatus({
    runDir,
    outputRoot,
    runId,
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

test('runtime status writer refuses to write outside outputRoot/runId', async (t) => {
  const outputRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-runtime-root-'));
  const outsideDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-runtime-outside-'));
  t.after(() => Promise.all([
    fs.rm(outputRoot, { recursive: true, force: true }),
    fs.rm(outsideDir, { recursive: true, force: true }),
  ]));

  await assert.rejects(() => writeRuntimeStatus({
    outputRoot,
    runDir: outsideDir,
    runId: 'safe-run',
    runtimeLimitMinutes: 600,
    status: 'failed',
    reason: 'should not write outside the run directory',
    startedAt: '2026-08-28T12:00:00.000Z',
    finishedAt: '2026-08-28T12:01:00.000Z',
    stage: 'verification',
  }), /outputRoot\/runId/i);

  assert.equal(
    await fs.access(path.join(outsideDir, 'runtime-status.json')).then(() => true).catch(() => false),
    false,
  );
});

test('CLI runtime rejects run IDs that are not safe single-segment directory names', async (t) => {
  const repoDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-cli-runid-'));
  t.after(() => fs.rm(repoDir, { recursive: true, force: true }));

  for (const runId of ['.', '..', '../escape', '..\\escape', 'nested/run', 'nested\\run']) {
    let loadConfigCalled = false;
    await assert.rejects(() => executeRadarRun({
      options: {
        config: 'configs/runtime-fixture.json',
        profile: '',
        transport: 'public-json',
        runId,
        outputRoot: '.local/runs',
        maxRuntimeMinutes: null,
        llmModel: '',
        openCliPath: '',
      },
      repoRoot: repoDir,
      environment: {},
      loadConfig: async () => {
        loadConfigCalled = true;
        throw new Error('loadConfig should not run for invalid run IDs');
      },
    }), /Invalid run id:/i, `runId ${runId} should be rejected`);
    assert.equal(loadConfigCalled, false, `loadConfig should not run for invalid runId ${runId}`);
  }
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

test('CLI runtime status mirrors the manifest status for successful bounded runs', async (t) => {
  for (const manifestStatus of ['partial', 'complete']) {
    const repoDir = await fs.mkdtemp(path.join(os.tmpdir(), `radar-cli-status-${manifestStatus}-`));
    t.after(() => fs.rm(repoDir, { recursive: true, force: true }));

    const summary = await executeRadarRun({
      options: {
        config: 'configs/runtime-fixture.json',
        profile: '',
        transport: 'public-json',
        runId: `manifest-${manifestStatus}`,
        outputRoot: '.local/runs',
        maxRuntimeMinutes: 10,
        llmModel: '',
        openCliPath: '',
      },
      repoRoot: repoDir,
      environment: {},
      loadConfig: async () => ({
        transport: { timeout_ms: 30000 },
        analysis: { llm: { enabled_by_default: false } },
      }),
      createPublicJsonAdapter: () => ({ name: 'fixture-public-json' }),
      runLightingRadarImpl: async ({ runDir, runId }) => {
        await fs.mkdir(runDir, { recursive: true });
        await fs.writeFile(path.join(runDir, 'config.snapshot.json'), '{}\n', 'utf8');
        await fs.writeFile(path.join(runDir, 'report.html'), '<html></html>\n', 'utf8');
        return {
          manifest: {
            run_id: runId,
            status: manifestStatus,
            transport: 'public-json',
            counts: { failures: manifestStatus === 'partial' ? 1 : 0 },
          },
        };
      },
    });

    assert.equal(summary.status, manifestStatus);
    const status = JSON.parse(await fs.readFile(path.join(repoDir, '.local', 'runs', `manifest-${manifestStatus}`, 'runtime-status.json'), 'utf8'));
    assert.equal(status.status, manifestStatus);
    assert.match(status.reason, new RegExp(`Run ${manifestStatus}`, 'i'));
  }
});

test('CLI runtime timeout aborts the live OpenCLI child process and records timed_out status', async (t) => {
  const repoDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-cli-opencli-timeout-'));
  const fixturePath = path.join(repoDir, 'opencli-timeout-fixture.cjs');
  const markerPath = path.join(repoDir, 'opencli-finished.txt');
  t.after(() => fs.rm(repoDir, { recursive: true, force: true }));

  await fs.writeFile(fixturePath, `'use strict';
const fs = require('node:fs/promises');
const markerPath = process.argv[2];
setTimeout(async () => {
  await fs.writeFile(markerPath, 'finished\\n', 'utf8');
  process.stdout.write('[]');
}, 400);
`, 'utf8');

  await assert.rejects(() => executeRadarRun({
    options: {
      config: 'configs/runtime-fixture.json',
      profile: '',
      transport: 'opencli',
      runId: 'opencli-timeout',
      outputRoot: '.local/runs',
      maxRuntimeMinutes: 0.002,
      llmModel: '',
      openCliPath: 'ignored-opencli',
    },
    repoRoot: repoDir,
    environment: {},
    loadConfig: async () => ({
      transport: { timeout_ms: 30000 },
      analysis: { llm: { enabled_by_default: false } },
    }),
    createOpenCliAdapter: ({ execImpl }) => ({
      name: 'opencli',
      async search() {
        const { stdout } = await execImpl(process.execPath, [fixturePath, markerPath], {
          encoding: 'utf8',
          windowsHide: true,
          shell: false,
        });
        return JSON.parse(stdout);
      },
    }),
    runLightingRadarImpl: async ({ adapter, runDir }) => {
      await fs.mkdir(runDir, { recursive: true });
      await fs.writeFile(path.join(runDir, 'config.snapshot.json'), '{}\n', 'utf8');
      await adapter.search('headlight timeout');
      throw new Error('search should have timed out');
    },
  }), /0\.002 minutes.*round-one-search/i);

  await wait(500);
  assert.equal(await fs.access(markerPath).then(() => true).catch(() => false), false);

  const status = JSON.parse(await fs.readFile(path.join(repoDir, '.local', 'runs', 'opencli-timeout', 'runtime-status.json'), 'utf8'));
  assert.equal(status.status, 'timed_out');
  assert.equal(status.stage, 'round-one-search');
  assert.deepEqual(status.completed_artifacts, ['config.snapshot.json']);
});

test('CLI runtime timeout kills a real Windows .cmd OpenCLI wrapper tree and records timed_out status', async (t) => {
  if (process.platform !== 'win32') {
    t.skip('Windows-specific .cmd wrapper behavior');
  }

  const repoDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-cli-opencli-cmd-timeout-'));
  const childScriptPath = path.join(repoDir, 'opencli-timeout-child.cjs');
  const wrapperPath = path.join(repoDir, 'opencli.cmd');
  const markerPath = path.join(repoDir, 'opencli-cmd-finished.txt');
  t.after(() => fs.rm(repoDir, { recursive: true, force: true }));

  await fs.writeFile(childScriptPath, `'use strict';
const fs = require('node:fs/promises');
const markerPath = ${JSON.stringify(markerPath)};
setTimeout(async () => {
  await fs.writeFile(markerPath, 'finished\\n', 'utf8');
  process.stdout.write('[]');
}, 400);
`, 'utf8');
  await fs.writeFile(wrapperPath, `@echo off
"${process.execPath}" "%~dp0opencli-timeout-child.cjs" %*
`, 'utf8');

  await assert.rejects(() => executeRadarRun({
    options: {
      config: 'configs/runtime-fixture.json',
      profile: '',
      transport: 'opencli',
      runId: 'opencli-cmd-timeout',
      outputRoot: '.local/runs',
      maxRuntimeMinutes: 0.002,
      llmModel: '',
      openCliPath: 'opencli.cmd',
    },
    repoRoot: repoDir,
    environment: {},
    loadConfig: async () => ({
      transport: { timeout_ms: 30000 },
      analysis: { llm: { enabled_by_default: false } },
    }),
    runLightingRadarImpl: async ({ adapter, runDir }) => {
      await fs.mkdir(runDir, { recursive: true });
      await fs.writeFile(path.join(runDir, 'config.snapshot.json'), '{}\n', 'utf8');
      await adapter.search('headlight timeout');
      throw new Error('search should have timed out');
    },
  }), /0\.002 minutes.*round-one-search/i);

  await wait(500);
  assert.equal(await fs.access(markerPath).then(() => true).catch(() => false), false);

  const status = JSON.parse(await fs.readFile(path.join(repoDir, '.local', 'runs', 'opencli-cmd-timeout', 'runtime-status.json'), 'utf8'));
  assert.equal(status.status, 'timed_out');
  assert.equal(status.stage, 'round-one-search');
  assert.deepEqual(status.completed_artifacts, ['config.snapshot.json']);
});

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
