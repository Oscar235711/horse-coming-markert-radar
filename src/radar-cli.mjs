export function parseCliArgs(argv) {
  const options = {
    config: 'configs/automotive_lighting_us_pilot.json',
    transport: 'auto',
    runId: '',
    outputRoot: '.local/runs',
    openCliPath: process.env.RADAR_OPENCLI_EXE ?? '',
    help: false,
  };
  const valueFlags = new Map([
    ['--config', 'config'],
    ['--transport', 'transport'],
    ['--run-id', 'runId'],
    ['--output-root', 'outputRoot'],
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
  if (!['auto', 'opencli', 'public-json'].includes(options.transport)) {
    throw new Error(`Unsupported transport: ${options.transport}`);
  }
  return options;
}

export function selectTransportName({ requested = 'auto', ci = false, openCliPath = '' } = {}) {
  if (requested !== 'auto') return requested;
  if (ci) return 'public-json';
  return openCliPath ? 'opencli' : 'public-json';
}

export function createRunId(now = new Date()) {
  return `lighting-us-${now.toISOString().replace(/[:.]/g, '-').replace('Z', '')}`;
}
