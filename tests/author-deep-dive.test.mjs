import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  collectAuthorActivity,
  extractSelfDeclaredContext,
  retainRelevantActivity,
  selectAuthors,
} from '../src/author-deep-dive.mjs';

test('selectAuthors prioritizes high-quality source-post authors and multi-record qualified contributors', () => {
  const qualifiedEvidence = [
    makeEvidence({ id: 'post-alice', type: 'post', author: 'alice', qualityBand: 'high', evidenceRole: 'direct_experience', score: 10, commentCount: 3 }),
    makeEvidence({ id: 'comment-bob', type: 'comment', postId: 'p1', author: 'bob', qualityBand: 'medium', evidenceRole: 'qualified_practitioner', score: 40 }),
    makeEvidence({ id: 'post-carol', type: 'post', author: 'carol', qualityBand: 'high', evidenceRole: 'market_observation', score: 4, commentCount: 2 }),
    makeEvidence({ id: 'comment-carol', type: 'comment', postId: 'p2', author: 'carol', qualityBand: 'medium', evidenceRole: 'qualified_practitioner', score: 6 }),
    makeEvidence({ id: 'post-store', type: 'post', author: 'best_headlights_store', qualityBand: 'high', evidenceRole: 'direct_experience', score: 90 }),
    makeEvidence({ id: 'post-mod', type: 'post', author: 'mod_team', qualityBand: 'high', evidenceRole: 'direct_experience', score: 90 }),
    makeEvidence({ id: 'post-deleted', type: 'post', author: null, qualityBand: 'high', evidenceRole: 'direct_experience', score: 50 }),
  ];

  const selected = selectAuthors(qualifiedEvidence, { limit: 5 });

  assert.deepEqual(selected.map((item) => item.username).sort(), ['alice', 'carol']);
  assert.equal(selected.find((item) => item.username === 'alice')?.high_quality_source_post_count, 1);
  assert.equal(selected.find((item) => item.username === 'carol')?.qualified_record_count, 2);
  assert.deepEqual(selected.find((item) => item.username === 'carol')?.evidence_ids, ['comment-carol', 'post-carol']);
  assert.deepEqual(selected.find((item) => item.username === 'carol')?.source_post_ids, ['post-carol']);
});

test('selectAuthors requires at least one eligible high-quality record and does not admit medium-only authors', () => {
  const qualifiedEvidence = [
    makeEvidence({ id: 'post-alice', type: 'post', author: 'alice', qualityBand: 'high', evidenceRole: 'direct_experience' }),
    makeEvidence({ id: 'post-bob', type: 'post', author: 'bob', qualityBand: 'medium', evidenceRole: 'direct_experience' }),
    makeEvidence({ id: 'comment-bob', type: 'comment', postId: 'p-bob', author: 'bob', qualityBand: 'medium', evidenceRole: 'qualified_practitioner' }),
    makeEvidence({ id: 'post-carol', type: 'post', author: 'carol', qualityBand: 'high', evidenceRole: 'direct_experience', eligible: false }),
    makeEvidence({ id: 'comment-carol', type: 'comment', postId: 'p-carol', author: 'carol', qualityBand: 'high', evidenceRole: 'qualified_practitioner', eligible: false }),
  ];

  const selected = selectAuthors(qualifiedEvidence, { limit: 5 });

  assert.deepEqual(selected.map((item) => item.username), ['alice']);
});

test('selectAuthors requires at least one eligible high-quality source post and deduplicates repeated author evidence', () => {
  const qualifiedEvidence = [
    makeEvidence({ id: 'post-alice', type: 'post', author: 'alice', qualityBand: 'high', evidenceRole: 'direct_experience' }),
    makeEvidence({ id: 'comment-alice', type: 'comment', postId: 'p1', author: 'alice', qualityBand: 'high', evidenceRole: 'qualified_practitioner' }),
    makeEvidence({ id: 'comment-bob-1', type: 'comment', postId: 'p2', author: 'bob', qualityBand: 'high', evidenceRole: 'qualified_practitioner' }),
    makeEvidence({ id: 'comment-bob-2', type: 'comment', postId: 'p2', author: 'bob', qualityBand: 'medium', evidenceRole: 'qualified_practitioner' }),
    makeEvidence({ id: 'post-alice-duplicate', type: 'post', postId: 'post-alice-duplicate', author: 'alice', qualityBand: 'high', evidenceRole: 'direct_experience' }),
  ];

  const selected = selectAuthors(qualifiedEvidence, { limit: 5 });

  assert.deepEqual(selected.map((item) => item.username), ['alice']);
  assert.deepEqual(selected[0].source_post_ids, ['post-alice', 'post-alice-duplicate']);
});

