import test from 'node:test';
import assert from 'node:assert/strict';

import { analyzeDetails, analyzeWithOptionalLlm } from '../src/radar-analysis.mjs';

const config = {
  market: { country: 'US' },
  keywords: { candidate_only_brands: ['SEALIGHT', 'Sylvania', 'Philips', 'AUXITO'] },
};

test('rule analysis keeps pain hotspots but does not promote thin pain or product mentions into opportunities', () => {
  const analysis = analyzeDetails(fixtureDetails(), config, { runId: 'analysis-run' });

  assert.equal(analysis.run_id, 'analysis-run');
  assert.equal(analysis.scope.country, 'US');
  assert.equal(analysis.metrics.posts_analyzed, 2);
  assert.equal(analysis.metrics.us_posts, 1);
  assert.equal(analysis.metrics.unknown_geography_posts, 1);
  assert.equal(analysis.opportunities.length, 0);
  assert.ok(analysis.candidate_signals.some((item) => item.id === 'led-headlight-bulb-kit'));
  assert.ok(analysis.pain_points.some((item) => item.id === 'flicker'));
  assert.ok(analysis.hotspots.communities.some((item) => item.name === 'MechanicAdvice'));
});

test('analysis separates facts, inferences, and unknown supply-chain fields', () => {
  const analysis = analyzeDetails(fixtureDetails(), config);
  const opportunity = analysis.candidate_signals.find((item) => item.id === 'led-headlight-bulb-kit');

  assert.ok(opportunity);
  assert.ok(opportunity.claims.facts.length > 0);
  assert.ok(opportunity.claims.inferences.length > 0);
  assert.ok(opportunity.claims.unknowns.includes('制造成本'));
  assert.deepEqual(opportunity.qualified_evidence_ids, []);
  assert.equal(opportunity.commercial.shipping_complexity.status, 'unknown');
  assert.equal(opportunity.commercial.return_risk.status, 'unknown');
});

test('analysis retains English evidence and excludes sensitive demographic inference', () => {
  const analysis = analyzeDetails(fixtureDetails(), config);
  const serialized = JSON.stringify(analysis);

  assert.ok(analysis.evidence.some((item) => item.quote_original.includes('flicker')));
  assert.ok(!serialized.includes('estimated_age'));
  assert.ok(!serialized.includes('estimated_income'));
  assert.ok(!serialized.includes('"age_band"'));
  assert.ok(!serialized.includes('"state"'));
  assert.ok(analysis.privacy_note.includes('public'));
});

test('brand and slang discoveries become suggestions without changing formal keywords', () => {
  const analysis = analyzeDetails(fixtureDetails(), config);

  assert.ok(analysis.configuration_suggestions.some((item) => item.term === 'AUXITO'));
  assert.ok(analysis.configuration_suggestions.every((item) => item.auto_apply === false));
});

test('optional LLM failure preserves rule analysis and records the fallback', async () => {
  const rules = analyzeDetails(fixtureDetails(), config);
  const result = await analyzeWithOptionalLlm(rules, async () => {
    throw new Error('provider timeout');
  });

  assert.equal(result.opportunities.length, rules.opportunities.length);
  assert.equal(result.analysis_engine.llm.status, 'failed');
  assert.match(result.analysis_engine.llm.error, /provider timeout/);
  assert.equal(result.analysis_engine.active_result, 'rules');
});

test('product concept rules recognize bulbs but do not turn housing condensation into an opportunity', () => {
  const details = [{
    post: {
      id: 'post-plural', post_id: 'plural', subreddit: 'f150', title: 'How to access my headlight bulbs',
      body_original: 'Texas F-150 with rectangular housings that may be a sealed unit.', score: 5, comment_count: 3,
      url: 'https://www.reddit.com/r/f150/comments/plural/x', geography: { status: 'us', confidence: 0.8 },
    },
    comments: [{ id: 'comment-plural', body_original: 'The LEDs are one complete assembly.', score: 1, url: 'https://www.reddit.com/r/f150/comments/plural/x/c1' }],
  }];

  const analysis = analyzeDetails(details, config);

  assert.ok(analysis.candidate_signals.some((item) => item.id === 'led-headlight-bulb-kit'));
  assert.ok(!analysis.opportunities.some((item) => /assembly|sealing|condensation/.test(item.id)));
});

test('pain extraction stays within the matched product context', () => {
  const details = [{
    post: {
      id: 'post-context', post_id: 'context', subreddit: 'f150', title: 'F-150 headlight housing condensation',
      body_original: 'Texas sealed housing has water inside.', score: 5, comment_count: 2,
      url: 'https://www.reddit.com/r/f150/comments/context/x', geography: { status: 'us', confidence: 0.8 },
    },
    comments: [{ id: 'comment-context', body_original: 'I also added an off-road light bar for camping.', score: 1, url: 'https://www.reddit.com/r/f150/comments/context/x/c1' }],
  }];

  const analysis = analyzeDetails(details, config);
  const auxiliary = analysis.candidate_signals.find((item) => item.id === 'auxiliary-light-kit');

  assert.ok(auxiliary);
  assert.ok(!auxiliary.pain_points.includes('进水/起雾'));
});

