import test from 'node:test';
import assert from 'node:assert/strict';

import { buildKeywordCloud } from '../src/keyword-cloud.mjs';
import { createKeywordCloudInputs } from './fixtures/task-6-report.fixture.mjs';

test('keyword cloud weight uses unique qualified users and evidence quality instead of raw frequency alone', () => {
  const { candidates, evidence } = createKeywordCloudInputs();
  const cloud = buildKeywordCloud(candidates, evidence, { runId: 'keyword-cloud-run' });
  const byTerm = new Map(cloud.terms.map((term) => [term.term, term]));

  const protectiveFilm = byTerm.get('headlight protective film');
  const relayHarnessFix = byTerm.get('relay harness fix');

  assert.ok(protectiveFilm);
  assert.ok(relayHarnessFix);
  assert.equal(protectiveFilm.display_weight > relayHarnessFix.display_weight, true);
  assert.deepEqual(protectiveFilm.evidence_ids, ['comment-c1', 'post-p1']);
  assert.deepEqual(protectiveFilm.source_evidence_ids, ['comment-c1', 'post-p1']);
  assert.equal(protectiveFilm.average_quality_weight > relayHarnessFix.average_quality_weight, true);
});

test('keyword cloud emits deterministic categories, filters, and representative evidence backlinks from qualified records only', () => {
  const { candidates, evidence } = createKeywordCloudInputs();
  const cloud = buildKeywordCloud(candidates, evidence, { runId: 'keyword-cloud-run' });
  const protectiveFilm = cloud.terms.find((term) => term.term === 'headlight protective film');
  const relayHarnessFix = cloud.terms.find((term) => term.term === 'relay harness fix');

  assert.equal(cloud.scope.data_source, 'keyword_cloud.json');
  assert.deepEqual(cloud.filters.categories, ['adjacent_product', 'pain', 'product', 'solution']);
  assert.deepEqual(cloud.filters.statuses, ['candidate_review', 'exploratory_used']);
  assert.equal(cloud.filters.minimum_score, 0);
  assert.equal(protectiveFilm.category, 'adjacent_product');
  assert.deepEqual(protectiveFilm.communities, ['F150', 'MechanicAdvice']);
  assert.deepEqual(protectiveFilm.parent_formal_terms, ['headlight condensation']);
  assert.equal(protectiveFilm.representative_evidence.length, 2);
  assert.deepEqual(protectiveFilm.representative_evidence.map((item) => item.evidence_id), ['comment-c1', 'post-p1']);
  assert.equal(relayHarnessFix.representative_evidence.some((item) => item.evidence_id === 'noise-1'), false);
});
