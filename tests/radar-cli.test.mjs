import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { parseCliArgs, selectTransportName } from '../src/radar-cli.mjs';
import { createOpenAiCompatibleAnalyzer } from '../src/llm-client.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('CLI parser exposes config, transport, run id, and output root', () => {
  const options = parseCliArgs(['--config', 'configs/light.json', '--transport', 'public-json', '--run-id', 'pilot-1', '--output-root', '.local/runs']);

  assert.equal(options.config, 'configs/light.json');
  assert.equal(options.transport, 'public-json');
  assert.equal(options.runId, 'pilot-1');
  assert.equal(options.outputRoot, '.local/runs');
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

  assert.match(output, /--transport <auto\|opencli\|public-json>/);
  assert.match(output, /--output-root/);
  assert.match(output, /automotive_lighting_us_pilot\.json/);
});
