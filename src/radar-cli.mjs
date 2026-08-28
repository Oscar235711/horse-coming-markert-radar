export const DEFAULT_CONFIG_PATH = 'configs/automotive_lighting_us_pilot.json';

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
