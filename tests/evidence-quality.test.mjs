import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  applyEvidenceGate,
  classifyEvidence,
  loadUniversalEvidenceRules,
  normalizeEvidenceText,
} from '../src/evidence-quality.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const rulesPath = path.join(repoRoot, 'configs', 'rules', 'universal_evidence_rules.json');

test('direct experience receives a high auditable quality result', () => {
  const result = classifyEvidence({
    id: 'direct-1',
    author: 'owner',
    body_original: 'I installed H11 LEDs on my F-150 in Texas; they flickered until I added a CANbus adapter.',
    subreddit: 'f150',
    url: 'https://www.reddit.com/r/f150/comments/direct-1',
    score: 2,
  }, { market: { country: 'US' }, marketRules: { minimum_quality_score: 0 } });

  assert.equal(result.evidence_role, 'direct_experience');
  assert.equal(result.hard_exclusion, false);
  assert.equal(result.eligible, true);
  assert.equal(result.quality_band, 'high');
  assert.ok(result.quality_score >= 70);
  assert.ok(result.components.first_person_or_practitioner <= 20);
  assert.ok(result.components.product_specificity <= 15);
  assert.ok(result.components.context <= 15);
  assert.ok(result.components.observable_outcome <= 20);
  assert.ok(result.components.purchase_signal <= 10);
  assert.ok(result.components.diagnostic_detail <= 10);
  assert.ok(result.components.corroboration <= 5);
  assert.ok(result.components.engagement <= 5);
  assert.ok(result.reason_codes.includes('direct_experience'));
});

test('practitioner detail is separated from a generic recommendation', () => {
  const result = classifyEvidence({
    id: 'practitioner-1',
    author: 'reader123',
    body_original: 'Check the ground and CANbus adapter when an H11 LED flickers on a Silverado; if the adapter clears the warning light, the issue is usually the load signal.',
    subreddit: 'AskMechanics',
    url: 'https://www.reddit.com/r/AskMechanics/comments/practitioner-1',
    score: 4,
  }, { market: { country: 'US' } });

  assert.equal(result.evidence_role, 'qualified_practitioner');
  assert.equal(result.hard_exclusion, false);
  assert.ok(result.components.diagnostic_detail >= 5);
  assert.ok(result.reason_codes.includes('qualified_practitioner'));
});

test('self-declared identity alone does not elevate a generic recommendation to practitioner evidence', () => {
  const result = classifyEvidence({
    id: 'identity-only-1',
    author: 'shop_tech',
    body_original: 'As a mechanic, I would just buy brighter LED headlights for your Silverado.',
    subreddit: 'AskMechanics',
    url: 'https://www.reddit.com/r/AskMechanics/comments/identity-only-1',
    score: 9,
  }, { market: { country: 'US' } });

  assert.notEqual(result.evidence_role, 'qualified_practitioner');
  assert.ok(result.components.diagnostic_detail < 5);
});

test('detailed request without an outcome is contextual demand', () => {
  const result = classifyEvidence({
    id: 'demand-1',
    author: 'buyer',
    title: 'What should I buy for my Tacoma?',
    body_original: 'I need an H11 LED headlight upgrade for night driving in Washington, preferably under $100, and I have limited space behind the factory dust cap.',
    subreddit: 'ToyotaTacoma',
    url: 'https://www.reddit.com/r/ToyotaTacoma/comments/demand-1',
    score: 1,
  }, { market: { country: 'US' } });

  assert.equal(result.evidence_role, 'contextual_demand');
  assert.equal(result.hard_exclusion, false);
  assert.equal(result.eligible, false);
  assert.ok(['weak', 'medium'].includes(result.quality_band));
  assert.ok(result.reason_codes.includes('contextual_demand'));
});

test('weak reaction stays out of the evidence library', () => {
  const result = classifyEvidence({
    id: 'weak-1',
    author: 'reader',
    body_original: 'LED headlights are nice.',
    subreddit: 'Automotive',
    url: 'https://www.reddit.com/r/Automotive/comments/weak-1',
    score: 2000,
  }, { market: { country: 'US' } });

  assert.equal(result.evidence_role, 'weak');
  assert.equal(result.eligible, false);
  assert.equal(result.hard_exclusion, false);
  assert.ok(result.components.engagement <= 5);
  assert.ok(result.reason_codes.includes('low_information_density'));
});

