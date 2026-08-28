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
  assert.ok(manifest.required.includes('artifacts'));
  assert.ok(manifest.required.includes('persona_status'));
  assert.ok(manifest.properties.counts.required.includes('keyword_cloud_terms'));
  assert.ok(manifest.properties.counts.required.includes('candidate_signals'));
  assert.deepEqual(manifest.properties.artifacts.required, [
    'analysis',
    'evidence',
    'audience_map',
    'keyword_cloud',
    'opportunities',
    'personas',
    'quality_evidence',
    'excluded_evidence',
    'report',
    'optimization_backlog',
    'failures',
  ]);
  assert.equal(graph.properties.nodes.items.properties.entry_type.enum.includes('formal_opportunity'), true);
  assert.equal(graph.properties.nodes.items.properties.entry_type.enum.includes('adjacent_bundle'), true);
  assert.ok(graph.properties.filters.required.includes('entry_types'));
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
  const artifact = await schema('opportunity-artifact.schema.json');
  assert.deepEqual(opportunities.properties.opportunities.items.properties.opportunity_type.enum, [
    'validated_entry', 'emerging_product', 'adjacent_bundle',
  ]);
  assert.deepEqual(opportunities.$defs.score_components.required, [
    'qualified_demand',
    'existing_market_validation',
    'unresolved_entry_gap',
    'purchase_price_signals',
    'diversity',
    'adjacency_bundle_logic',
    'evidence_quality',
  ]);
  assert.deepEqual(opportunities.$defs.score_penalties.required, [
    'one_user_concentration',
    'one_community_concentration',
    'contextual_question_dominance',
    'missing_qualified_support',
    'non_sellable_concept',
    'total',
  ]);
  assert.deepEqual(opportunities.$defs.commercial.required, [
    'pricing_band',
    'margin_potential',
    'manufacturing_complexity',
    'shipping_complexity',
    'return_risk',
  ]);
  assert.ok(opportunities.$defs.opportunity.required.includes('threshold_check'));
  assert.ok(opportunities.$defs.opportunity.required.includes('qualified_evidence_ids'));
  assert.ok(opportunities.$defs.opportunity.required.includes('unique_user_count'));
  assert.ok(opportunities.$defs.opportunity.required.includes('community_count'));
  assert.ok(opportunities.$defs.opportunity.required.includes('competitor_signals'));
  assert.ok(opportunities.$defs.opportunity.required.includes('existing_product_signals'));
  assert.ok(opportunities.$defs.opportunity.required.includes('entry_gaps'));
  assert.equal(opportunities.$defs.opportunity.properties.unique_user_count.minimum, 0);
  assert.equal(opportunities.$defs.opportunity.properties.community_count.minimum, 0);
  assert.equal(opportunities.$defs.opportunity.properties.direct_experience_count.minimum, 0);
  assert.deepEqual(opportunities.$defs.competitor_signal.required, ['name', 'evidence_ids']);
  assert.deepEqual(opportunities.$defs.threshold_checks.required, [
    'qualified_evidence',
    'unique_users',
    'communities',
    'direct_experience',
    'contexts',
    'core_contexts',
    'score',
    'concrete_product',
    'existing_market',
    'entry_gap',
    'solution_validation',
  ]);
  assert.ok(opportunities.required.includes('pain_points'));
  assert.ok(opportunities.required.includes('candidate_signals'));
  assert.deepEqual(artifact.required, [
    'schema_version',
    'run_id',
    'generated_at',
    'opportunities',
    'candidate_signals',
    'competitors',
    'pain_points',
  ]);
  assert.equal(artifact.additionalProperties, false);
  assert.equal(artifact.properties.opportunities.items.$ref, '#/$defs/formal_opportunity');
  assert.equal(artifact.properties.candidate_signals.items.$ref, '#/$defs/candidate_signal');
  assert.equal(artifact.properties.pain_points.items.$ref, '#/$defs/pain_point');
  assert.deepEqual(artifact.$defs.formal_opportunity.required, [
    'id',
    'label',
    'category',
    'opportunity_type',
    'opportunity_score',
    'verdict',
    'evidence_ids',
    'qualified_evidence_ids',
    'communities',
    'fitment_tags',
    'pain_points',
    'solution_ideas',
    'claims',
    'why_not_done',
    'commercial',
    'competitor_signals',
    'existing_product_signals',
    'entry_gaps',
  ]);
  assert.deepEqual(artifact.$defs.candidate_signal.required, [
    'id',
    'label',
    'category',
    'opportunity_type',
    'threshold_check',
    'evidence_ids',
    'qualified_evidence_ids',
    'claims',
    'why_not_done',
  ]);
  assert.deepEqual(artifact.$defs.pain_point.required, [
    'id',
    'label',
    'evidence_ids',
    'communities',
    'evidence_count',
    'qualified_evidence_count',
    'unique_users',
    'fact_status',
    'related_opportunity_ids',
    'related_solution_ids',
  ]);
});

