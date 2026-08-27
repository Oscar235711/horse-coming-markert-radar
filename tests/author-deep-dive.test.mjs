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
    makeEvidence({ id: 'post-carol', type: 'post', author: 'carol', qualityBand: 'medium', evidenceRole: 'market_observation', score: 4, commentCount: 2 }),
    makeEvidence({ id: 'comment-carol', type: 'comment', postId: 'p2', author: 'carol', qualityBand: 'medium', evidenceRole: 'qualified_practitioner', score: 6 }),
    makeEvidence({ id: 'post-store', type: 'post', author: 'best_headlights_store', qualityBand: 'high', evidenceRole: 'direct_experience', score: 90 }),
    makeEvidence({ id: 'post-mod', type: 'post', author: 'mod_team', qualityBand: 'high', evidenceRole: 'direct_experience', score: 90 }),
    makeEvidence({ id: 'post-deleted', type: 'post', author: null, qualityBand: 'high', evidenceRole: 'direct_experience', score: 50 }),
  ];

  const selected = selectAuthors(qualifiedEvidence, { limit: 5 });

  assert.deepEqual(selected.map((item) => item.username), ['alice', 'carol']);
  assert.equal(selected[0].high_quality_source_post_count, 1);
  assert.equal(selected[1].qualified_record_count, 2);
  assert.deepEqual(selected[1].evidence_ids, ['comment-carol', 'post-carol']);
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
    { username: 'alice', evidence_ids: ['post-alice'] },
    { username: 'private_user', evidence_ids: ['post-private'] },
    { username: 'charlie', evidence_ids: ['post-charlie'] },
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
      eligible: true,
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

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}