test('retainRelevantActivity keeps market-relevant public activity and discards unrelated personal history', () => {
  const authorItems = [
    {
      id: 'lighting-post',
      activity_type: 'post',
      subreddit: 'Cartalk',
      title: 'Silverado headlight condensation keeps coming back',
      body_original: 'I am still comparing vent kits and protective film options.',
      created_at: '2026-08-20T00:00:00.000Z',
      url: 'https://www.reddit.com/r/Cartalk/comments/lighting-post',
      author: 'alice',
      score: 8,
    },
    {
      id: 'budget-comment',
      activity_type: 'comment',
      subreddit: 'MechanicAdvice',
      body_original: 'My budget is under $150 for H11 bulbs and I would rather install them myself.',
      created_at: '2026-08-19T00:00:00.000Z',
      url: 'https://www.reddit.com/r/MechanicAdvice/comments/budget-comment',
      author: 'alice',
      score: 4,
    },
    {
      id: 'travel-post',
      activity_type: 'post',
      subreddit: 'travel',
      title: 'Summer road trip photos',
      body_original: 'Austin food was great and the hotel pool was perfect.',
      created_at: '2026-08-18T00:00:00.000Z',
      url: 'https://www.reddit.com/r/travel/comments/travel-post',
      author: 'alice',
      score: 20,
    },
    {
      id: 'sensitive-comment',
      activity_type: 'comment',
      subreddit: 'AskDocs',
      body_original: 'I am diabetic and worried about medication side effects.',
      created_at: '2026-08-17T00:00:00.000Z',
      url: 'https://www.reddit.com/r/AskDocs/comments/sensitive-comment',
      author: 'alice',
      score: 1,
    },
  ];

  const kept = retainRelevantActivity(authorItems, {
    market: { country: 'US' },
    productTerms: ['headlight', 'h11', 'floor mat'],
    dictionaries: {
      products: ['headlight', 'bulb', 'protective film', 'vent kit'],
      vehicles: ['silverado'],
      fitment: ['h11'],
      slang: ['condensation'],
    },
  });

  assert.deepEqual(kept.retained.map((item) => item.id), ['lighting-post', 'budget-comment']);
  assert.equal(kept.excluded_count, 2);
  assert.match(kept.retained[0].relevance_reasons.join(' '), /product/i);
  assert.equal(kept.retained[1].self_declared_context.find((item) => item.kind === 'budget')?.value, 'under $150');
});

test('extractSelfDeclaredContext converts explicit self-reports into safe aggregate-ready fields', () => {
  const activity = {
    id: 'activity-1',
    activity_type: 'comment',
    body_original: 'I am 32, based in Austin, Texas. My budget is under $120 for an H11 upgrade. I daily drive an F-150 and install these myself. I make $200k and I am diabetic.',
    created_at: '2026-08-21T00:00:00.000Z',
    url: 'https://www.reddit.com/r/f150/comments/activity-1',
  };

  const result = extractSelfDeclaredContext(activity, activity.id);

  assert.deepEqual(result.map((item) => item.kind), ['age_band', 'state', 'budget', 'vehicle', 'diy_ability']);
  assert.equal(result.find((item) => item.kind === 'age_band')?.value, '25-34');
  assert.equal(result.find((item) => item.kind === 'state')?.value, 'Texas');
  assert.equal(result.find((item) => item.kind === 'budget')?.value, 'under $120');
  assert.equal(result.some((item) => /Austin|200k|diabetic/i.test(String(item.value))), false);
  assert.equal(result.every((item) => item.source === 'self_declared'), true);
});

test('extractSelfDeclaredContext only keeps state from explicit first-person location statements', () => {
  const examples = [
    {
      body_original: 'My brother moved to Texas and recommended these headlights.',
      expectedState: false,
    },
    {
      body_original: 'The seller shipped from California but I still need better bulbs.',
      expectedState: false,
    },
    {
      body_original: 'I live in Texas and still need a better cutoff.',
      expectedState: 'Texas',
    },
    {
      body_original: 'I am based in California for work and drive an F-150.',
      expectedState: 'California',
    },
  ];

  for (const [index, example] of examples.entries()) {
    const result = extractSelfDeclaredContext({
      id: `state-${index}`,
      activity_type: 'comment',
      body_original: example.body_original,
      created_at: '2026-08-21T00:00:00.000Z',
      url: `https://www.reddit.com/comments/state-${index}`,
    }, `state-${index}`);
    const state = result.find((item) => item.kind === 'state')?.value ?? false;
    assert.equal(state, example.expectedState);
  }
});