test('author activity schema is strict about retained payloads and self-declared kinds', async () => {
  const authorActivity = await schema('author-activity.schema.json');

  assert.deepEqual(authorActivity.required, [
    'schema_version',
    'username',
    'source_post_ids',
    'source_evidence_ids',
    'retained_count',
    'excluded_count',
    'limits',
    'retained_activity',
    'privacy_note',
  ]);
  assert.equal(authorActivity.properties.retained_activity.items.additionalProperties, false);
  assert.deepEqual(authorActivity.properties.retained_activity.items.required, [
    'id',
    'activity_id',
    'activity_type',
    'username',
    'author',
    'subreddit',
    'title',
    'body_original',
    'score',
    'created_at',
    'url',
    'source',
    'relevance_reasons',
    'quality',
    'product_concepts',
    'pain_points',
    'discovered_terms',
    'self_declared_context',
  ]);
  assert.deepEqual(authorActivity.properties.retained_activity.items.properties.self_declared_context.items.properties.kind.enum, [
    'age_band',
    'state',
    'budget',
    'vehicle',
    'diy_ability',
    'occupation',
  ]);
});

test('keyword candidate schema and exploratory search defaults are tracked', async () => {
  const keywordCandidates = await schema('keyword-candidates.schema.json');
  const pilot = await jsonFile(path.join(repoRoot, 'configs', 'automotive_lighting_us_pilot.json'));

  assert.deepEqual(keywordCandidates.required, [
    'schema_version',
    'run_id',
    'generated_at',
    'selected_terms',
    'candidates',
  ]);
  assert.equal(keywordCandidates.$defs.candidate.additionalProperties, false);
  assert.deepEqual(keywordCandidates.$defs.candidate.required, [
    'term',
    'normalized_term',
    'categories',
    'extraction_methods',
    'evidence_ids',
    'source_evidence_ids',
    'authors',
    'communities',
    'parent_formal_terms',
    'threads',
    'unique_user_count',
    'community_count',
    'purchase_signal_count',
    'pain_signal_count',
    'workaround_signal_count',
    'promotional_signal_count',
    'source_quality',
    'average_quality_weight',
    'score_breakdown',
    'penalties',
    'discovery_score',
    'status',
  ]);
  assert.deepEqual(keywordCandidates.$defs.score_breakdown.required, [
    'unique_users',
    'cross_community',
    'specificity',
    'purchase_intent',
    'pain_or_workaround',
    'anchor_cooccurrence',
    'novelty',
  ]);
  assert.deepEqual(keywordCandidates.$defs.penalties.required, [
    'one_user_dominance',
    'one_thread_dominance',
    'brand_only',
    'promotional_language',
    'generic_language',
    'excluded_evidence',
    'total',
  ]);
  assert.deepEqual(keywordCandidates.$defs.source_quality.required, [
    'high',
    'medium',
    'total',
  ]);
  assert.deepEqual(keywordCandidates.$defs.candidate.properties.status.enum, [
    'formal',
    'exploratory_used',
    'candidate_review',
    'rejected',
    'promoted_by_human',
  ]);
  assert.equal(pilot.limits.round_two_terms, 20);
  assert.equal(pilot.limits.round_two_posts_per_term, 10);
  assert.equal(pilot.limits.round_two_minimum_score, 65);
  assert.equal(pilot.limits.round_two_minimum_users, 2);
  assert.equal(pilot.limits.round_two_minimum_communities, 2);
});