test('quality score stays exactly recomputable from components minus penalties', () => {
  const result = classifyEvidence({
    id: 'score-1',
    author: 'buyer',
    title: 'What should I buy for my Tacoma?',
    body_original: 'I need an H11 LED headlight upgrade for night driving in Washington, preferably under $100, and I have limited space behind the factory dust cap.',
    subreddit: 'ToyotaTacoma',
    url: 'https://www.reddit.com/r/ToyotaTacoma/comments/score-1',
    score: 1,
  }, { market: { country: 'US' } });

  const recomputed = Object.values(result.components).reduce((sum, value) => sum + value, 0) - result.penalties.total;
  assert.equal(result.quality_score, Math.max(0, Math.min(100, Math.round(recomputed))));
});

test('quoted recommendation without personal context receives the quotation penalty', () => {
  const result = classifyEvidence({
    id: 'quote-1',
    author: 'reader',
    body_original: '"Buy these LED headlights" was the entire advice in the thread.',
    subreddit: 'Automotive',
    url: 'https://www.reddit.com/r/Automotive/comments/quote-1',
    score: 3,
  }, { market: { country: 'US' } });

  assert.equal(result.penalties.quotation_without_personal_context, 5);
  assert.ok(result.quality_score < Object.values(result.components).reduce((sum, value) => sum + value, 0));
});

test('hard exclusions cannot be rescued by engagement or market overrides', () => {
  const result = applyEvidenceGate([
    { id: 'bot', author: 'AutoModerator', body_original: 'Community rules', score: 999 },
    { id: 'real', author: 'owner', body_original: 'I installed H11 LEDs on my F-150; they flickered until I added a CANbus adapter.', score: 2 },
  ], { market: { country: 'US' }, marketRules: { minimum_quality_score: 0 } });

  assert.deepEqual(result.qualified.map(item => item.id), ['real']);
  assert.equal(result.excluded[0].quality.hard_exclusion, true);
  assert.equal(result.excluded[0].quality.evidence_role, 'noise');
  assert.equal(result.distribution.noise, 1);
  assert.equal(result.distribution.high + result.distribution.medium, 1);
});

test('affiliate, URL-only, duplicate, and off-market records receive distinct hard exclusions', () => {
  const result = applyEvidenceGate([
    { id: 'affiliate', author: 'seller', body_original: 'Use my coupon code BEAM20 and buy through my affiliate link for the best LED bulbs.', subreddit: 'Automotive', score: 500 },
    { id: 'url-only', author: 'reader', body_original: 'https://example.com/headlights.jpg', subreddit: 'Automotive', score: 500 },
    { id: 'first-copy', author: 'owner', body_original: 'I installed an H11 LED bulb on my Tacoma and it fixed the flicker.', subreddit: 'ToyotaTacoma', score: 1 },
    { id: 'near-copy', author: 'owner2', body_original: 'I installed an H11 LED bulb on my Tacoma, and it fixed the flicker!', subreddit: 'ToyotaTacoma', score: 999 },
    { id: 'off-market', author: 'owner', body_original: 'I installed an H11 LED on my UK car for the MOT and it failed.', subreddit: 'CarTalkUK', score: 999 },
  ], { market: { country: 'US' } });

  const byId = new Map(result.excluded.map(item => [item.id, item.quality]));
  assert.ok(byId.get('affiliate').hard_exclusion);
  assert.ok(byId.get('affiliate').reason_codes.includes('affiliate_or_coupon'));
  assert.ok(byId.get('url-only').reason_codes.includes('url_only'));
  assert.ok(byId.get('near-copy').reason_codes.includes('duplicate_or_near_duplicate'));
  assert.ok(byId.get('off-market').reason_codes.includes('off_market'));
  assert.ok(result.qualified.some(item => item.id === 'first-copy'));
});

