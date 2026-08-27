import test from 'node:test';
import assert from 'node:assert/strict';

import {
  aggregateSelfDeclaredContext,
  buildPersonas,
  evaluatePersonaEligibility,
} from '../src/persona-engine.mjs';

test('persona generation refuses insufficient global samples with explicit missing counts', () => {
  const fixture = makePersonaFixture({
    clusterSpecs: [
      { key: 'diy_led_upgrade', count: 30 },
      { key: 'housing_protection', count: 30 },
    ],
    evidencePerUser: 4,
  });
  const evidenceShort = [
    ...fixture.evidence.filter((_, index) => index % 4 === 0),
    ...fixture.evidence.filter((_, index) => index % 4 !== 0).slice(0, 139),
  ];

  const evidenceResult = evaluatePersonaEligibility(evidenceShort, fixture.authors);
  assert.equal(evidenceResult.status, 'insufficient_sample');
  assert.deepEqual(evidenceResult.missing, [
    { metric: 'qualified_evidence', required: 200, actual: 199 },
  ]);

  const removedUsers = new Set(fixture.authors.slice(-10).map((item) => item.username));
  const userResult = evaluatePersonaEligibility(
    fixture.evidence.filter((item) => !removedUsers.has(item.author)),
    fixture.authors,
  );
  assert.equal(userResult.status, 'insufficient_sample');
  assert.deepEqual(userResult.missing, [
    { metric: 'qualified_users', required: 60, actual: 50 },
  ]);

  const authorResult = evaluatePersonaEligibility(
    fixture.evidence,
    fixture.authors.slice(0, 29),
  );
  assert.equal(authorResult.status, 'insufficient_sample');
  assert.deepEqual(authorResult.missing, [
    { metric: 'deep_dive_authors', required: 30, actual: 29 },
  ]);
});

test('aggregateSelfDeclaredContext only emits cohort-safe aggregate age, state, and budget context', () => {
  const smallCohort = makePersonaFixture({
    clusterSpecs: [{ key: 'diy_led_upgrade', count: 9 }],
    evidencePerUser: 24,
  }).authors;
  const smallAggregate = aggregateSelfDeclaredContext(smallCohort, { minimumCohort: 10 });

  assert.deepEqual(smallAggregate.age_bands, []);
  assert.deepEqual(smallAggregate.states, []);
  assert.deepEqual(smallAggregate.budget_signals, []);

  const publishableCohort = makePersonaFixture({
    clusterSpecs: [{ key: 'diy_led_upgrade', count: 10 }],
    evidencePerUser: 20,
  }).authors;
  const publishableAggregate = aggregateSelfDeclaredContext(publishableCohort, { minimumCohort: 10 });

  assert.deepEqual(publishableAggregate.age_bands, [{ value: '25-34', count: 10 }]);
  assert.deepEqual(publishableAggregate.states, [{ value: 'Texas', count: 10 }]);
  assert.deepEqual(publishableAggregate.budget_signals, [{ value: 'under $120', count: 10 }]);
});

test('buildPersonas is deterministic, behavior-only, and keeps representative cards traceable without demographic fields', () => {
  const fixture = makePersonaFixture({
    clusterSpecs: [
      { key: 'diy_led_upgrade', count: 20, budget: 'under $120', state: 'Texas', ageBand: '25-34' },
      { key: 'housing_protection', count: 20, budget: 'under $200', state: 'California', ageBand: '35-44' },
      { key: 'truck_visibility_fixers', count: 20, budget: 'around $180', state: 'Florida', ageBand: '45-54' },
    ],
    evidencePerUser: 4,
  });

  const first = buildPersonas(fixture.evidence, fixture.authors, {});
  const second = buildPersonas(fixture.evidence, fixture.authors, {});

  assert.deepEqual(second, first);
  assert.equal(first.status, 'complete');
  assert.equal(first.persona_status, 'complete');
  assert.equal(first.counts.qualified_evidence, 240);
  assert.equal(first.counts.qualified_users, 60);
  assert.equal(first.clusters.length, 3);
  assert.deepEqual(first.clusters.map((item) => item.id), [
    'diy-led-upgrade',
    'housing-protection',
    'truck-visibility-fixers',
  ]);

  const diyCluster = first.clusters[0];
  assert.equal(diyCluster.user_count, 20);
  assert.deepEqual(diyCluster.aggregate_context.age_bands, [{ value: '25-34', count: 20 }]);
  assert.ok(diyCluster.signals.includes('DIY install preference'));
  assert.ok(diyCluster.purchase_criteria.includes('budget_sensitive'));
  assert.equal(diyCluster.representative_users.length, 3);
  assert.ok(diyCluster.representative_users.every((item) => item.supporting_evidence_urls.length >= 3));
  assert.ok(diyCluster.representative_users.every((item) => !('age_band' in item)));
  assert.ok(diyCluster.representative_users.every((item) => !('state' in item)));
  assert.ok(diyCluster.representative_users.every((item) => item.observable_behaviors.length > 0));
});

