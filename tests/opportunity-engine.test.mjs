import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildOpportunityCandidates,
  classifyOpportunities,
  extractPainRecords,
} from '../src/opportunity-engine.mjs';

const config = {
  opportunity_engine: {
    concepts: [
      { id: 'led-bulb-kit', label: 'LED bulb kit', category: 'lighting', patterns: ['led bulb', 'headlight upgrade'], opportunity_type: 'validated_entry' },
      { id: 'vent-membrane-kit', label: 'Vent membrane kit', category: 'repair-accessory', patterns: ['vent membrane kit', 'breather vent'], opportunity_type: 'emerging_product' },
      { id: 'protective-headlight-film', label: 'Protective headlight film', category: 'protection', patterns: ['headlight film', 'protective film'], opportunity_type: 'adjacent_bundle' },
    ],
    pain_patterns: { condensation: ['condensation', 'fogging', 'moisture'] },
    competitor_terms: ['Lasfit', 'AUXITO'],
    thresholds: {
      validated_entry: { unique_users: 3, communities: 2, direct_experience: 2, score: 30 },
      emerging_product: { unique_users: 3, contexts: 2, score: 30 },
      adjacent_bundle: { unique_users: 3, core_contexts: 2, score: 30 },
    },
  },
};

test('condensation remains a pain and never becomes a product opportunity by itself', () => {
  const evidence = [
    evidenceRecord('pain-1', 'u1', 'f150', 'My headlight housing has condensation and moisture.', 'direct_experience'),
    evidenceRecord('pain-2', 'u2', 'MechanicAdvice', 'The assembly keeps fogging after rain.', 'direct_experience'),
  ];
  const pains = extractPainRecords(evidence, config);
  const result = classifyOpportunities(buildOpportunityCandidates(evidence, pains, config), config);

  assert.equal(pains[0].id, 'condensation');
  assert.equal(result.opportunities.some((item) => /condensation|assembly|sealing/i.test(item.id)), false);
  assert.equal(result.opportunities.length, 0);
});

test('classifies only concrete sellable concepts into the three allowed opportunity types', () => {
  const evidence = [
    evidenceRecord('v1', 'u1', 'f150', 'I bought an AUXITO LED bulb kit; it is brighter but the fitment is poor.', 'direct_experience'),
    evidenceRecord('v2', 'u2', 'MechanicAdvice', 'I installed an LED bulb kit and returned it because the beam pattern was bad.', 'direct_experience'),
    evidenceRecord('v3', 'u3', 'f150', 'Lasfit already sells this headlight upgrade, but I need better support.', 'market_observation'),
    evidenceRecord('e1', 'u4', 'projectcar', 'I made a breather vent workaround; I want a vent membrane kit.', 'direct_experience'),
    evidenceRecord('e2', 'u5', 'MechanicAdvice', 'A vent membrane kit would replace my DIY moisture workaround.', 'contextual_demand'),
    evidenceRecord('e3', 'u6', 'projectcar', 'I tried a vent membrane kit prototype for recurring fogging.', 'direct_experience'),
    evidenceRecord('a1', 'u7', 'f150', 'I added protective headlight film with my LED bulb install.', 'direct_experience'),
    evidenceRecord('a2', 'u8', 'CarModification', 'I bought headlight film as protection after an upgrade.', 'direct_experience'),
    evidenceRecord('a3', 'u9', 'f150', 'Protective film is an easy add-on to a headlight upgrade.', 'market_observation'),
  ];
  const result = classifyOpportunities(
    buildOpportunityCandidates(evidence, extractPainRecords(evidence, config), config),
    config,
  );

  assert.deepEqual(new Set(result.opportunities.map((item) => item.opportunity_type)), new Set([
    'validated_entry', 'emerging_product', 'adjacent_bundle',
  ]));
  assert.ok(result.opportunities.every((item) => item.evidence_ids.length >= 3));
  assert.ok(result.opportunities.every((item) => item.score_components && item.threshold_check));
  for (const item of result.opportunities) {
    assert.equal(item.opportunity_score, Object.values(item.score_components).reduce((sum, value) => sum + value, 0) - item.score_penalties.total);
  }
  assert.ok(result.competitors.some((item) => item.name === 'AUXITO'));
});

