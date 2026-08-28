import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

const CHECKPOINT_SCHEMA_VERSION = '1.0.0';

export function hashStageInput(value) {
  return crypto.createHash('sha256').update(stableStringify(value)).digest('hex');
}

export async function readStageCheckpoint(runDir, stage, inputHash, schemaVersion) {
  const { metadataPath, payloadPath } = checkpointPaths(runDir, stage, inputHash);
  try {
    const metadata = JSON.parse(await fs.readFile(metadataPath, 'utf8'));
    if (
      metadata?.schema_version !== schemaVersion
      || metadata?.checkpoint_schema_version !== CHECKPOINT_SCHEMA_VERSION
      || metadata?.input_hash !== inputHash
      || metadata?.stage !== stage
      || metadata?.payload_file !== path.basename(payloadPath)
    ) {
      return null;
    }
    return JSON.parse(await fs.readFile(payloadPath, 'utf8'));
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

export async function writeStageCheckpoint(runDir, stage, inputHash, schemaVersion, value) {
  const { dirPath, metadataPath, payloadPath } = checkpointPaths(runDir, stage, inputHash);
  await fs.mkdir(dirPath, { recursive: true });
  await writeAtomicJson(payloadPath, value);
  await writeAtomicJson(metadataPath, {
    checkpoint_schema_version: CHECKPOINT_SCHEMA_VERSION,
    stage,
    input_hash: inputHash,
    schema_version: schemaVersion,
    payload_file: path.basename(payloadPath),
    written_at: new Date().toISOString(),
  });
  return payloadPath;
}

function checkpointPaths(runDir, stage, inputHash) {
  const safeStage = String(stage).replace(/[^a-z0-9._-]+/gi, '_');
  const safeHash = String(inputHash).replace(/[^a-f0-9]+/gi, '').toLowerCase();
  const dirPath = path.join(runDir, 'checkpoints', safeStage);
  return {
    dirPath,
    metadataPath: path.join(dirPath, `${safeHash}.meta.json`),
    payloadPath: path.join(dirPath, `${safeHash}.payload.json`),
  };
}

function stableStringify(value) {
  return JSON.stringify(normalizeForHash(value));
}

function normalizeForHash(value) {
  if (Array.isArray(value)) return value.map((entry) => normalizeForHash(entry));
  if (value && typeof value === 'object') {
    return Object.keys(value)
      .sort()
      .reduce((result, key) => {
        result[key] = normalizeForHash(value[key]);
        return result;
      }, {});
  }
  return value ?? null;
}

async function writeAtomicJson(filePath, value) {
  const tempPath = `${filePath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await fs.rm(filePath, { force: true });
  await fs.rename(tempPath, filePath);
}