test('keyword cloud schema keeps display weights, evidence backlinks, and offline filter metadata explicit', async () => {
  const keywordCloud = await schema('keyword-cloud.schema.json');

  assert.deepEqual(keywordCloud.required, [
    'schema_version',
    'run_id',
    'generated_at',
    'scope',
    'terms',
    'filters',
  ]);
  assert.deepEqual(keywordCloud.$defs.term.required, [
    'term',
    'normalized_term',
    'category',
    'status',
    'display_weight',
    'discovery_score',
    'unique_user_count',
    'community_count',
    'purchase_signal_count',
    'pain_signal_count',
    'average_quality_weight',
    'score_breakdown',
    'penalties',
    'evidence_ids',
    'source_evidence_ids',
    'communities',
    'parent_formal_terms',
    'related_product_ids',
    'representative_evidence',
  ]);
  assert.equal(keywordCloud.$defs.term.properties.display_weight.minimum, 1);
  assert.equal(keywordCloud.$defs.term.properties.display_weight.maximum, 100);
  assert.deepEqual(keywordCloud.$defs.term.properties.category.enum, [
    'product',
    'solution',
    'pain',
    'fitment',
    'competitor_brand',
    'use_case',
    'adjacent_product',
  ]);
  assert.deepEqual(keywordCloud.$defs.term.properties.status.enum, [
    'formal',
    'exploratory_used',
    'candidate_review',
    'rejected',
    'promoted_by_human',
  ]);
  assert.deepEqual(keywordCloud.$defs.representative_evidence.required, [
    'evidence_id',
    'url',
    'subreddit',
    'quote_original',
    'quality_band',
  ]);
  assert.deepEqual(keywordCloud.properties.filters.required, [
    'categories',
    'statuses',
    'minimum_score',
  ]);
});

test('persona artifact schema enforces aggregate-only demographics and representative traceability', async () => {
  const personas = await schema('user_profile.schema.json');
  const analysis = await schema('analysis.schema.json');

  assert.deepEqual(personas.required, [
    'schema_version',
    'status',
    'persona_status',
    'thresholds',
    'counts',
    'missing',
    'aggregate_context',
    'clusters',
    'privacy_note',
  ]);
  assert.equal(personas.$defs.representative_user.additionalProperties, false);
  assert.deepEqual(personas.$defs.representative_user.required, [
    'user_code',
    'public_username',
    'selection_score',
    'retained_activity_count',
    'observable_behaviors',
    'supporting_evidence_ids',
    'supporting_evidence_urls',
    'confidence',
    'privacy_note',
  ]);
  assert.equal(personas.$defs.representative_user.properties.age_band, undefined);
  assert.equal(personas.$defs.representative_user.properties.state, undefined);
  assert.equal(personas.$defs.representative_user.properties.supporting_evidence_ids.minItems, 3);
  assert.equal(personas.$defs.representative_user.properties.supporting_evidence_ids.maxItems, 3);
  assert.equal(personas.$defs.representative_user.properties.supporting_evidence_urls.minItems, 3);
  assert.equal(personas.$defs.representative_user.properties.supporting_evidence_urls.maxItems, 3);
  assert.equal(personas.$defs.cluster.properties.user_count.minimum, 12);
  assert.equal(personas.$defs.cluster.properties.representative_users.minItems, 3);
  assert.equal(personas.$defs.cluster.properties.representative_users.maxItems, 3);
  assert.deepEqual(personas.$defs.aggregate_context.required, [
    'age_bands',
    'states',
    'budget_signals',
  ]);
  assert.deepEqual(personas.$defs.cluster.required, [
    'id',
    'label',
    'user_count',
    'evidence_count',
    'signals',
    'product_interests',
    'vehicle_platforms',
    'purchase_criteria',
    'recurring_pain_points',
    'explored_solutions',
    'related_communities',
    'vocabulary',
    'aggregate_context',
    'representative_users',
  ]);
  assert.ok(analysis.required.includes('personas'));
  assert.match(String(analysis.properties.personas.$ref ?? ''), /user_profile\.schema\.json/i);
});

async function schema(name) {
  return JSON.parse(await fs.readFile(path.join(repoRoot, 'schemas', name), 'utf8'));
}

async function jsonFile(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}