test('extractSelfDeclaredContext chooses the earliest allowed state inside a first-person location clause', () => {
  const result = extractSelfDeclaredContext({
    id: 'state-order',
    activity_type: 'comment',
    body_original: 'I live in Texas but travel to California for work, and I still need a better cutoff.',
    created_at: '2026-08-21T00:00:00.000Z',
    url: 'https://www.reddit.com/comments/state-order',
  }, 'state-order');

  assert.equal(result.find((item) => item.kind === 'state')?.value, 'Texas');
});

test('collectAuthorActivity enforces author and total limits, writes checkpoints, and continues failures', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'author-deep-dive-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));

  const calls = [];
  const adapter = {
    async fetchAuthorActivity(username, options) {
      calls.push({ username, limit: options.limit, afterUtc: options.afterUtc });
      if (username === 'private_user') {
        const error = new Error('Reddit HTTP 403: private profile');
        error.status = 403;
        throw error;
      }

      const itemsByUser = {
        alice: [
          makeActivity({ id: 'alice-1', title: 'Headlight beam pattern issue', body: 'My budget is under $90 for a replacement.', subreddit: 'Cartalk', createdAt: '2026-08-25T00:00:00.000Z' }),
          makeActivity({ id: 'alice-2', body: 'H11 bulbs fixed my F-150 lighting issue.', subreddit: 'f150', createdAt: '2026-08-24T00:00:00.000Z', type: 'comment' }),
          makeActivity({ id: 'alice-old', body: 'Old headlight post', subreddit: 'Cartalk', createdAt: '2025-01-01T00:00:00.000Z', type: 'comment' }),
        ],
        charlie: [
          makeActivity({ id: 'charlie-1', body: 'I need a floor mat after replacing the headlight assembly.', subreddit: 'MechanicAdvice', createdAt: '2026-08-23T00:00:00.000Z', type: 'comment' }),
          makeActivity({ id: 'charlie-2', body: 'Weekend hiking photos', subreddit: 'travel', createdAt: '2026-08-22T00:00:00.000Z', type: 'comment' }),
        ],
      };
      return itemsByUser[username] ?? [];
    },
  };

  const authors = [
    { username: 'alice', evidence_ids: ['post-alice'], source_post_ids: ['post-alice'] },
    { username: 'private_user', evidence_ids: ['post-private'], source_post_ids: ['post-private'] },
    { username: 'charlie', evidence_ids: ['post-charlie'], source_post_ids: ['post-charlie'] },
  ];

  const result = await collectAuthorActivity(authors, adapter, {
    runDir,
    afterUtc: '2026-02-28T00:00:00.000Z',
    limitPerAuthor: 2,
    maxTotalActivities: 3,
    timeoutMs: 5000,
    productTerms: ['headlight', 'floor mat', 'h11'],
    dictionaries: {
      products: ['headlight', 'bulb', 'headlight assembly', 'floor mat'],
      vehicles: ['f-150'],
      fitment: ['h11'],
      slang: ['beam pattern'],
    },
    market: { country: 'US' },
  });

  assert.deepEqual(calls, [
    { username: 'alice', limit: 2, afterUtc: '2026-02-28T00:00:00.000Z' },
    { username: 'private_user', limit: 1, afterUtc: '2026-02-28T00:00:00.000Z' },
    { username: 'charlie', limit: 1, afterUtc: '2026-02-28T00:00:00.000Z' },
  ]);
  assert.equal(result.authors.length, 2);
  assert.equal(result.failures.length, 1);
  assert.equal(result.failures[0].username, 'private_user');
  assert.equal(result.summary.retained_activities, 3);
  assert.equal(await exists(path.join(runDir, 'raw', 'authors', 'alice.json')), true);
  assert.equal(await exists(path.join(runDir, 'raw', 'authors', 'charlie.json')), true);
  assert.equal(await exists(path.join(runDir, 'raw', 'authors', 'private_user.json')), false);
  const aliceCheckpoint = JSON.parse(await fs.readFile(path.join(runDir, 'raw', 'authors', 'alice.json'), 'utf8'));
  assert.deepEqual(aliceCheckpoint.source_post_ids, ['post-alice']);
});

