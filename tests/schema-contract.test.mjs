import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('normalized evidence, run manifest, and Audience Map schemas are tracked', async () => {
  const evidence = await schema('normalized-evidence.schema.json');
  const graph = await schema('audience-map.schema.json');
  const manifest = await schema('run-manifest.schema.json');

  assert.ok(evidence.required.includes('post'));
  assert.ok(evidence.properties.comments.items.required.includes('body_original'));
  assert.ok(graph.required.includes('nodes'));
  assert.deepEqual(graph.properties.edges.items.properties.source_type.enum, ['product']);
  assert.deepEqual(graph.properties.edges.items.properties.target_type.enum, ['community']);
  assert.ok(manifest.required.includes('status'));
});

async function schema(name) {
  return JSON.parse(await fs.readFile(path.join(repoRoot, 'schemas', name), 'utf8'));
}
