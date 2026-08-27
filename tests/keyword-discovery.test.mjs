import test from 'node:test';
import assert from 'node:assert/strict';

import {
  extractKeywordCandidates,
  scoreKeywordCandidates,
  selectRoundTwoTerms,
} from '../src/keyword-discovery.mjs';

const config = {
  keywords: {
    anchors: [
      'headlight bulb',
      'led headlight bulb',
      'headlight bulb replacement',
      'dim headlights',
      'headlight upgrade',
      'halogen headlight bulb',
      'hid headlight bulb',
      'h11 headlight bulb',
      '9005 headlight bulb',
      '9006 headlight bulb',
      'h7 headlight bulb',
      'h4 headlight bulb',
      '9012 headlight bulb',
      'h13 headlight bulb',
    ],
    expanded: [
      'fog light',
      'tail light',
      'brake light',
      'turn signal light',
      'daytime running light drl',
      'auxiliary driving light',
      'off road light bar',
      'headlight assembly',
      'projector retrofit',
      'headlight wiring harness',
      'headlight relay',
      'canbus adapter',
      'headlight glare',
      'headlight condensation',
      'headlight flicker',
      'headlight overheating',
      'headlight fitment',
    ],
    candidate_only_brands: ['SEALIGHT', 'Sylvania', 'Philips', 'AUXITO'],
  },
  market_rules: {
    dictionaries: {
      products: ['headlight protective film', 'protective film', 'vent kit', 'canbus adapter'],
      vehicles: ['f-150', 'silverado'],
      fitment: ['h11'],
      competitors: ['sealight', 'sylvania'],
      retailers: ['amazon'],
      slang: ['flicker', 'condensation'],
      stopwords: ['light', 'lights', 'car', 'cars', 'kit'],
    },
  },
};

test('extractKeywordCandidates derives normalized exploratory phrases with provenance and without mutating formal keywords', () => {
  const before = structuredClone(config.keywords);
  const candidates = extractKeywordCandidates(makeEvidence(), makeAuthorActivity(), config);
  const byTerm = new Map(candidates.map((candidate) => [candidate.term, candidate]));

  assert.deepEqual(config.keywords, before);
  assert.equal(byTerm.has('headlight protective film'), true);
  assert.equal(byTerm.has('vent membrane'), true);
  assert.equal(byTerm.has('sealight'), false);
  assert.equal(byTerm.has('headlight bulb'), false);
  assert.equal(byTerm.has('light'), false);

  const protectiveFilm = byTerm.get('headlight protective film');
  assert.deepEqual(protectiveFilm.parent_formal_terms, ['headlight condensation']);
  assert.deepEqual(protectiveFilm.communities.sort(), ['Cartalk', 'F150', 'MechanicAdvice']);
  assert.deepEqual(protectiveFilm.authors.sort(), ['alice', 'bob', 'carol']);
  assert.equal(protectiveFilm.evidence_ids.length >= 4, true);
  assert.equal(protectiveFilm.extraction_methods.includes('ngram'), true);
  assert.equal(protectiveFilm.extraction_methods.includes('dictionary'), true);
  assert.equal(protectiveFilm.categories.includes('product'), true);
  assert.equal(protectiveFilm.purchase_signal_count >= 1, true);
  assert.equal(protectiveFilm.pain_signal_count >= 1, true);
});

test('scoreKeywordCandidates rewards cross-community evidence and penalizes one-user or brand-only terms', () => {
  const scored = scoreKeywordCandidates(extractKeywordCandidates(makeEvidence(), makeAuthorActivity(), config), config);
  const byTerm = new Map(scored.map((candidate) => [candidate.term, candidate]));

  const protectiveFilm = byTerm.get('headlight protective film');
  const ventMembrane = byTerm.get('vent membrane');
  const oneUser = byTerm.get('relay harness fix');

  assert.equal(protectiveFilm.discovery_score >= 65, true);
  assert.equal(protectiveFilm.status, 'candidate_review');
  assert.equal(protectiveFilm.score_breakdown.unique_users > oneUser.score_breakdown.unique_users, true);
  assert.equal(oneUser.penalties.one_user_dominance > 0, true);
  assert.equal(ventMembrane.score_breakdown.cross_community > 0, true);
  assert.equal(ventMembrane.score_breakdown.pain_or_workaround > 0, true);
  assert.equal(ventMembrane.discovery_score < protectiveFilm.discovery_score, true);
});

