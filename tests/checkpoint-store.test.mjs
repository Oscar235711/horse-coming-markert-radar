import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  hashStageInput,
  readStageCheckpoint,
  writeStageCheckpoint,
} from '../src/checkpoint-store.mjs';

test('hashStageInput is stable across object key order', () => {
  const left = {
    query: 'headlight condensation',
    limits: { posts: 30, comments: 20 },
    subreddits: ['Cartalk', 'f150'],
  };
  const right = {
    subreddits: ['Cartalk', 'f150'],
    limits: { comments: 20, posts: 30 },
    query: 'headlight condensation',
  };

  assert.equal(hashStageInput(left), hashStageInput(right));
});

test('stage checkpoints are reused only for exact input hash and schema matches', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'checkpoint-store-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const inputA = { stage: 'quality', terms: ['condensation'], limit: 10 };
  const inputB = { stage: 'quality', terms: ['condensation', 'fogging'], limit: 10 };
  const payload = { results: [{ post_id: 'p1' }], failures: [] };

  const checkpointPath = await writeStageCheckpoint(
    runDir,
    'quality',
    hashStageInput(inputA),
    '2.0.0',
    payload,
  );

  assert.deepEqual(
    await readStageCheckpoint(runDir, 'quality', hashStageInput(inputA), '2.0.0'),
    payload,
  );
  assert.equal(
    await readStageCheckpoint(runDir, 'quality', hashStageInput(inputB), '2.0.0'),
    null,
  );
  assert.equal(
    await readStageCheckpoint(runDir, 'quality', hashStageInput(inputA), '2.1.0'),
    null,
  );

  const metadataPath = checkpointPath.replace(/\.payload\.json$/i, '.meta.json');
  const metadata = JSON.parse(await fs.readFile(metadataPath, 'utf8'));
  assert.equal(metadata.stage, 'quality');
  assert.equal(metadata.schema_version, '2.0.0');
  assert.equal(metadata.input_hash, hashStageInput(inputA));
});