test('analysis emits insufficient persona status instead of pseudo-profiles when deep-dive data is missing', () => {
  const analysis = analyzeDetails(fixtureDetails(), config, { runId: 'persona-missing' });

  assert.equal(analysis.personas.status, 'insufficient_sample');
  assert.equal(analysis.personas.persona_status, 'insufficient_sample');
  assert.deepEqual(analysis.personas.clusters, []);
  assert.ok(analysis.personas.missing.some((item) => item.metric === 'qualified_evidence'));
  assert.ok(analysis.personas.missing.some((item) => item.metric === 'qualified_users'));
  assert.ok(analysis.personas.missing.some((item) => item.metric === 'deep_dive_authors'));
});

test('analysis integrates persona clusters from qualified evidence and retained author activity', () => {
  const details = fixturePersonaDetails();
  const analysis = analyzeDetails(details, config, {
    runId: 'persona-complete',
    authorActivity: fixturePersonaAuthors(),
  });

  assert.equal(analysis.personas.status, 'complete');
  assert.equal(analysis.personas.persona_status, 'complete');
  assert.equal(analysis.personas.clusters.length, 3);
  assert.ok(analysis.personas.clusters.every((item) => item.representative_users.length === 3));
  assert.ok(analysis.personas.clusters.every((item) => item.aggregate_context.age_bands.length > 0));
  assert.ok(analysis.personas.clusters.every((item) => item.representative_users.every((user) => !('age_band' in user))));
});

function fixtureDetails() {
  return [
    {
      post: {
        id: 'post-p1',
        post_id: 'p1',
        subreddit: 'MechanicAdvice',
        title: 'H11 LED headlight flicker and error code on my F-150',
        body_original: 'I am in Texas. The AUXITO bulb is bright but flickers. What should I buy under $100?',
        score: 32,
        comment_count: 18,
        url: 'https://www.reddit.com/r/MechanicAdvice/comments/p1/x',
        geography: { status: 'us', confidence: 0.8 },
      },
      comments: [
        {
          id: 'comment-c1',
          comment_id: 'c1',
          post_id: 'p1',
          author: 'helper',
          body_original: 'The CANbus adapter fixed the flicker, but the beam pattern still causes glare.',
          score: 20,
          url: 'https://www.reddit.com/r/MechanicAdvice/comments/p1/x/c1',
        },
      ],
    },
    {
      post: {
        id: 'post-p2',
        post_id: 'p2',
        subreddit: 'projectcar',
        title: 'Fog light condensation after install',
        body_original: 'The housing keeps fogging after rain and does not fit correctly.',
        score: 12,
        comment_count: 6,
        url: 'https://www.reddit.com/r/projectcar/comments/p2/x',
        geography: { status: 'unknown', confidence: 0 },
      },
      comments: [],
    },
  ];
}

function fixturePersonaDetails() {
  const groups = [
    { prefix: 'diy-led-upgrade', subreddit: 'f150', title: 'DIY H11 LED upgrade with CANbus adapter', body: 'I am in Texas. I installed these bulbs myself, but my F-150 still flickers and needs a beam pattern fix under $120.', comments: ['I added the adapter and my F-150 still flickers without the right harness.', 'I installed another bulb set and the cutoff improved, but fitment still needs work.', 'I tested a second adapter and it reduced flicker without adding extra glare.', 'I swapped the relay harness and the warning light finally cleared.', 'I bought another H11 pair and the brightness improved, but I still monitor glare.'] },
    { prefix: 'housing-protection', subreddit: 'projectcar', title: 'Recurring condensation fix with vent kit or protective film', body: 'I am in California. I replaced the housing once, but my budget is under $200 for a better headlight sealing solution.', comments: ['I installed protective film, but moisture still returns after rain.', 'I replaced the assembly and the leak improved for a week before condensation came back.', 'I tested vent kits after another leak and still need a longer-lasting sealing fix.', 'I sealed the back cover and the fogging dropped for two drives before returning.', 'I bought another membrane kit and it improved drainage, but water still gets in.'] },
    { prefix: 'truck-visibility-fixers', subreddit: 'silverado', title: 'Truck visibility upgrade with better beam control', body: 'I am in Florida and I tried a projector-style upgrade, but I still need better night visibility without glare.', comments: ['I installed the projector swap and improved reach a little.', 'I drove a highway loop after this upgrade and still need more durable parts with cleaner beam control.', 'I tested another setup after my latest install and it gave more reach without extra glare.', 'I replaced the bulbs again and the road signs lit up better, but the cutoff still needs work.', 'I bought a second harness and the beam stayed steadier on dark roads.'] },
  ];
  const details = [];
  let postSequence = 0;

  for (const group of groups) {
    for (let index = 1; index <= 20; index += 1) {
      postSequence += 1;
      const username = `${group.prefix}-${String(index).padStart(2, '0')}`;
      details.push({
        post: {
          id: `${username}-post`,
          post_id: `${username}-post`,
          author: username,
          subreddit: group.subreddit,
          title: `${group.title} case ${index}`,
          body_original: `${group.body} This is case ${index} after another install attempt.`,
          score: 30,
          comment_count: 5,
          url: `https://www.reddit.com/r/${group.subreddit}/comments/${username}/post`,
          geography: { status: 'us', confidence: 0.9 },
        },
        comments: group.comments.map((body, commentIndex) => ({
          id: `${username}-comment-${commentIndex + 1}`,
          comment_id: `${username}-comment-${commentIndex + 1}`,
          post_id: `${username}-post`,
          author: username,
          body_original: `${body} User case ${index}, note ${commentIndex + 1}.`,
          score: 8 - commentIndex,
          url: `https://www.reddit.com/r/${group.subreddit}/comments/${username}/c${commentIndex + 1}`,
        })),
      });
    }
  }

  return details;
}

