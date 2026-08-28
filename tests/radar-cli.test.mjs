import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { parseCliArgs, resolveProfileConfigPath, selectTransportName } from '../src/radar-cli.mjs';
import { createOpenAiCompatibleAnalyzer } from '../src/llm-client.mjs';

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

test('OpenAI-compatible analyzer returns structured enrichment', async () => {
  let requestedUrl = '';
  const analyzer = createOpenAiCompatibleAnalyzer({
    baseUrl: 'https://example.test/v1',
    apiKey: 'test-key',
    model: 'example-model',
    fetchImpl: async (url, options) => {
      requestedUrl = String(url);
      assert.equal(options.headers.Authorization, 'Bearer test-key');
      return {
        ok: true,
        async json() { return { choices: [{ message: { content: '{"executive_summary":"LLM enriched"}' } }] }; },
        async text() { return ''; },
      };
    },
  });

  const result = await analyzer({ executive_summary: 'rules', opportunities: [] });

  assert.equal(requestedUrl, 'https://example.test/v1/chat/completions');
  assert.equal(result.executive_summary, 'LLM enriched');
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
