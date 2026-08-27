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

test('evidence-quality schema and universal rule/config contracts are tracked', async () => {
  const evidenceQuality = await schema('evidence-quality.schema.json');
  const rules = await jsonFile(path.join(repoRoot, 'configs', 'rules', 'universal_evidence_rules.json'));
  const pilot = await jsonFile(path.join(repoRoot, 'configs', 'automotive_lighting_us_pilot.json'));

  assert.deepEqual(evidenceQuality.required, [
    'evidence_role',
    'quality_band',
    'quality_score',
    'eligible',
    'hard_exclusion',
    'components',
    'penalties',
    'reason_codes',
  ]);
  assert.deepEqual(evidenceQuality.properties.evidence_role.enum, [
    'direct_experience',
    'qualified_practitioner',
    'contextual_demand',
    'market_observation',
    'weak',
    'noise',
  ]);
  assert.deepEqual(rules.component_caps, {
    first_person_or_practitioner: 20,
    product_specificity: 15,
    context: 15,
    observable_outcome: 20,
    purchase_signal: 10,
    diagnostic_detail: 10,
    corroboration: 5,
    engagement: 5,
  });
  assert.equal(pilot.market_rules.minimum_quality_score, 50);
  assert.ok(Array.isArray(pilot.market_rules.geography.non_target_signals));
});

test('opportunity schema limits formal opportunities to sellable product types', async () => {
  const opportunities = await schema('opportunities.schema.json');
  assert.deepEqual(opportunities.properties.opportunities.items.properties.opportunity_type.enum, [
    'validated_entry', 'emerging_product', 'adjacent_bundle',
  ]);
  assert.ok(opportunities.properties.opportunities.items.required.includes('score_components'));
  assert.ok(opportunities.properties.opportunities.items.required.includes('threshold_check'));
  assert.ok(opportunities.required.includes('pain_points'));
  assert.ok(opportunities.required.includes('candidate_signals'));
});

async function schema(name) {
  return JSON.parse(await fs.readFile(path.join(repoRoot, 'schemas', name), 'utf8'));
}

async function jsonFile(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}