test('collectAuthorActivity reapplies stricter caps when resuming from older wider checkpoints', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'author-deep-dive-resume-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const authorsDir = path.join(runDir, 'raw', 'authors');
  await fs.mkdir(authorsDir, { recursive: true });
  await fs.writeFile(path.join(authorsDir, 'alice.json'), `${JSON.stringify({
    schema_version: '1.0.0',
    username: 'alice',
    source_post_ids: ['post-alice'],
    source_evidence_ids: ['post-alice'],
    retained_count: 2,
    excluded_count: 0,
    limits: {
      requested_limit: 2,
      applied_after_utc: '2026-02-28T00:00:00.000Z',
      max_total_activities: 4,
    },
    retained_activity: [
      makeRetainedActivity({ id: 'post-alice-1', createdAt: '2026-08-25T00:00:00.000Z' }),
      makeRetainedActivity({ id: 'post-alice-2', createdAt: '2026-08-24T00:00:00.000Z' }),
    ],
    privacy_note: 'Only public, research-relevant automotive content is retained; no sensitive demographic attributes are inferred.',
  }, null, 2)}\n`, 'utf8');
  await fs.writeFile(path.join(authorsDir, 'charlie.json'), `${JSON.stringify({
    schema_version: '1.0.0',
    username: 'charlie',
    source_post_ids: ['post-charlie'],
    source_evidence_ids: ['post-charlie'],
    retained_count: 2,
    excluded_count: 0,
    limits: {
      requested_limit: 2,
      applied_after_utc: '2026-02-28T00:00:00.000Z',
      max_total_activities: 4,
    },
    retained_activity: [
      makeRetainedActivity({ id: 'post-charlie-1', createdAt: '2026-08-23T00:00:00.000Z', username: 'charlie' }),
      makeRetainedActivity({ id: 'post-charlie-2', createdAt: '2026-08-22T00:00:00.000Z', username: 'charlie' }),
    ],
    privacy_note: 'Only public, research-relevant automotive content is retained; no sensitive demographic attributes are inferred.',
  }, null, 2)}\n`, 'utf8');

  const calls = [];
  const adapter = {
    async fetchAuthorActivity(username) {
      calls.push(username);
      return [];
    },
  };

  const result = await collectAuthorActivity([
    { username: 'alice', evidence_ids: ['post-alice'], source_post_ids: ['post-alice'] },
    { username: 'charlie', evidence_ids: ['post-charlie'], source_post_ids: ['post-charlie'] },
  ], adapter, {
    runDir,
    afterUtc: '2026-02-28T00:00:00.000Z',
    limitPerAuthor: 1,
    maxTotalActivities: 1,
    timeoutMs: 5000,
    productTerms: ['headlight'],
    market: { country: 'US' },
  });

  assert.deepEqual(calls, []);
  assert.equal(result.authors.length, 1);
  assert.equal(result.authors[0].username, 'alice');
  assert.equal(result.authors[0].retained_activity.length, 1);
  assert.equal(result.summary.authors_collected, 1);
  assert.equal(result.summary.retained_activities, 1);
  const aliceCheckpoint = JSON.parse(await fs.readFile(path.join(authorsDir, 'alice.json'), 'utf8'));
  assert.equal(aliceCheckpoint.retained_activity.length, 1);
  assert.deepEqual(aliceCheckpoint.source_post_ids, ['post-alice']);
  assert.equal(await exists(path.join(authorsDir, 'charlie.json')), true);
});

function makeEvidence({
  id,
  type,
  postId = null,
  author,
  qualityBand,
  evidenceRole,
  score = 0,
  commentCount = 0,
  eligible = true,
}) {
  return {
    id,
    type,
    post_id: postId,
    author,
    title: `${id} title`,
    body_original: `${id} body`,
    score,
    comment_count: commentCount,
    quality: {
      quality_band: qualityBand,
      evidence_role: evidenceRole,
      eligible,
      hard_exclusion: false,
    },
  };
}

function makeActivity({
  id,
  title = '',
  body = '',
  subreddit,
  createdAt,
  type = 'post',
}) {
  return {
    id,
    activity_type: type,
    title,
    body_original: body,
    subreddit,
    created_at: createdAt,
    url: `https://www.reddit.com/r/${subreddit}/comments/${id}`,
    score: 1,
  };
}

function makeRetainedActivity({ id, createdAt, username = 'alice' }) {
  return {
    id,
    activity_id: id.replace(/^post-/, ''),
    activity_type: 'post',
    username,
    subreddit: 'Cartalk',
    title: 'Headlight protective film',
    body_original: 'My budget is under $80.',
    created_at: createdAt,
    url: `https://www.reddit.com/r/Cartalk/comments/${id}`,
    relevance_reasons: ['product_context'],
    quality: {
      evidence_role: 'contextual_demand',
      quality_band: 'noise',
      quality_score: 29,
      eligible: false,
      hard_exclusion: false,
      components: {},
      penalties: {},
      reason_codes: ['contextual_demand'],
    },
    product_concepts: ['protective-headlight-film'],
    pain_points: [],
    discovered_terms: ['protective film'],
    self_declared_context: [],
  };
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}