test('selectRoundTwoTerms enforces bounded score, user, and community gates and caps the pool at twenty terms', () => {
  const scored = scoreKeywordCandidates(extractKeywordCandidates(makeEvidence(), makeAuthorActivity(), config), config);
  const padded = [
    ...scored,
    ...Array.from({ length: 25 }, (_, index) => ({
      term: `candidate-${index}`,
      normalized_term: `candidate-${index}`,
      unique_user_count: 3,
      community_count: 2,
      discovery_score: 90 - index,
      penalties: {
        one_user_dominance: 0,
        one_thread_dominance: 0,
        brand_only: 0,
        promotional_language: 0,
        generic_language: 0,
        excluded_evidence: 0,
        total: 0,
      },
      score_breakdown: {
        unique_users: 25,
        cross_community: 15,
        specificity: 15,
        purchase_intent: 15,
        pain_or_workaround: 10,
        anchor_cooccurrence: 10,
        novelty: 10,
      },
      status: 'candidate_review',
    })),
  ];

  const selected = selectRoundTwoTerms(padded, {
    maxTerms: 20,
    minimumScore: 65,
    minimumUsers: 2,
    minimumCommunities: 2,
  });

  assert.equal(selected.length, 20);
  assert.equal(selected.includes('headlight protective film'), true);
  assert.equal(selected.includes('relay harness fix'), false);
  assert.equal(selected.includes('candidate-0'), true);
  assert.equal(selected.includes('candidate-20'), false);
});

function makeEvidence() {
  return [
    {
      id: 'post-1',
      type: 'post',
      author: 'alice',
      subreddit: 'MechanicAdvice',
      title: 'My headlight condensation keeps coming back on an F-150',
      body_original: 'I am considering headlight protective film because the vent membrane kit failed. Budget is under $80.',
      quality: { eligible: true, quality_band: 'high', evidence_role: 'direct_experience', quality_score: 88 },
    },
    {
      id: 'comment-1',
      type: 'comment',
      post_id: 'post-1',
      author: 'bob',
      subreddit: 'MechanicAdvice',
      body_original: 'I bought protective film from Amazon after my headlight condensation returned.',
      quality: { eligible: true, quality_band: 'high', evidence_role: 'direct_experience', quality_score: 82 },
    },
    {
      id: 'post-2',
      type: 'post',
      author: 'carol',
      subreddit: 'Cartalk',
      title: 'Silverado vent membrane ideas',
      body_original: 'My condensation problem came back. Looking for a vent membrane instead of another headlight assembly.',
      quality: { eligible: true, quality_band: 'high', evidence_role: 'contextual_demand', quality_score: 78 },
    },
    {
      id: 'comment-2',
      type: 'comment',
      post_id: 'post-2',
      author: 'carol',
      subreddit: 'Cartalk',
      body_original: 'SEALIGHT has LEDs, but I still need a vent membrane that stops the leak.',
      quality: { eligible: true, quality_band: 'high', evidence_role: 'direct_experience', quality_score: 72 },
    },
    {
      id: 'post-3',
      type: 'post',
      author: 'alice',
      subreddit: 'F150',
      title: 'Relay harness fix for one truck',
      body_original: 'My relay harness fix stopped the flicker on one F-150.',
      quality: { eligible: true, quality_band: 'high', evidence_role: 'direct_experience', quality_score: 70 },
    },
    {
      id: 'comment-weak',
      type: 'comment',
      post_id: 'post-3',
      author: 'dave',
      subreddit: 'F150',
      body_original: 'nice',
      quality: { eligible: false, quality_band: 'noise', evidence_role: 'noise', quality_score: 0 },
    },
  ];
}

function makeAuthorActivity() {
  return [
    {
      username: 'alice',
      retained_activity: [
        {
          id: 'activity-1',
          activity_type: 'post',
          author: 'alice',
          subreddit: 'F150',
          title: 'Headlight protective film test',
          body_original: 'I bought headlight protective film after the condensation came back.',
          quality: { eligible: true, quality_band: 'high', evidence_role: 'direct_experience', quality_score: 80 },
          discovered_terms: ['headlight protective film'],
        },
      ],
    },
    {
      username: 'carol',
      retained_activity: [
        {
          id: 'activity-2',
          activity_type: 'comment',
          author: 'carol',
          subreddit: 'Cartalk',
          body_original: 'A vent membrane plus protective film seems better than another assembly.',
          quality: { eligible: true, quality_band: 'medium', evidence_role: 'contextual_demand', quality_score: 64 },
          discovered_terms: ['vent membrane', 'protective film'],
        },
      ],
    },
  ];
}
