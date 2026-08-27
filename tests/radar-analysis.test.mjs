import test from 'node:test';
import assert from 'node:assert/strict';

import { analyzeDetails, analyzeWithOptionalLlm } from '../src/radar-analysis.mjs';

const config = {
  market: { country: 'US' },
  keywords: { candidate_only_brands: ['SEALIGHT', 'Sylvania', 'Philips', 'AUXITO'] },
};

test('rule analysis creates evidence-backed lighting opportunities and market hotspots', () => {
  const analysis = analyzeDetails(fixtureDetails(), config, { runId: 'analysis-run' });

  assert.equal(analysis.run_id, 'analysis-run');
  assert.equal(analysis.scope.country, 'US');
  assert.equal(analysis.metrics.posts_analyzed, 2);
  assert.equal(analysis.metrics.us_posts, 1);
  assert.equal(analysis.metrics.unknown_geography_posts, 1);
  assert.ok(analysis.opportunities.some((item) => item.id === 'product-led-headlight-upgrade'));
  const led = analysis.opportunities.find((item) => item.id === 'product-led-headlight-upgrade');
  assert.ok(led.evidence_ids.length >= 1);
  assert.ok(led.communities.includes('MechanicAdvice'));
  assert.ok(led.fitment_tags.includes('H11'));
  assert.ok(led.pain_points.includes('闪烁/故障码'));
  assert.ok(led.opportunity_score >= 1 && led.opportunity_score <= 100);
  assert.ok(analysis.hotspots.communities.some((item) => item.name === 'MechanicAdvice'));
});

test('analysis separates facts, inferences, and unknown supply-chain fields', () => {
  const analysis = analyzeDetails(fixtureDetails(), config);
  const opportunity = analysis.opportunities[0];

  assert.ok(opportunity.claims.facts.length > 0);
  assert.ok(opportunity.claims.inferences.length > 0);
  assert.ok(opportunity.claims.unknowns.includes('制造成本'));
  assert.equal(opportunity.commercial.shipping_complexity.status, 'unknown');
  assert.equal(opportunity.commercial.return_risk.status, 'inference');
});

test('analysis retains English evidence and excludes sensitive demographic inference', () => {
  const analysis = analyzeDetails(fixtureDetails(), config);
  const serialized = JSON.stringify(analysis);

  assert.ok(analysis.evidence.some((item) => item.quote_original.includes('flicker')));
  assert.ok(!serialized.includes('estimated_age'));
  assert.ok(!serialized.includes('estimated_income'));
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

test('product concept rules recognize plural bulb and housing language', () => {
  const details = [{
    post: {
      id: 'post-plural', post_id: 'plural', subreddit: 'f150', title: 'How to access my headlight bulbs',
      body_original: 'Texas F-150 with rectangular housings that may be a sealed unit.', score: 5, comment_count: 3,
      url: 'https://www.reddit.com/r/f150/comments/plural/x', geography: { status: 'us', confidence: 0.8 },
    },
    comments: [{ id: 'comment-plural', body_original: 'The LEDs are one complete assembly.', score: 1, url: 'https://www.reddit.com/r/f150/comments/plural/x/c1' }],
  }];

  const analysis = analyzeDetails(details, config);

  assert.ok(analysis.opportunities.some((item) => item.id === 'product-led-headlight-upgrade'));
  assert.ok(analysis.opportunities.some((item) => item.id === 'product-headlight-assembly'));
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
  const auxiliary = analysis.opportunities.find((item) => item.id === 'product-auxiliary-light');

  assert.ok(auxiliary);
  assert.ok(!auxiliary.pain_points.includes('进水/起雾'));
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