test('near-duplicate normalization ignores case, punctuation, and URL noise', () => {
  const first = normalizeEvidenceText('I installed H11 LEDs on my F-150! https://example.com/a');
  const second = normalizeEvidenceText('i installed h11 leds on my f 150');
  assert.equal(first, second);
});

test('market overrides can tighten thresholds but cannot disable universal hard exclusions', () => {
  const bot = classifyEvidence({ id: 'bot-2', author: 'some_bot', body_original: 'I installed H11 LEDs on my F-150 and they worked.', score: 100000 }, {
    market: { country: 'US' },
    marketRules: { minimum_quality_score: 95, hard_exclusions: { bots: false } },
  });
  assert.equal(bot.hard_exclusion, true);
  assert.equal(bot.eligible, false);

  const real = classifyEvidence({ id: 'real-2', author: 'owner', body_original: 'I installed H11 LEDs on my F-150 and they worked after I adjusted the beam.', score: 1 }, {
    market: { country: 'US' },
    marketRules: { minimum_quality_score: 95 },
  });
  assert.equal(real.hard_exclusion, false);
  assert.equal(real.eligible, false);
  assert.ok(real.quality_score < 95);
});

test('gate preserves records, classifies each record once, and reports role/band distributions', () => {
  const records = [
    { id: 'one', author: 'a', body_original: 'I bought a 9005 LED headlight for my Silverado in Ohio; it is brighter than stock.', subreddit: 'Silverado', score: 3 },
    { id: 'two', author: 'b', body_original: 'Headlight bulbs are available at most auto parts stores.', subreddit: 'Automotive', score: 3 },
    { id: 'three', author: 'c', body_original: 'same', subreddit: 'Automotive', score: 99 },
  ];
  const result = applyEvidenceGate(records, { market: { country: 'US' } });

  assert.equal(result.qualified.length + result.excluded.length, records.length);
  assert.deepEqual(result.qualified[0].id, 'one');
  assert.equal(result.distribution.by_role.direct_experience, 1);
  assert.equal(result.distribution.by_role.market_observation, 1);
  assert.equal(result.distribution.by_role.noise, 1);
  assert.equal(result.distribution.by_quality_band.noise, 1);
});

test('tracked universal rules expose the documented caps and bands', async () => {
  const rules = loadUniversalEvidenceRules(rulesPath);

  assert.equal(rules.schema_version, '1.0.0');
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
  assert.deepEqual(rules.quality_bands, { high: [70, 100], medium: [50, 69], weak: [30, 49], noise: [0, 29] });
});

test('universal rules loader rejects malformed tracked rule files', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'evidence-rules-'));
  const baseRules = loadUniversalEvidenceRules(rulesPath);
  const missingComponentCaps = path.join(directory, 'missing-component-caps.json');
  const missingHardExclusions = path.join(directory, 'missing-hard-exclusions.json');
  const missingRoles = path.join(directory, 'missing-roles.json');
  const missingPenalties = path.join(directory, 'missing-penalties.json');

  const withoutComponentCaps = { ...baseRules };
  const withoutHardExclusions = { ...baseRules };
  const withoutRoles = { ...baseRules };
  const withoutPenalties = { ...baseRules };

  delete withoutComponentCaps.component_caps;
  delete withoutHardExclusions.hard_exclusions;
  delete withoutRoles.roles;
  delete withoutPenalties.penalties;

  await fs.writeFile(missingComponentCaps, JSON.stringify(withoutComponentCaps), 'utf8');
  await fs.writeFile(missingHardExclusions, JSON.stringify(withoutHardExclusions), 'utf8');
  await fs.writeFile(missingRoles, JSON.stringify(withoutRoles), 'utf8');
  await fs.writeFile(missingPenalties, JSON.stringify(withoutPenalties), 'utf8');

  assert.throws(() => loadUniversalEvidenceRules(missingComponentCaps), /component_caps/i);
  assert.throws(() => loadUniversalEvidenceRules(missingHardExclusions), /hard_exclusions/i);
  assert.throws(() => loadUniversalEvidenceRules(missingRoles), /roles/i);
  assert.throws(() => loadUniversalEvidenceRules(missingPenalties), /penalties/i);
  await fs.rm(directory, { recursive: true, force: true });
});