test('under-threshold concrete concepts remain candidate signals with failed gates', () => {
  const evidence = [evidenceRecord('thin-1', 'solo', 'f150', 'I installed a protective headlight film.', 'direct_experience')];
  const result = classifyOpportunities(
    buildOpportunityCandidates(evidence, extractPainRecords(evidence, config), config),
    config,
  );

  assert.equal(result.opportunities.length, 0);
  assert.equal(result.candidate_signals[0].id, 'protective-headlight-film');
  assert.equal(result.candidate_signals[0].threshold_check.passed, false);
  assert.ok(result.candidate_signals[0].threshold_check.failures.includes('unique_users'));
});

test('pain-theme labels like headlight assembly sealing optimization never qualify as formal opportunities', () => {
  const speculativeConfig = {
    opportunity_engine: {
      ...config.opportunity_engine,
      concepts: [
        ...config.opportunity_engine.concepts,
        {
          id: 'headlight-assembly-sealing-optimization',
          label: 'Headlight assembly sealing optimization',
          category: 'assembly',
          patterns: ['headlight assembly', 'sealing optimization', 'condensation'],
          opportunity_type: 'validated_entry',
        },
      ],
    },
  };
  const evidence = [
    evidenceRecord('assembly-1', 'u1', 'f150', 'My headlight assembly still has condensation after resealing.', 'direct_experience'),
    evidenceRecord('assembly-2', 'u2', 'MechanicAdvice', 'I need a better sealing fix for my headlight housing.', 'contextual_demand'),
    evidenceRecord('assembly-3', 'u3', 'projectcar', 'This headlight assembly fogging issue keeps coming back.', 'market_observation'),
  ];
  const result = classifyOpportunities(
    buildOpportunityCandidates(evidence, extractPainRecords(evidence, speculativeConfig), speculativeConfig),
    speculativeConfig,
  );

  assert.ok(!result.opportunities.some((item) => item.id === 'headlight-assembly-sealing-optimization'));
  const blocked = result.candidate_signals.find((item) => item.id === 'headlight-assembly-sealing-optimization');
  assert.ok(blocked);
  assert.ok(blocked.threshold_check.failures.includes('concrete_product'));
});

test('contextual demand cannot count as direct experience or prove product performance', () => {
  const evidence = [
    evidenceRecord('q1', 'u1', 'f150', 'Would a vent membrane kit stop condensation?', 'contextual_demand'),
    evidenceRecord('q2', 'u2', 'projectcar', 'I need a vent membrane kit for fogging.', 'contextual_demand'),
    evidenceRecord('q3', 'u3', 'MechanicAdvice', 'Which vent membrane kit works?', 'contextual_demand'),
  ];
  const result = classifyOpportunities(
    buildOpportunityCandidates(evidence, extractPainRecords(evidence, config), config),
    config,
  );

  const candidate = result.candidate_signals[0];
  assert.equal(candidate.direct_experience_count, 0);
  assert.ok(candidate.claims.facts.every((fact) => !/works|performance|solves/i.test(fact)));
});

function evidenceRecord(id, author, subreddit, body, role) {
  return {
    id,
    author,
    subreddit,
    body_original: body,
    url: `https://www.reddit.com/r/${subreddit}/comments/p/${id}`,
    geography: 'us',
    quality: {
      eligible: !['weak', 'noise'].includes(role),
      evidence_role: role,
      quality_band: role === 'contextual_demand' ? 'medium' : 'high',
      quality_score: role === 'contextual_demand' ? 55 : 80,
    },
  };
}