function fixturePersonaAuthors() {
  const authors = [];
  const groups = [
    { prefix: 'diy-led-upgrade', subreddit: 'f150', state: 'Texas', ageBand: '25-34', budget: 'under $120', lines: ['I live in Texas and my budget is under $120 for an H11 LED upgrade on my F-150.', 'I install these myself and need a CANbus adapter so the bulbs stop flickering.', 'Beam pattern and cutoff matter more than raw brightness when I do the swap.', 'I keep testing DIY upgrade parts that fit well and do not cause glare.'], productConcepts: ['led-headlight-bulb-kit', 'canbus-adapter-kit'], painPoints: ['flicker', 'glare'], terms: ['h11', 'canbus adapter', 'beam pattern'] },
    { prefix: 'housing-protection', subreddit: 'projectcar', state: 'California', ageBand: '35-44', budget: 'under $200', lines: ['I live in California and my budget is under $200 for a condensation fix.', 'The headlight housing keeps fogging after rain so I am comparing vent kits and protective film.', 'I replaced the assembly once and still need a sealing solution that lasts.', 'I want a fix that avoids repeat condensation and saves another warranty swap.'], productConcepts: ['protective-headlight-film', 'headlight-vent-membrane-kit', 'headlight-assembly'], painPoints: ['condensation', 'fitment'], terms: ['protective film', 'vent kit', 'headlight assembly'] },
    { prefix: 'truck-visibility-fixers', subreddit: 'silverado', state: 'Florida', ageBand: '45-54', budget: 'around $180', lines: ['I live in Florida and my budget is around $180 for better night visibility on my truck.', 'I use my Silverado on dark roads and want a cleaner beam pattern without glare.', 'I tried a projector-style upgrade but still need a dependable visibility fix.', 'I care about reach, beam control, and durable parts for repeated highway driving.'], productConcepts: ['led-headlight-bulb-kit', 'projector-upgrade-kit'], painPoints: ['glare', 'dim_output'], terms: ['projector upgrade', 'beam pattern', 'night visibility'] },
  ];

  for (const group of groups) {
    for (let index = 1; index <= 20; index += 1) {
      const username = `${group.prefix}-${String(index).padStart(2, '0')}`;
      authors.push({
        schema_version: '1.0.0',
        username,
        source_evidence_ids: [`source-${username}`],
        retained_count: 4,
        excluded_count: 0,
        limits: {
          requested_limit: 4,
          applied_after_utc: '2026-02-28T00:00:00.000Z',
          max_total_activities: 500,
        },
        retained_activity: group.lines.map((line, lineIndex) => ({
          id: `${username}-activity-${lineIndex + 1}`,
          activity_id: `${username}-activity-${lineIndex + 1}`,
          activity_type: lineIndex === 0 ? 'post' : 'comment',
          username,
          author: username,
          subreddit: group.subreddit,
          title: lineIndex === 0 ? line : '',
          body_original: line,
          score: 40 - lineIndex,
          created_at: '2026-08-20T00:00:00.000Z',
          url: `https://www.reddit.com/r/${group.subreddit}/comments/${username}/${lineIndex + 1}`,
          source: { transport: 'fixture', collected_at: '2026-08-20T00:00:00.000Z' },
          relevance_reasons: ['product_context', 'purchase_behavior', 'installation_or_repair'],
          quality: {
            evidence_role: 'direct_experience',
            quality_band: 'high',
            quality_score: 80 - lineIndex,
            eligible: true,
            hard_exclusion: false,
            components: {},
            penalties: {},
            reason_codes: ['fixture'],
          },
          product_concepts: group.productConcepts,
          pain_points: group.painPoints,
          discovered_terms: group.terms,
          self_declared_context: lineIndex === 0
            ? [
                { kind: 'age_band', value: group.ageBand, source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' },
                { kind: 'state', value: group.state, source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' },
                { kind: 'budget', value: group.budget, source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' },
                ...(group.prefix === 'diy-led-upgrade'
                  ? [{ kind: 'diy_ability', value: 'DIY', source: 'self_declared', evidence_id: `${username}-activity-1`, permalink: `https://www.reddit.com/comments/${username}/1`, observed_at: '2026-08-20T00:00:00.000Z' }]
                  : []),
              ]
            : [],
        })),
        privacy_note: 'Only public, research-relevant automotive content is retained; no sensitive demographic attributes are inferred.',
      });
    }
  }

  return authors;
}
