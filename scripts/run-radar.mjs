#!/usr/bin/env node
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  DEFAULT_CONFIG_PATH,
  executeRadarRun,
  parseCliArgs,
} from '../src/radar-cli.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function printHelp() {
  process.stdout.write(`US Automotive Lighting Reddit Radar\n\nUsage:\n  node scripts/run-radar.mjs [options]\n\nOptions:\n  --config <path>                         Default: ${DEFAULT_CONFIG_PATH}\n  --profile <overnight>                   Profile shortcut for configs/automotive_lighting_us_overnight_v1.2.json\n  --transport <auto|opencli|public-json> Default: auto\n  --opencli <path>                        Explicit OpenCLI executable\n  --run-id <id>                           Reuse the same ID to resume\n  --output-root <path>                    Default: .local/runs\n  --max-runtime-minutes <minutes>         Enforced wall-clock ceiling for Hermes handoff flows\n  --llm-model <model>                     Force the OpenAI-compatible model and enable LLM analysis\n  -h, --help                              Show this help\n\nWhen a runtime ceiling is configured, the runner writes runtime-status.json with the final status, stage, reason, and completed artifacts.\n\nOptional LLM environment:\n  RADAR_LLM_ENABLED=1\n  RADAR_LLM_BASE_URL=https://.../v1\n  RADAR_LLM_API_KEY=...\n  RADAR_LLM_MODEL=...\n`);
}

async function main() {
  const options = parseCliArgs(process.argv.slice(2));
  if (options.help) { printHelp(); return; }
  const summary = await executeRadarRun({ options, repoRoot, environment: process.env });
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`RADAR_FATAL ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