test('buildPersonas refuses pseudo-personas when a derived cluster misses the 12-user floor', () => {
  const fixture = makePersonaFixture({
    clusterSpecs: [
      { key: 'diy_led_upgrade', count: 11 },
      { key: 'housing_protection', count: 49 },
    ],
    evidencePerUser: 4,
  });

  const result = buildPersonas(fixture.evidence, fixture.authors, {});

  assert.equal(result.status, 'insufficient_sample');
  assert.equal(result.persona_status, 'insufficient_sample');
  assert.deepEqual(result.clusters, []);
  assert.deepEqual(result.missing, [
    {
      metric: 'cluster_members',
      required: 12,
      actual: 11,
      cluster_id: 'diy-led-upgrade',
      cluster_label: 'DIY LED Upgraders',
    },
  ]);
});

test('buildPersonas refuses pseudo-personas when a cluster lacks three representative users with three retained activities', () => {
  const fixture = makePersonaFixture({
    clusterSpecs: [{ key: 'diy_led_upgrade', count: 60 }],
    evidencePerUser: 4,
    representativeActivityCutoff: 2,
  });

  const result = buildPersonas(fixture.evidence, fixture.authors, {});

  assert.equal(result.status, 'insufficient_sample');
  assert.deepEqual(result.missing, [
    {
      metric: 'representative_users',
      required: 3,
      actual: 2,
      cluster_id: 'diy-led-upgrade',
      cluster_label: 'DIY LED Upgraders',
    },
  ]);
});

function makePersonaFixture({
  clusterSpecs,
  evidencePerUser,
  representativeActivityCutoff = 3,
}) {
  const authors = [];
  const evidence = [];
  let authorIndex = 0;

  for (const spec of clusterSpecs) {
    for (let localIndex = 0; localIndex < spec.count; localIndex += 1) {
      authorIndex += 1;
      const username = `${spec.key}-${String(localIndex + 1).padStart(2, '0')}`;
      const activityCount = localIndex < representativeActivityCutoff ? 4 : 2;
      authors.push(makeAuthor({
        username,
        key: spec.key,
        sequence: authorIndex,
        activityCount,
        budget: spec.budget,
        state: spec.state,
        ageBand: spec.ageBand,
      }));
      evidence.push(...makeEvidence({
        username,
        key: spec.key,
        count: evidencePerUser,
      }));
    }
  }

  return { authors, evidence };
}

