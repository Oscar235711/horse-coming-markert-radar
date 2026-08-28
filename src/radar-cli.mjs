import fs from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';

import { loadLightingConfig } from './radar-core.mjs';
import { createOpenAiCompatibleAnalyzer } from './llm-client.mjs';
import { createOpenCliAdapter, createPublicJsonAdapter } from './radar-pipeline.mjs';
import { runLightingRadar } from './radar-runner.mjs';

export const DEFAULT_CONFIG_PATH = 'configs/automotive_lighting_us_pilot.json';
export const RUNTIME_STATUS_FILENAME = 'runtime-status.json';

const PROFILE_CONFIGS = {
  overnight: 'configs/automotive_lighting_us_overnight_v1.2.json',
};

export function parseCliArgs(argv) {
  const options = {
    config: '',
    profile: '',
    transport: 'auto',
    runId: '',
    outputRoot: '.local/runs',
    maxRuntimeMinutes: null,
    llmModel: '',
    openCliPath: process.env.RADAR_OPENCLI_EXE ?? '',
    help: false,
  };
  const valueFlags = new Map([
    ['--config', 'config'],
    ['--profile', 'profile'],
    ['--transport', 'transport'],
    ['--run-id', 'runId'],
    ['--output-root', 'outputRoot'],
    ['--max-runtime-minutes', 'maxRuntimeMinutes'],
    ['--llm-model', 'llmModel'],
    ['--opencli', 'openCliPath'],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') { options.help = true; continue; }
    const property = valueFlags.get(arg);
    if (!property) throw new Error(`Unknown argument: ${arg}`);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
    options[property] = value;
    index += 1;
  }
  if (options.profile && !(options.profile in PROFILE_CONFIGS)) {
    throw new Error(`Unsupported profile: ${options.profile}`);
  }
  if (!['auto', 'opencli', 'public-json'].includes(options.transport)) {
    throw new Error(`Unsupported transport: ${options.transport}`);
  }
  if (options.maxRuntimeMinutes !== null) {
    const parsed = Number.parseInt(options.maxRuntimeMinutes, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      throw new Error(`Invalid --max-runtime-minutes: ${options.maxRuntimeMinutes}`);
    }
    options.maxRuntimeMinutes = parsed;
  }
  return options;
}

export function resolveProfileConfigPath({ profile = '', config = '' } = {}) {
  if (config) return config;
  if (profile) return PROFILE_CONFIGS[profile];
  return DEFAULT_CONFIG_PATH;
}

export function selectTransportName({ requested = 'auto', ci = false, openCliPath = '' } = {}) {
  if (requested !== 'auto') return requested;
  if (ci) return 'public-json';
  return openCliPath ? 'opencli' : 'public-json';
}

export function createRunId(now = new Date()) {
  return `lighting-us-${now.toISOString().replace(/[:.]/g, '-').replace('Z', '')}`;
}

export function createRuntimeBudget({
  maxRuntimeMinutes = null,
  now = () => Date.now(),
  defaultOperationTimeoutMs = 30000,
} = {}) {
  const normalizedLimit = Number.isFinite(Number(maxRuntimeMinutes)) && Number(maxRuntimeMinutes) > 0
    ? Number(maxRuntimeMinutes)
    : null;
  const readNow = typeof now === 'function' ? now : () => now;
  const startedAtMs = normalizeNow(readNow());
  const deadlineAtMs = normalizedLimit === null ? null : startedAtMs + normalizedLimit * 60 * 1000;

  function remainingMs() {
    if (deadlineAtMs === null) return Number.POSITIVE_INFINITY;
    return Math.max(0, deadlineAtMs - normalizeNow(readNow()));
  }

  function isExceeded() {
    return deadlineAtMs !== null && remainingMs() <= 0;
  }

  function capTimeout(timeoutMs = defaultOperationTimeoutMs) {
    const requested = normalizePositiveInteger(timeoutMs, defaultOperationTimeoutMs);
    if (deadlineAtMs === null) return requested;
    return Math.max(0, Math.min(requested, remainingMs()));
  }

  function throwIfExceeded(stage = 'runtime') {
    if (!isExceeded()) return;
    throw createRuntimeLimitError({
      stage,
      maxRuntimeMinutes: normalizedLimit,
    });
  }

  return {
    maxRuntimeMinutes: normalizedLimit,
    defaultOperationTimeoutMs: normalizePositiveInteger(defaultOperationTimeoutMs, 30000),
    startedAtMs,
    deadlineAtMs,
    remainingMs,
    isExceeded,
    capTimeout,
    throwIfExceeded,
  };
}

export function createRuntimeLimitError({
  stage = 'runtime',
  maxRuntimeMinutes = null,
  cause = null,
} = {}) {
  const limitLabel = Number.isFinite(Number(maxRuntimeMinutes)) && Number(maxRuntimeMinutes) > 0
    ? `${Number(maxRuntimeMinutes)} minutes`
    : 'the configured runtime limit';
  const error = new Error(`Max runtime of ${limitLabel} reached during ${stage}.`);
  error.code = 'RADAR_RUNTIME_LIMIT';
  error.stage = stage;
  error.maxRuntimeMinutes = maxRuntimeMinutes;
  if (cause) error.cause = cause;
  return error;
}

export function isRuntimeLimitError(error) {
  return error?.code === 'RADAR_RUNTIME_LIMIT';
}

export function createRuntimeAwareAdapter(adapter, runtimeBudget, { defaultOperationTimeoutMs = 30000 } = {}) {
  if (!adapter || !runtimeBudget?.maxRuntimeMinutes) return adapter;
  return {
    ...adapter,
    ...(typeof adapter.search === 'function'
      ? {
          async search(query, options = {}) {
            runtimeBudget.throwIfExceeded('round-one-search');
            return adapter.search(query, applyRuntimeTimeout(options, runtimeBudget, {
              stage: 'round-one-search',
              defaultOperationTimeoutMs,
            }));
          },
        }
      : {}),
    ...(typeof adapter.fetchDetails === 'function'
      ? {
          async fetchDetails(post, options = {}) {
            runtimeBudget.throwIfExceeded('detail-fetch');
            return adapter.fetchDetails(post, applyRuntimeTimeout(options, runtimeBudget, {
              stage: 'detail-fetch',
              defaultOperationTimeoutMs,
            }));
          },
        }
      : {}),
    ...(typeof adapter.fetchAuthorActivity === 'function'
      ? {
          async fetchAuthorActivity(username, options = {}) {
            runtimeBudget.throwIfExceeded('author-deep-dive');
            return adapter.fetchAuthorActivity(username, applyRuntimeTimeout(options, runtimeBudget, {
              stage: 'author-deep-dive',
              defaultOperationTimeoutMs,
            }));
          },
        }
      : {}),
  };
}

export function createRuntimeAwareAnalyzer(llmAnalyzer, runtimeBudget, stage = 'analysis') {
  if (typeof llmAnalyzer !== 'function' || !runtimeBudget?.maxRuntimeMinutes) return llmAnalyzer;
  return async function runtimeAwareAnalyzer(payload) {
    runtimeBudget.throwIfExceeded(stage);
    return llmAnalyzer(payload);
  };
}

export async function listCompletedArtifacts(runDir) {
  const files = [];
  await walkFiles(runDir, runDir, files);
  return files
    .filter((filePath) => filePath !== RUNTIME_STATUS_FILENAME)
    .sort((left, right) => left.localeCompare(right));
}

export async function writeRuntimeStatus({
  runDir,
  outputRoot,
  runId,
  runtimeLimitMinutes,
  profile = '',
  transport = '',
  llmModel = '',
  status = 'timed_out',
  reason,
  startedAt,
  finishedAt,
  stage = '',
} = {}) {
  const resolvedRunId = normalizeRunId(runId);
  const resolvedRunDir = resolveRunDir({
    outputRoot: outputRoot ?? path.dirname(path.resolve(runDir)),
    runId: resolvedRunId,
    runDir,
  });
  const completedArtifacts = await listCompletedArtifacts(resolvedRunDir);
  const payload = {
    schema_version: '1.0.0',
    run_id: resolvedRunId,
    status,
    reason: String(reason ?? '').trim(),
    stage: stage || null,
    profile: profile || null,
    transport: transport || null,
    llm_model: llmModel || null,
    runtime_limit_minutes: runtimeLimitMinutes ?? null,
    started_at: startedAt ?? null,
    finished_at: finishedAt ?? new Date().toISOString(),
    completed_artifacts: completedArtifacts,
  };
  await fs.mkdir(resolvedRunDir, { recursive: true });
  await fs.writeFile(path.join(resolvedRunDir, RUNTIME_STATUS_FILENAME), `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return payload;
}

export async function executeRadarRun({
  options,
  repoRoot,
  environment = process.env,
  now = () => Date.now(),
  loadConfig = loadLightingConfig,
  createOpenCliAdapter: createOpenCliAdapterImpl = createOpenCliAdapter,
  createPublicJsonAdapter: createPublicJsonAdapterImpl = createPublicJsonAdapter,
  createLlmAnalyzer = createOpenAiCompatibleAnalyzer,
  runLightingRadarImpl = runLightingRadar,
} = {}) {
  if (!options) throw new Error('CLI options are required');
  if (!repoRoot) throw new Error('repoRoot is required');

  const selectedConfig = resolveProfileConfigPath({ profile: options.profile, config: options.config });
  const configPath = path.resolve(repoRoot, selectedConfig);
  const outputRoot = path.resolve(repoRoot, options.outputRoot || '.local/runs');
  const runId = normalizeRunId(options.runId || createRunId(new Date(normalizeNow(readNowValue(now)))));
  const runDir = resolveRunDir({ outputRoot, runId });
  const config = await loadConfig(configPath);
  const openCliPath = options.openCliPath ? path.resolve(repoRoot, options.openCliPath) : options.openCliPath;
  const transportName = selectTransportName({
    requested: options.transport,
    ci: Boolean(environment.CI),
    openCliPath,
  });
  const baseAdapter = transportName === 'opencli'
    ? createRuntimeBoundOpenCliAdapter({
        executablePath: openCliPath,
        createOpenCliAdapterImpl,
        runtimeBudget: createRuntimeBudget({
          maxRuntimeMinutes: options.maxRuntimeMinutes,
          now,
          defaultOperationTimeoutMs: config.transport?.timeout_ms ?? 30000,
        }),
      })
    : createPublicJsonAdapterImpl();
  const runtimeBudget = transportName === 'opencli' && baseAdapter.runtimeBudget
    ? baseAdapter.runtimeBudget
    : createRuntimeBudget({
        maxRuntimeMinutes: options.maxRuntimeMinutes,
        now,
        defaultOperationTimeoutMs: config.transport?.timeout_ms ?? 30000,
      });
  const adapter = createRuntimeAwareAdapter(baseAdapter, runtimeBudget, {
    defaultOperationTimeoutMs: config.transport?.timeout_ms ?? 30000,
  });
  const startedAt = new Date(normalizeNow(readNowValue(now))).toISOString();
  const previousValues = snapshotEnvironment(environment, [
    'RADAR_LLM_ENABLED',
    'RADAR_LLM_MODEL',
    'RADAR_MAX_RUNTIME_MINUTES',
  ]);

  try {
    if (options.maxRuntimeMinutes !== null && options.maxRuntimeMinutes !== undefined) {
      environment.RADAR_MAX_RUNTIME_MINUTES = String(options.maxRuntimeMinutes);
    }

    const llmModel = options.llmModel || environment.RADAR_LLM_MODEL || config.analysis?.llm?.default_model || '';
    const llmEnabled = environment.RADAR_LLM_ENABLED === '1'
      || Boolean(options.llmModel)
      || config.analysis?.llm?.enabled_by_default === true;

    if (options.llmModel) {
      environment.RADAR_LLM_MODEL = options.llmModel;
      environment.RADAR_LLM_ENABLED = '1';
    }

    let llmAnalyzer = null;
    if (llmEnabled) {
      llmAnalyzer = createRuntimeAwareAnalyzer(createLlmAnalyzer({
        baseUrl: environment.RADAR_LLM_BASE_URL,
        apiKey: environment.RADAR_LLM_API_KEY,
        model: llmModel,
      }), runtimeBudget, 'analysis');
    }

    const result = await runLightingRadarImpl({ config, adapter, runDir, runId, llmAnalyzer });
    const finishedAt = new Date(normalizeNow(readNowValue(now))).toISOString();
    if (options.maxRuntimeMinutes !== null && options.maxRuntimeMinutes !== undefined) {
      await writeRuntimeStatus({
        runDir,
        outputRoot,
        runId,
        runtimeLimitMinutes: options.maxRuntimeMinutes,
        profile: options.profile,
        transport: transportName,
        llmModel: llmModel || null,
        status: result.manifest.status,
        reason: `Run ${result.manifest.status} within the configured max runtime of ${options.maxRuntimeMinutes} minutes.`,
        startedAt,
        finishedAt,
        stage: 'verification',
      });
    }
    return {
      run_id: result.manifest.run_id,
      status: result.manifest.status,
      transport: result.manifest.transport,
      profile: options.profile || null,
      llm_model: llmModel || null,
      runtime_limit_minutes: options.maxRuntimeMinutes ?? null,
      counts: result.manifest.counts,
      run_dir: runDir,
      report: path.join(runDir, 'report.html'),
    };
  } catch (error) {
    const finishedAt = new Date(normalizeNow(readNowValue(now))).toISOString();
    if (options.maxRuntimeMinutes !== null && options.maxRuntimeMinutes !== undefined) {
      await writeRuntimeStatus({
        runDir,
        outputRoot,
        runId,
        runtimeLimitMinutes: options.maxRuntimeMinutes,
        profile: options.profile,
        transport: transportName,
        llmModel: options.llmModel || environment.RADAR_LLM_MODEL || config.analysis?.llm?.default_model || null,
        status: isRuntimeLimitError(error) ? 'timed_out' : 'failed',
        reason: error instanceof Error ? error.message : String(error),
        startedAt,
        finishedAt,
        stage: error?.stage ?? 'runtime',
      });
    }
    throw error;
  } finally {
    restoreEnvironment(environment, previousValues);
  }
}

function normalizeRunId(runId) {
  const normalized = String(runId ?? '').trim();
  if (!normalized) throw new Error('Invalid run id: value is required.');
  if (normalized.includes('/') || normalized.includes('\\') || normalized.includes('..')) {
    throw new Error(`Invalid run id: ${normalized}. Run IDs must not contain path separators or "..".`);
  }
  return normalized;
}

function resolveRunDir({ outputRoot, runId, runDir = null } = {}) {
  const resolvedOutputRoot = path.resolve(outputRoot);
  const resolvedRunId = normalizeRunId(runId);
  const expectedRunDir = path.resolve(resolvedOutputRoot, resolvedRunId);
  if (runDir === null || runDir === undefined || runDir === '') return expectedRunDir;
  const resolvedRunDir = path.resolve(runDir);
  if (resolvedRunDir !== expectedRunDir) {
    throw new Error(`runtime-status must stay inside outputRoot/runId: ${expectedRunDir}`);
  }
  return resolvedRunDir;
}

function createRuntimeBoundOpenCliAdapter({
  executablePath,
  createOpenCliAdapterImpl,
  runtimeBudget,
} = {}) {
  if (!runtimeBudget?.maxRuntimeMinutes) {
    return createOpenCliAdapterImpl({ executablePath });
  }
  const maxRuntimeMinutes = runtimeBudget.maxRuntimeMinutes;

  function buildAdapter(stage) {
    runtimeBudget.throwIfExceeded(stage);
    const remainingMs = Math.max(0, Math.floor(runtimeBudget.remainingMs()));
    if (remainingMs <= 0) {
      throw createRuntimeLimitError({ stage, maxRuntimeMinutes });
    }
    return createOpenCliAdapterImpl({
      executablePath,
      execImpl(file, args, options = {}) {
        return execFileWithinRuntimeBudget(file, args, {
          ...options,
          timeout: remainingMs,
        }, {
          stage,
          maxRuntimeMinutes,
        });
      },
    });
  }

  return {
    name: 'opencli',
    runtimeBudget,
    async search(query, options = {}) {
      return buildAdapter('round-one-search').search(query, options);
    },
    async fetchDetails(post, options = {}) {
      return buildAdapter('detail-fetch').fetchDetails(post, options);
    },
    async fetchAuthorActivity(username, options = {}) {
      return buildAdapter('author-deep-dive').fetchAuthorActivity(username, options);
    },
  };
}

function execFileWithinRuntimeBudget(file, args, options, { stage, maxRuntimeMinutes } = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout = '', stderr = '') => {
      if (!error) {
        resolve({ stdout, stderr });
        return;
      }
      if (error.code === 'ETIMEDOUT' || error.killed === true) {
        reject(createRuntimeLimitError({
          stage,
          maxRuntimeMinutes,
          cause: error,
        }));
        return;
      }
      error.stdout = stdout;
      error.stderr = stderr;
      reject(error);
    });
  });
}

async function walkFiles(rootDir, currentDir, files) {
  let entries = [];
  try {
    entries = await fs.readdir(currentDir, { withFileTypes: true });
  } catch (error) {
    if (error?.code === 'ENOENT') return;
    throw error;
  }
  for (const entry of entries) {
    const fullPath = path.join(currentDir, entry.name);
    if (entry.isDirectory()) {
      await walkFiles(rootDir, fullPath, files);
      continue;
    }
    const relativePath = path.relative(rootDir, fullPath).replace(/\\/g, '/');
    if (relativePath) files.push(relativePath);
  }
}

function normalizePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return fallback;
}

function applyRuntimeTimeout(options, runtimeBudget, { stage, defaultOperationTimeoutMs }) {
  const timeoutMs = runtimeBudget.capTimeout(options?.timeoutMs ?? defaultOperationTimeoutMs);
  if (timeoutMs <= 0) {
    throw createRuntimeLimitError({
      stage,
      maxRuntimeMinutes: runtimeBudget.maxRuntimeMinutes,
    });
  }
  return {
    ...(options ?? {}),
    timeoutMs,
  };
}

function snapshotEnvironment(environment, names) {
  return new Map(names.map((name) => [name, environment[name]]));
}

function restoreEnvironment(environment, previousValues) {
  for (const [name, value] of previousValues.entries()) {
    if (value === undefined) delete environment[name];
    else environment[name] = value;
  }
}

function readNowValue(now) {
  return typeof now === 'function' ? now() : now;
}

function normalizeNow(value) {
  if (value instanceof Date) return value.getTime();
  return Number(value);
}
