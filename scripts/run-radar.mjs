#!/usr/bin/env node
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  createRunId,
  DEFAULT_CONFIG_PATH,
  parseCliArgs,
  resolveProfileConfigPath,
  selectTransportName,
} from '../src/radar-cli.mjs';
import { loadLightingConfig } from '../src/radar-core.mjs';
import { createOpenAiCompatibleAnalyzer } from '../src/llm-client.mjs';
import { createOpenCliAdapter, createPublicJsonAdapter } from '../src/radar-pipeline.mjs';
import { runLightingRadar } from '../src/radar-runner.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function printHelp() {
  process.stdout.write(`US Automotive Lighting Reddit Radar\n\nUsage:\n  node scripts/run-radar.mjs [options]\n\nOptions:\n  --config <path>                         Default: ${DEFAULT_CONFIG_PATH}\n  --profile <overnight>                   Profile shortcut for configs/automotive_lighting_us_overnight_v1.2.json\n  --transport <auto|opencli|public-json> Default: auto\n  --opencli <path>                        Explicit OpenCLI executable\n  --run-id <id>                           Reuse the same ID to resume\n  --output-root <path>                    Default: .local/runs\n  --max-runtime-minutes <minutes>         Advisory wall-clock ceiling for Hermes handoff flows\n  --llm-model <model>                     Force the OpenAI-compatible model and enable LLM analysis\n  -h, --help                              Show this help\n\nOptional LLM environment:\n  RADAR_LLM_ENABLED=1\n  RADAR_LLM_BASE_URL=https://.../v1\n  RADAR_LLM_API_KEY=...\n  RADAR_LLM_MODEL=...\n`);
}

async function main() {
  const options = parseCliArgs(process.argv.slice(2));
  if (options.help) { printHelp(); return; }
  const selectedConfig = resolveProfileConfigPath({ profile: options.profile, config: options.config });
  const configPath = path.resolve(repoRoot, selectedConfig);
  const outputRoot = path.resolve(repoRoot, options.outputRoot);
  const runId = options.runId || createRunId();
  const runDir = path.join(outputRoot, runId);
  const config = await loadLightingConfig(configPath);
  const transportName = selectTransportName({ requested: options.transport, ci: Boolean(process.env.CI), openCliPath: options.openCliPath });
  const adapter = transportName === 'opencli'
    ? createOpenCliAdapter({ executablePath: path.resolve(repoRoot, options.openCliPath) })
    : createPublicJsonAdapter();

  if (options.maxRuntimeMinutes !== null) {
    process.env.RADAR_MAX_RUNTIME_MINUTES = String(options.maxRuntimeMinutes);
  }

  const llmModel = options.llmModel || process.env.RADAR_LLM_MODEL || config.analysis?.llm?.default_model || '';
  const llmEnabled = process.env.RADAR_LLM_ENABLED === '1' || Boolean(options.llmModel) || config.analysis?.llm?.enabled_by_default === true;
  if (options.llmModel) {
    process.env.RADAR_LLM_MODEL = options.llmModel;
    process.env.RADAR_LLM_ENABLED = '1';
  }

  let llmAnalyzer = null;
  if (llmEnabled) {
    llmAnalyzer = createOpenAiCompatibleAnalyzer({
      baseUrl: process.env.RADAR_LLM_BASE_URL,
      apiKey: process.env.RADAR_LLM_API_KEY,
      model: llmModel,
    });
  }
  const result = await runLightingRadar({ config, adapter, runDir, runId, llmAnalyzer });
  process.stdout.write(`${JSON.stringify({
    run_id: result.manifest.run_id,
    status: result.manifest.status,
    transport: result.manifest.transport,
    profile: options.profile || null,
    llm_model: llmModel || null,
    runtime_limit_minutes: options.maxRuntimeMinutes,
    counts: result.manifest.counts,
    run_dir: runDir,
    report: path.join(runDir, 'report.html'),
  }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`RADAR_FATAL ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