function makeAuthor({
  username,
  key,
  sequence,
  activityCount,
  budget = 'under $120',
  state = 'Texas',
  ageBand = '25-34',
}) {
  const createdAt = new Date(Date.UTC(2026, 7, Math.max(1, 28 - sequence))).toISOString();
  const activities = [];
  for (let index = 0; index < activityCount; index += 1) {
    const kind = index === 0 ? 'post' : 'comment';
    const text = activityTextFor(key, budget, state, index);
    activities.push({
      id: `${username}-activity-${index + 1}`,
      activity_id: `${username}-activity-${index + 1}`,
      activity_type: kind,
      username,
      author: username,
      subreddit: subredditFor(key),
      title: kind === 'post' ? titleFor(key) : '',
      body_original: text,
      score: 80 - index,
      created_at: createdAt,
      url: `https://www.reddit.com/r/${subredditFor(key)}/comments/${username}/${index + 1}`,
      source: {
        transport: 'fixture',
        collected_at: createdAt,
      },
      relevance_reasons: ['product_context', 'purchase_behavior', 'installation_or_repair'],
      quality: {
        evidence_role: 'direct_experience',
        quality_band: 'high',
        quality_score: 84 - index,
        eligible: true,
        hard_exclusion: false,
        components: {},
        penalties: {},
        reason_codes: ['fixture'],
      },
      product_concepts: productConceptsFor(key),
      pain_points: painPointsFor(key),
      discovered_terms: discoveredTermsFor(key),
      self_declared_context: index === 0
        ? [
            { kind: 'age_band', value: ageBand, source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/r/${subredditFor(key)}/comments/${username}/1`, observed_at: createdAt },
            { kind: 'state', value: state, source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/r/${subredditFor(key)}/comments/${username}/1`, observed_at: createdAt },
            { kind: 'budget', value: budget, source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/r/${subredditFor(key)}/comments/${username}/1`, observed_at: createdAt },
            ...diyContextFor(key, username),
          ]
        : [...diyContextFor(key, username)],
    });
  }

  return {
    schema_version: '1.0.0',
    username,
    source_evidence_ids: [`source-${username}`],
    retained_count: activities.length,
    excluded_count: 0,
    limits: {
      requested_limit: activities.length,
      applied_after_utc: '2026-02-28T00:00:00.000Z',
      max_total_activities: 500,
    },
    retained_activity: activities,
    privacy_note: 'Only public, research-relevant automotive content is retained; no sensitive demographic attributes are inferred.',
  };
}

function makeEvidence({ username, key, count }) {
  return Array.from({ length: count }, (_, index) => ({
    id: `${username}-evidence-${index + 1}`,
    type: index === 0 ? 'post' : 'comment',
    post_id: `${username}-post`,
    author: username,
    subreddit: subredditFor(key),
    title: index === 0 ? titleFor(key) : '',
    body_original: activityTextFor(key, 'under $120', 'Texas', index),
    url: `https://www.reddit.com/r/${subredditFor(key)}/comments/${username}/e${index + 1}`,
    score: 50 - index,
    comment_count: 12,
    quality: {
      evidence_role: 'direct_experience',
      quality_band: index === 0 ? 'high' : 'medium',
      quality_score: index === 0 ? 82 : 64,
      eligible: true,
      hard_exclusion: false,
      components: {},
      penalties: {},
      reason_codes: ['fixture'],
    },
  }));
}

function activityTextFor(key, budget, state, index) {
  if (key === 'housing_protection') {
    return [
      `I live in ${state} and my budget is ${budget} for a condensation fix.`,
      'The headlight housing keeps fogging after rain so I am comparing vent kits and protective film.',
      'I replaced the assembly once and still need a sealing solution that lasts.',
      'I want a fix that avoids repeat condensation and saves another warranty swap.',
    ][index] ?? 'I am still comparing vent kits and protective film.';
  }
  if (key === 'truck_visibility_fixers') {
    return [
      `I live in ${state} and my budget is ${budget} for better night visibility on my truck.`,
      'I use my Silverado on dark roads and want a cleaner beam pattern without glare.',
      'I tried a projector-style upgrade but still need a dependable visibility fix.',
      'I care about reach, beam control, and durable parts for repeated highway driving.',
    ][index] ?? 'I need a better visibility setup for truck night driving.';
  }
  return [
    `I live in ${state} and my budget is ${budget} for an H11 LED upgrade on my F-150.`,
    'I install these myself and need a CANbus adapter so the bulbs stop flickering.',
    'Beam pattern and cutoff matter more than raw brightness when I do the swap.',
    'I keep testing DIY upgrade parts that fit well and do not cause glare.',
  ][index] ?? 'I want a DIY H11 LED setup with stable fitment.';
}

function titleFor(key) {
  if (key === 'housing_protection') return 'Protective film and vent kit options for recurring headlight condensation';
  if (key === 'truck_visibility_fixers') return 'Truck night visibility upgrade with better beam control';
  return 'DIY H11 LED upgrade with CANbus adapter and cleaner cutoff';
}

function subredditFor(key) {
  if (key === 'housing_protection') return 'projectcar';
  if (key === 'truck_visibility_fixers') return 'silverado';
  return 'f150';
}

function productConceptsFor(key) {
  if (key === 'housing_protection') return ['protective-headlight-film', 'headlight-vent-membrane-kit', 'headlight-assembly'];
  if (key === 'truck_visibility_fixers') return ['led-headlight-bulb-kit', 'projector-upgrade-kit'];
  return ['led-headlight-bulb-kit', 'canbus-adapter-kit'];
}

function painPointsFor(key) {
  if (key === 'housing_protection') return ['condensation', 'fitment'];
  if (key === 'truck_visibility_fixers') return ['glare', 'dim_output'];
  return ['flicker', 'glare'];
}

function discoveredTermsFor(key) {
  if (key === 'housing_protection') return ['protective film', 'vent kit', 'headlight assembly'];
  if (key === 'truck_visibility_fixers') return ['projector upgrade', 'beam pattern', 'night visibility'];
  return ['h11', 'canbus adapter', 'beam pattern'];
}

function diyContextFor(key, username) {
  if (key === 'housing_protection') {
    return [{ kind: 'vehicle', value: 'SUV', source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' }];
  }
  if (key === 'truck_visibility_fixers') {
    return [{ kind: 'vehicle', value: 'Silverado', source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' }];
  }
  return [
    { kind: 'vehicle', value: 'F-150', source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' },
    { kind: 'diy_ability', value: 'DIY', source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' },
  ];
}
