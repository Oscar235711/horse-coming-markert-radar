import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('dsv4pro enrichment schema stays patch-only and citation-driven', async () => {
  const enrichment = JSON.parse(
    await fs.readFile(path.join(repoRoot, 'schemas', 'dsv4pro-enrichment.schema.json'), 'utf8'),
  );

  assert.equal(enrichment.additionalProperties, false);
  assert.deepEqual(Object.keys(enrichment.properties).sort(), [
    'candidate_signals',
    'competitors',
    'executive_summary',
    'opportunities',
    'seller_verdict',
  ]);
  assert.deepEqual(enrichment.$defs.update.required, ['id']);
  assert.equal(enrichment.$defs.update.additionalProperties, false);
  assert.deepEqual(enrichment.$defs.cited_text.required, ['text', 'evidence_ids']);
  assert.equal(enrichment.$defs.cited_text.properties.evidence_ids.minItems, 1);
  assert.equal(enrichment.$defs.why_not_done.additionalProperties, false);
  assert.equal(enrichment.$defs.competitor.required.includes('evidence_ids'), true);
});
