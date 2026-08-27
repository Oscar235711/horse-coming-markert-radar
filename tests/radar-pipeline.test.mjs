import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  buildOpenCliSearchArgs,
  createPublicJsonAdapter,
  parseRedditAtom,
  runRadarPipeline,
} from '../src/radar-pipeline.mjs';

const config = {
  schema_version: '1.0.0',
  name: 'fixture',
  market: { country: 'US' },
  keywords: { anchors: Array.from({ length: 14 }, (_, index) => `anchor-${index}`), expanded: ['fog light'] },
  query_groups: ['headlight problem'],
  subreddits: Array.from({ length: 10 }, (_, index) => `sub${index}`),
  limits: { posts: 30, comments_per_post: 20, search_results_per_query: 15 },
  transport: { request_interval_ms: 0, timeout_ms: 1000 },
};

test('OpenCLI search arguments keep the executable path external and constrain the scan', () => {
  const args = buildOpenCliSearchArgs('headlight flicker', { limit: 15 });

  assert.deepEqual(args.slice(0, 3), ['reddit', 'search', 'headlight flicker']);
  assert.ok(args.includes('--limit'));
  assert.ok(args.includes('15'));
  assert.ok(args.includes('--time'));
  assert.ok(args.includes('year'));
  assert.ok(!args.includes('opencli'));
});

test('public JSON adapter normalizes Reddit search and caps comments', async () => {
  const requested = [];
  const fakeFetch = async (url) => {
    requested.push(String(url));
    if (String(url).includes('/search.json')) {
      return jsonResponse({ data: { children: [{ data: { id: 'p1', title: 'Headlight issue', subreddit: 'sub0', permalink: '/comments/p1/x' } }] } });
    }
    const comments = Array.from({ length: 25 }, (_, index) => ({ kind: 't1', data: { id: `c${index}`, body: `Body ${index}`, score: index, permalink: `/comments/p1/x/c${index}` } }));
    return jsonResponse([
      { data: { children: [{ data: { id: 'p1', title: 'Headlight issue', subreddit: 'sub0', permalink: '/comments/p1/x' } }] } },
      { data: { children: comments } },
    ]);
  };
  const adapter = createPublicJsonAdapter({ fetchImpl: fakeFetch, baseUrl: 'https://www.reddit.com' });

  const posts = await adapter.search('headlight problem', { limit: 15, timeoutMs: 1000 });
  const detail = await adapter.fetchDetails({ post_id: 'p1' }, { commentLimit: 20, timeoutMs: 1000 });

  assert.equal(posts.length, 1);
  assert.equal(detail.comments.length, 20);
  assert.ok(requested[0].includes('raw_json=1'));
  assert.ok(requested[1].includes('limit=20'));
});

test('public JSON adapter fetches author activity through overview JSON and falls back to RSS feeds', async () => {
  const requested = [];
  const adapter = createPublicJsonAdapter({
    baseUrl: 'https://old.reddit.com',
    rssBaseUrl: 'https://www.reddit.com',
    fetchImpl: async (url) => {
      requested.push(String(url));
      if (String(url).includes('/overview.json')) return errorResponse(404, 'Not Found');
      if (String(url).includes('/submitted.rss')) {
        return textResponse(`<?xml version="1.0"?><feed><entry><author><name>/u/tester</name></author><category term="Cartalk"/><content type="html">&lt;p&gt;F-150 headlight condensation&lt;/p&gt;</content><id>t3_post1</id><link href="https://www.reddit.com/r/Cartalk/comments/post1/x/"/><updated>2026-08-01T00:00:00+00:00</updated><title>Headlight condensation</title></entry></feed>`);
      }
      return textResponse(`<?xml version="1.0"?><feed><entry><author><name>/u/tester</name></author><category term="MechanicAdvice"/><content type="html">&lt;p&gt;My budget is under $100 for H11 bulbs&lt;/p&gt;</content><id>t1_comment1</id><link href="https://www.reddit.com/r/MechanicAdvice/comments/post1/x/comment1/"/><updated>2026-08-02T00:00:00+00:00</updated><title>/u/tester on Headlight condensation</title></entry></feed>`);
    },
  });

  const activity = await adapter.fetchAuthorActivity('tester', { limit: 3, afterUtc: '2026-07-01T00:00:00.000Z', timeoutMs: 1000 });

  assert.equal(activity.length, 2);
  assert.deepEqual(activity.map((item) => item.activity_type), ['comment', 'post']);
  assert.ok(requested[0].includes('/user/tester/overview.json'));
  assert.ok(requested.some((url) => url.includes('/user/tester/submitted.rss')));
  assert.ok(requested.some((url) => url.includes('/user/tester/comments.rss')));
});

test('public adapter falls back to Reddit RSS when JSON search is blocked', async () => {
  const requested = [];
  const adapter = createPublicJsonAdapter({
    baseUrl: 'https://old.reddit.com',
    rssBaseUrl: 'https://www.reddit.com',
    fetchImpl: async (url) => {
      requested.push(String(url));
      if (String(url).includes('search.json')) return errorResponse(404, 'Not Found');
      return textResponse(`<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><author><name>/u/tester</name></author><category term="MechanicAdvice" label="r/MechanicAdvice"/><content type="html">&lt;div&gt;My H11 headlights flicker on an F-150&lt;/div&gt;</content><id>t3_p1</id><link href="https://www.reddit.com/r/MechanicAdvice/comments/p1/headlight/"/><updated>2026-08-01T00:00:00+00:00</updated><title>H11 headlight flicker</title></entry></feed>`);
    },
  });

  const posts = await adapter.search('headlight flicker', { limit: 15, timeoutMs: 1000 });

  assert.equal(posts.length, 1);
  assert.equal(posts[0].id, 'p1');
  assert.equal(posts[0].subreddit, 'MechanicAdvice');
  assert.match(posts[0].selftext, /F-150/);
  assert.ok(requested[0].startsWith('https://old.reddit.com/search.json'));
  assert.ok(requested[1].startsWith('https://www.reddit.com/search.rss'));
});

test('Atom parser ignores subreddit entries and returns post/comment records', () => {
  const xml = `<?xml version="1.0"?><feed><entry><id>t5_sub</id><title>A community</title></entry><entry><author><name>/u/op</name></author><category term="Cartalk"/><content type="html">&lt;p&gt;Post&#32;body&#39;s text&lt;/p&gt;</content><id>t3_abc</id><link href="https://www.reddit.com/r/Cartalk/comments/abc/x/"/><updated>2026-08-01T00:00:00+00:00</updated><title>Headlight problem</title></entry><entry><author><name>/u/helper</name></author><content type="html">&lt;p&gt;Use a relay harness&lt;/p&gt;</content><id>t1_comment</id><link href="https://www.reddit.com/r/Cartalk/comments/abc/x/comment/"/><updated>2026-08-02T00:00:00+00:00</updated><title>/u/helper on Headlight problem</title></entry></feed>`;

  const parsed = parseRedditAtom(xml);

  assert.equal(parsed.posts.length, 1);
  assert.equal(parsed.comments.length, 1);
  assert.equal(parsed.posts[0].id, 'abc');
  assert.equal(parsed.posts[0].selftext, "Post body's text");
  assert.equal(parsed.comments[0].body, 'Use a relay harness');
});

test('RSS fallback retries one 429 response before failing the query', async () => {
  let rssAttempts = 0;
  const adapter = createPublicJsonAdapter({
    baseUrl: 'https://old.reddit.com',
    rssBaseUrl: 'https://www.reddit.com',
    retryDelayMs: 0,
    fetchImpl: async (url) => {
      if (String(url).includes('.json')) return errorResponse(404, 'Not Found');
      rssAttempts += 1;
      if (rssAttempts === 1) return errorResponse(429, '');
      return textResponse(`<?xml version="1.0"?><feed><entry><id>t3_retry</id><category term="Cartalk"/><title>Headlight retry</title><content type="html">body</content><link href="https://www.reddit.com/r/Cartalk/comments/retry/x/"/></entry></feed>`);
    },
  });

  const posts = await adapter.search('headlight', { limit: 5, timeoutMs: 1000 });

  assert.equal(rssAttempts, 2);
  assert.equal(posts[0].id, 'retry');
});

test('pipeline deduplicates candidates, records failures, and continues', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-pipeline-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const adapter = fixtureAdapter();

  const result = await runRadarPipeline({ config, adapter, runDir, runId: 'fixture-run' });

  assert.equal(result.candidates.length, 2);
  assert.equal(result.details.length, 1);
  assert.equal(result.failures.length, 1);
  assert.equal(result.manifest.status, 'partial');
  assert.deepEqual(adapter.visited, ['p1', 'bad']);
  const backlog = (await fs.readFile(path.join(runDir, 'optimization_backlog.jsonl'), 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  assert.equal(backlog.length >= 7, true);
  for (const id of ['missing-html', 'schema-gap', 'missing-actions']) {
    assert.equal(backlog.find((item) => item.id === id)?.status, 'resolved');
  }
  assert.equal(backlog.find((item) => item.id === 'public-json-blocked')?.status, 'mitigated');
  assert.equal((await fs.readFile(path.join(runDir, 'failures.jsonl'), 'utf8')).includes('rate limited'), true);
});

test('pipeline collects relevant author activity, writes checkpoints, and records profile failures without stopping', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-authors-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const authorCalls = [];
  const adapter = {
    name: 'fixture',
    async search() {
      return [
        { id: 'p1', title: 'I installed H11 LEDs on my F-150 and they still flicker', selftext: 'Texas. Which adapter should I buy?', subreddit: 'sub0', score: 25, num_comments: 10, permalink: '/comments/p1/x', author: 'alice' },
        { id: 'p2', title: 'I replaced my Silverado fog lights but the vent kit failed', selftext: 'Ohio owner here. I checked the dust cap and seal, but condensation came back.', subreddit: 'sub1', score: 18, num_comments: 6, permalink: '/comments/p2/x', author: 'private_user' },
      ];
    },
    async fetchDetails(post) {
      return {
        post: { id: post.post_id, title: post.title, selftext: post.body_original, subreddit: post.subreddit, score: post.score, num_comments: post.comment_count, permalink: post.url, author: post.author },
        comments: [{ id: `c-${post.post_id}`, body: post.post_id === 'p1' ? 'I bought a CANbus adapter and it fixed the issue.' : 'My vent kit reduced the condensation for a month before it came back.', score: 8, permalink: `/comments/${post.post_id}/x/c1`, author: post.author }],
      };
    },
    async fetchAuthorActivity(username, options) {
      authorCalls.push({ username, limit: options.limit });
      if (username === 'private_user') {
        const error = new Error('Reddit HTTP 403: private profile');
        error.status = 403;
        throw error;
      }
      return [
        { id: 'a1', kind: 't3', data: { id: 'a1', author: username, subreddit: 'Cartalk', title: 'Headlight protective film', selftext: 'My budget is under $80.', permalink: '/r/Cartalk/comments/a1/x', created_utc: 1_787_529_600 } },
        { id: 'a2', kind: 't1', data: { id: 'a2', author: username, subreddit: 'travel', body: 'Beach photos', permalink: '/r/travel/comments/a2/x', created_utc: 1_787_529_700 } },
      ];
    },
  };
  const authorConfig = {
    ...config,
    limits: {
      ...config.limits,
      posts: 2,
      deep_dive_posts: 2,
      profile_users: 2,
      profile_items_per_user: 3,
      total_profile_items: 3,
    },
    keywords: {
      ...config.keywords,
      candidate_only_brands: [],
    },
  };

  const result = await runRadarPipeline({ config: authorConfig, adapter, runDir, runId: 'author-run' });

  assert.deepEqual(authorCalls, [
    { username: 'alice', limit: 3 },
    { username: 'private_user', limit: 2 },
  ]);
  assert.equal(result.authorCandidates.length, 2);
  assert.equal(result.authorActivity.length, 1);
  assert.equal(result.authorFailures.length, 1);
  assert.equal(result.manifest.counts.author_candidates, 2);
  assert.equal(result.manifest.counts.authors_collected, 1);
  assert.equal(result.manifest.counts.author_activities, 1);
  assert.equal(result.manifest.status, 'partial');
  const saved = JSON.parse(await fs.readFile(path.join(runDir, 'raw', 'authors', 'alice.json'), 'utf8'));
  assert.equal(saved.retained_activity.length, 1);
  assert.equal(JSON.stringify(saved).includes('Beach photos'), false);
  assert.equal((await fs.readFile(path.join(runDir, 'failures.jsonl'), 'utf8')).includes('private_user'), true);
});

test('pipeline resumes existing author checkpoints without refetching retained authors', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-author-resume-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const calls = [];
  const adapter = {
    name: 'fixture',
    async search() {
      return [{ id: 'p1', title: 'I installed H11 LEDs on my F-150 and they still flicker', selftext: 'Texas. Which adapter should I buy?', subreddit: 'sub0', score: 25, num_comments: 10, permalink: '/comments/p1/x', author: 'alice' }];
    },
    async fetchDetails(post) {
      return {
        post: { id: post.post_id, title: post.title, selftext: post.body_original, subreddit: post.subreddit, score: post.score, num_comments: post.comment_count, permalink: post.url, author: post.author },
        comments: [{ id: `c-${post.post_id}`, body: 'I bought a CANbus adapter and it fixed the issue.', score: 8, permalink: `/comments/${post.post_id}/x/c1`, author: post.author }],
      };
    },
    async fetchAuthorActivity(username) {
      calls.push(username);
      return [{ id: 'a1', kind: 't3', data: { id: 'a1', author: username, subreddit: 'Cartalk', title: 'Headlight protective film', selftext: 'My budget is under $80.', permalink: '/r/Cartalk/comments/a1/x', created_utc: 1_787_529_600 } }];
    },
  };
  const authorConfig = {
    ...config,
    limits: {
      ...config.limits,
      posts: 1,
      deep_dive_posts: 1,
      profile_users: 1,
      profile_items_per_user: 3,
    },
    keywords: {
      ...config.keywords,
      candidate_only_brands: [],
    },
  };

  await runRadarPipeline({ config: authorConfig, adapter, runDir, runId: 'author-resume-run' });
  const second = { ...adapter, fetchAuthorActivity: async () => { throw new Error('should not refetch author checkpoint'); } };

  const resumed = await runRadarPipeline({ config: authorConfig, adapter: second, runDir, runId: 'author-resume-run' });

  assert.deepEqual(calls, ['alice']);
  assert.equal(resumed.authorActivity.length, 1);
  assert.equal(resumed.manifest.counts.authors_collected, 1);
});

test('pipeline removes author checkpoints for users outside the current selected set', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-author-cleanup-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const authorsDir = path.join(runDir, 'raw', 'authors');
  await fs.mkdir(authorsDir, { recursive: true });
  await fs.writeFile(path.join(authorsDir, 'orphan.json'), JSON.stringify({ username: 'orphan', retained_activity: [] }), 'utf8');
  const adapter = {
    name: 'fixture',
    async search() {
      return [{ id: 'p1', title: 'I installed H11 LEDs on my F-150 and they still flicker', selftext: 'Texas. Which adapter should I buy?', subreddit: 'sub0', score: 25, num_comments: 10, permalink: '/comments/p1/x', author: 'alice' }];
    },
    async fetchDetails(post) {
      return {
        post: { id: post.post_id, title: post.title, selftext: post.body_original, subreddit: post.subreddit, score: post.score, num_comments: post.comment_count, permalink: post.url, author: post.author },
        comments: [{ id: `c-${post.post_id}`, body: 'I bought a CANbus adapter and it fixed the issue.', score: 8, permalink: `/comments/${post.post_id}/x/c1`, author: post.author }],
      };
    },
    async fetchAuthorActivity(username) {
      return [{ id: 'a1', kind: 't3', data: { id: 'a1', author: username, subreddit: 'Cartalk', title: 'Headlight protective film', selftext: 'I live in Texas and my budget is under $80.', permalink: '/r/Cartalk/comments/a1/x', created_utc: 1_787_529_600 } }];
    },
  };
  const authorConfig = {
    ...config,
    limits: {
      ...config.limits,
      posts: 1,
      deep_dive_posts: 1,
      profile_users: 1,
      profile_items_per_user: 2,
    },
    keywords: {
      ...config.keywords,
      candidate_only_brands: [],
    },
  };

  await runRadarPipeline({ config: authorConfig, adapter, runDir, runId: 'author-cleanup-run' });

  assert.equal(await fs.access(path.join(authorsDir, 'orphan.json')).then(() => true).catch(() => false), false);
  assert.equal(await fs.access(path.join(authorsDir, 'alice.json')).then(() => true).catch(() => false), true);
});

test('pipeline resumes completed detail files without refetching them', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-resume-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const first = fixtureAdapter();
  await runRadarPipeline({ config, adapter: first, runDir, runId: 'resume-run' });
  const second = fixtureAdapter({ failBad: false });

  const resumed = await runRadarPipeline({ config, adapter: second, runDir, runId: 'resume-run' });

  assert.deepEqual(second.visited, ['bad']);
  assert.equal(resumed.details.length, 2);
  assert.equal(resumed.manifest.status, 'complete');
});

test('pipeline can discover automotive lighting communities outside the seed list', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-discovery-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const adapter = {
    name: 'fixture',
    async search() {
      return [
        { id: 'auto', title: 'F-150 headlight housing problem', selftext: 'Texas truck fitment', subreddit: 'FordTrucks', permalink: '/comments/auto/x' },
        { id: 'home', title: 'Indoor grow light bulb problem', selftext: 'House plant', subreddit: 'gardening', permalink: '/comments/home/x' },
        { id: 'cat', title: 'My cat chose the headlight upgrade', selftext: 'Standard issue cat markings', subreddit: 'standardissuecat', permalink: '/comments/cat/x' },
        { id: 'race', title: 'Formula 1 tail lights fell off', selftext: 'Race chassis vibration', subreddit: 'formula1', permalink: '/comments/race/x' },
      ];
    },
    async fetchDetails(post) { return { post, comments: [] }; },
  };

  const result = await runRadarPipeline({ config, adapter, runDir, runId: 'discovery-run' });

  assert.deepEqual(result.candidates.map((post) => post.post_id), ['auto']);
});

test('pipeline scans the full candidate pool but deep-dives only the configured winners', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-deep-limit-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const visited = [];
  const adapter = {
    name: 'fixture',
    async search() {
      return [
        { id: 'top', title: 'F-150 headlight flicker what should I buy', selftext: 'Texas', subreddit: 'sub0', score: 20, num_comments: 15, permalink: '/comments/top/x' },
        { id: 'second', title: 'Silverado headlight bulb', selftext: 'Ohio', subreddit: 'sub1', score: 2, num_comments: 1, permalink: '/comments/second/x' },
      ];
    },
    async fetchDetails(post) { visited.push(post.post_id); return { post, comments: [] }; },
  };
  const limitedConfig = { ...config, limits: { ...config.limits, deep_dive_posts: 1 } };

  const result = await runRadarPipeline({ config: limitedConfig, adapter, runDir, runId: 'deep-limit-run' });

  assert.equal(result.candidates.length, 2);
  assert.deepEqual(visited, ['top']);
  assert.equal(result.manifest.counts.deep_dive_target, 1);
});

test('pipeline removes orphaned detail checkpoints after candidate ranking changes', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-orphan-detail-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const detailsDir = path.join(runDir, 'raw', 'details');
  await fs.mkdir(detailsDir, { recursive: true });
  await fs.writeFile(path.join(detailsDir, 'orphan.json'), JSON.stringify({ post: { post_id: 'orphan' }, comments: [] }), 'utf8');
  const adapter = {
    name: 'fixture',
    async search() { return [{ id: 'current', title: 'F-150 headlight issue', selftext: 'Texas', subreddit: 'sub0', permalink: '/comments/current/x' }]; },
    async fetchDetails(post) { return { post, comments: [] }; },
  };
  await runRadarPipeline({ config, adapter, runDir, runId: 'orphan-run' });
  assert.equal(await fs.access(path.join(detailsDir, 'orphan.json')).then(() => true).catch(() => false), false);
  assert.equal(await fs.access(path.join(detailsDir, 'current.json')).then(() => true).catch(() => false), true);
});

test('deep-dive ranking places explicit US evidence before higher-scoring unknown geography', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-us-priority-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const visited = [];
  const adapter = {
    name: 'fixture',
    async search() {
      return [
        { id: 'unknown', title: 'Headlight flicker what should I buy', selftext: 'No location', subreddit: 'CarTalk', score: 100, num_comments: 100, permalink: '/comments/unknown/x' },
        { id: 'us', title: 'Headlight bulb issue in Texas', selftext: 'F-150', subreddit: 'f150', score: 1, num_comments: 1, permalink: '/comments/us/x' },
      ];
    },
    async fetchDetails(post) { visited.push(post.post_id); return { post, comments: [] }; },
  };
  const limitedConfig = { ...config, limits: { ...config.limits, deep_dive_posts: 1 } };

  await runRadarPipeline({ config: limitedConfig, adapter, runDir, runId: 'us-priority-run' });

  assert.deepEqual(visited, ['us']);
});

test('resume recalculates derived geography and noise filters for stored candidates', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-rederive-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  await fs.writeFile(path.join(runDir, 'candidates.json'), JSON.stringify([
    { id: 'post-us', post_id: 'us', title: 'Headlight issue in Pensacola', body_original: 'Toyota dealer', subreddit: 'COROLLA', score: 2, comment_count: 1, url: 'https://www.reddit.com/comments/us', geography: { status: 'unknown' }, high_signal: { total: 1, reasons: [] } },
    { id: 'post-cat', post_id: 'cat', title: 'Cat headlight upgrade', body_original: 'markings', subreddit: 'standardissuecat', score: 50, comment_count: 20, url: 'https://www.reddit.com/comments/cat', geography: { status: 'unknown' }, high_signal: { total: 90, reasons: [] } },
  ]), 'utf8');
  const visited = [];
  const adapter = { name: 'fixture', async search() { throw new Error('search should not run'); }, async fetchDetails(post) { visited.push(post.post_id); return { post, comments: [] }; } };

  const result = await runRadarPipeline({ config, adapter, runDir, runId: 'rederive-run' });

  assert.deepEqual(result.candidates.map((post) => post.post_id), ['us']);
  assert.equal(result.candidates[0].geography.status, 'us');
  assert.deepEqual(visited, ['us']);
});

test('resume retries unresolved search queries and preserves the immutable config snapshot', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-search-resume-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const firstConfig = { ...config, query_groups: ['headlight problem', 'headlight replacement'] };
  let retry = false;
  const adapter = {
    name: 'fixture',
    async search(query) {
      if (query === 'headlight problem') return [{ id: 'p1', title: 'F-150 headlight flicker', selftext: 'Texas', subreddit: 'sub0', permalink: '/comments/p1/x' }];
      if (!retry) throw new Error('search rate limited');
      return [{ id: 'p2', title: 'Silverado headlight replacement', selftext: 'Ohio', subreddit: 'sub1', permalink: '/comments/p2/x' }];
    },
    async fetchDetails(post) { return { post, comments: [] }; },
  };

  const first = await runRadarPipeline({ config: firstConfig, adapter, runDir, runId: 'search-resume-run' });
  assert.equal(first.manifest.status, 'partial');
  assert.equal(first.manifest.counts.failures, 1);
  const snapshotBefore = await fs.readFile(path.join(runDir, 'config.snapshot.json'), 'utf8');

  retry = true;
  const changedConfig = { ...firstConfig, query_groups: ['headlight problem', 'new query not in snapshot'] };
  const resumed = await runRadarPipeline({ config: changedConfig, adapter, runDir, runId: 'search-resume-run' });

  assert.equal(resumed.manifest.status, 'complete');
  assert.deepEqual(resumed.candidates.map((post) => post.post_id), ['p1', 'p2']);
  assert.deepEqual(await fs.readFile(path.join(runDir, 'config.snapshot.json'), 'utf8'), snapshotBefore);
  assert.equal((await fs.readFile(path.join(runDir, 'failures.jsonl'), 'utf8')).trim(), '');
});

test('pipeline writes a bounded keyword candidate pool, runs one controlled second round, and keeps formal keywords immutable', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-keyword-round-two-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const searchCalls = [];
  const detailCalls = [];
  const authorCalls = [];
  const keywordConfig = {
    ...config,
    keywords: {
      ...config.keywords,
      expanded: ['headlight condensation', 'canbus adapter'],
      candidate_only_brands: ['SEALIGHT', 'Sylvania'],
    },
    limits: {
      ...config.limits,
      posts: 5,
      deep_dive_posts: 5,
      profile_users: 3,
      profile_items_per_user: 4,
      total_profile_items: 6,
      round_two_terms: 20,
      round_two_posts_per_term: 10,
      round_two_minimum_score: 65,
      round_two_minimum_users: 2,
      round_two_minimum_communities: 2,
    },
    market_rules: {
      dictionaries: {
        products: ['headlight protective film', 'vent membrane', 'canbus adapter'],
        vehicles: ['f-150', 'silverado'],
        fitment: ['h11'],
        competitors: ['sealight'],
        retailers: ['amazon'],
        slang: ['condensation', 'flicker'],
        stopwords: ['light', 'lights', 'car', 'cars'],
      },
    },
    query_groups: ['headlight condensation'],
  };
  const before = structuredClone(keywordConfig.keywords);
  const adapter = {
    name: 'fixture',
    async search(query, options = {}) {
      searchCalls.push({ query, limit: options.limit });
      if (query === 'headlight condensation') {
        return [
          { id: 'p1', title: 'I bought headlight protective film after condensation returned on my F-150', selftext: 'Budget under $80 and the old vent membrane kit failed.', subreddit: 'sub0', score: 25, num_comments: 8, permalink: '/comments/p1/x', author: 'alice' },
          { id: 'p2', title: 'I bought a vent membrane for my Silverado headlight leak', selftext: 'The condensation came back after I installed new bulbs, so I need a better vent membrane before I replace the assembly again. Budget is under $120.', subreddit: 'sub1', score: 18, num_comments: 5, permalink: '/comments/p2/x', author: 'bob' },
        ];
      }
      if (query === 'headlight protective film') {
        return [
          { id: 'p3', title: 'Protective film kept my headlights clear', selftext: 'F-150 owner here. Bought it after another condensation leak.', subreddit: 'sub2', score: 19, num_comments: 6, permalink: '/comments/p3/x', author: 'carol' },
        ];
      }
      if (query === 'condensation' || query === 'vent membrane') {
        return [];
      }
      throw new Error(`unexpected query: ${query}`);
    },
    async fetchDetails(post) {
      detailCalls.push(post.post_id);
      const details = {
        p1: {
          post: { id: 'p1', title: 'I bought headlight protective film after condensation returned on my F-150', selftext: 'Budget under $80 and the old vent membrane kit failed.', subreddit: 'sub0', score: 25, num_comments: 8, permalink: '/comments/p1/x', author: 'alice' },
          comments: [{ id: 'c1', body: 'I bought headlight protective film after a vent kit failed.', score: 7, permalink: '/comments/p1/x/c1', author: 'alice' }],
        },
        p2: {
          post: { id: 'p2', title: 'I bought a vent membrane for my Silverado headlight leak', selftext: 'The condensation came back after I installed new bulbs, so I need a better vent membrane before I replace the assembly again. Budget is under $120.', subreddit: 'sub1', score: 18, num_comments: 5, permalink: '/comments/p2/x', author: 'bob' },
          comments: [{ id: 'c2', body: 'SEALIGHT bulbs did not solve the condensation, but a vent membrane might.', score: 6, permalink: '/comments/p2/x/c2', author: 'bob' }],
        },
        p3: {
          post: { id: 'p3', title: 'Protective film kept my headlights clear', selftext: 'F-150 owner here. Bought it after another condensation leak.', subreddit: 'sub2', score: 19, num_comments: 6, permalink: '/comments/p3/x', author: 'carol' },
          comments: [{ id: 'c3', body: 'The film worked better than another assembly for me.', score: 5, permalink: '/comments/p3/x/c3', author: 'carol' }],
        },
      };
      return details[post.post_id];
    },
    async fetchAuthorActivity(username, options = {}) {
      authorCalls.push({ username, limit: options.limit });
      return [
        { id: `${username}-activity`, kind: 't3', data: { id: `${username}-activity`, author: username, subreddit: username === 'alice' ? 'F150' : 'Cartalk', title: 'Headlight protective film follow-up', selftext: 'I bought headlight protective film after the condensation returned.', permalink: `/r/Cartalk/comments/${username}-activity/x`, created_utc: 1_787_529_600 } },
      ];
    },
  };

  const result = await runRadarPipeline({ config: keywordConfig, adapter, runDir, runId: 'keyword-round-two-run' });

  assert.deepEqual(keywordConfig.keywords, before);
  assert.deepEqual(searchCalls, [
    { query: 'headlight condensation', limit: 15 },
    { query: 'headlight protective film', limit: 10 },
    { query: 'condensation', limit: 10 },
    { query: 'vent membrane', limit: 10 },
  ]);
  assert.deepEqual(authorCalls, [
    { username: 'alice', limit: 4 },
    { username: 'bob', limit: 4 },
  ]);
  assert.equal(detailCalls.includes('p3'), true);
  assert.equal(result.candidates.some((post) => post.post_id === 'p3'), true);

  const keywordCandidates = JSON.parse(await fs.readFile(path.join(runDir, 'keyword_candidates.json'), 'utf8'));
  assert.equal(keywordCandidates.candidates.some((candidate) => candidate.term === 'headlight protective film'), true);
  assert.equal(keywordCandidates.candidates.find((candidate) => candidate.term === 'headlight protective film')?.status, 'exploratory_used');
  assert.equal(keywordCandidates.candidates.some((candidate) => candidate.term === 'sealight'), false);

  const checkpoint = JSON.parse(await fs.readFile(path.join(runDir, 'round_two_checkpoint.json'), 'utf8'));
  assert.deepEqual(checkpoint.selected_terms, ['headlight protective film', 'condensation', 'vent membrane']);
  assert.equal(checkpoint.completed_rounds, 1);
  assert.equal(checkpoint.failures.length, 0);
  assert.equal(result.manifest.counts.keyword_candidates >= 2, true);
  assert.equal(result.manifest.counts.round_two_terms, 3);
  assert.equal(result.manifest.counts.round_two_additions, 1);
});

test('pipeline resumes the round-two checkpoint, retries only failed exploratory queries, and keeps the first-round snapshot intact', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-keyword-resume-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  let retryRoundTwo = false;
  const searchCalls = [];
  const keywordConfig = {
    ...config,
    keywords: {
      ...config.keywords,
      expanded: ['headlight condensation'],
      candidate_only_brands: [],
    },
    limits: {
      ...config.limits,
      posts: 4,
      deep_dive_posts: 4,
      profile_users: 2,
      profile_items_per_user: 3,
      total_profile_items: 3,
      round_two_terms: 20,
      round_two_posts_per_term: 10,
      round_two_minimum_score: 65,
      round_two_minimum_users: 2,
      round_two_minimum_communities: 2,
    },
    market_rules: {
      dictionaries: {
        products: ['headlight protective film', 'vent membrane'],
        vehicles: ['f-150', 'silverado'],
        fitment: ['h11'],
        competitors: [],
        retailers: ['amazon'],
        slang: ['condensation'],
        stopwords: ['light', 'lights'],
      },
    },
    query_groups: ['headlight condensation'],
  };
  const adapter = {
    name: 'fixture',
    async search(query, options = {}) {
      searchCalls.push({ query, limit: options.limit });
      if (query === 'headlight condensation') {
        return [
          { id: 'p1', title: 'I bought headlight protective film after condensation returned on my F-150', selftext: 'Budget under $80 and the old vent membrane kit failed.', subreddit: 'sub0', score: 25, num_comments: 8, permalink: '/comments/p1/x', author: 'alice' },
          { id: 'p2', title: 'I bought a vent membrane for my Silverado headlight leak', selftext: 'The condensation came back after I installed new bulbs, so I need a better vent membrane before I replace the assembly again. Budget is under $120.', subreddit: 'sub1', score: 18, num_comments: 5, permalink: '/comments/p2/x', author: 'bob' },
        ];
      }
      if (query === 'headlight protective film') {
        if (!retryRoundTwo) throw new Error('temporary round-two throttle');
        return [
          { id: 'p3', title: 'Protective film kept my headlights clear', selftext: 'F-150 owner here. Bought it after another condensation leak.', subreddit: 'sub2', score: 19, num_comments: 6, permalink: '/comments/p3/x', author: 'carol' },
        ];
      }
      if (query === 'condensation' || query === 'vent membrane') {
        return [];
      }
      throw new Error(`unexpected query: ${query}`);
    },
    async fetchDetails(post) {
      const details = {
        p1: {
          post: { id: 'p1', title: 'I bought headlight protective film after condensation returned on my F-150', selftext: 'Budget under $80 and the old vent membrane kit failed.', subreddit: 'sub0', score: 25, num_comments: 8, permalink: '/comments/p1/x', author: 'alice' },
          comments: [{ id: 'c1', body: 'I bought headlight protective film after a vent kit failed.', score: 7, permalink: '/comments/p1/x/c1', author: 'alice' }],
        },
        p2: {
          post: { id: 'p2', title: 'I bought a vent membrane for my Silverado headlight leak', selftext: 'The condensation came back after I installed new bulbs, so I need a better vent membrane before I replace the assembly again. Budget is under $120.', subreddit: 'sub1', score: 18, num_comments: 5, permalink: '/comments/p2/x', author: 'bob' },
          comments: [{ id: 'c2', body: 'A vent membrane might stop the leak.', score: 6, permalink: '/comments/p2/x/c2', author: 'bob' }],
        },
        p3: {
          post: { id: 'p3', title: 'Protective film kept my headlights clear', selftext: 'F-150 owner here. Bought it after another condensation leak.', subreddit: 'sub2', score: 19, num_comments: 6, permalink: '/comments/p3/x', author: 'carol' },
          comments: [{ id: 'c3', body: 'The film worked better than another assembly for me.', score: 5, permalink: '/comments/p3/x/c3', author: 'carol' }],
        },
      };
      return details[post.post_id];
    },
    async fetchAuthorActivity(username) {
      return [
        { id: `${username}-activity`, kind: 't3', data: { id: `${username}-activity`, author: username, subreddit: username === 'alice' ? 'F150' : 'Cartalk', title: 'Headlight protective film follow-up', selftext: 'I bought headlight protective film after the condensation returned.', permalink: `/r/Cartalk/comments/${username}-activity/x`, created_utc: 1_787_529_600 } },
      ];
    },
  };

  const first = await runRadarPipeline({ config: keywordConfig, adapter, runDir, runId: 'keyword-resume-run' });
  const snapshotBefore = await fs.readFile(path.join(runDir, 'config.snapshot.json'), 'utf8');
  assert.equal(first.manifest.status, 'partial');
  assert.equal(first.manifest.counts.round_two_failures, 1);

  retryRoundTwo = true;
  const resumed = await runRadarPipeline({
    config: {
      ...keywordConfig,
      query_groups: ['a different seed should not replace the stored first-round snapshot'],
    },
    adapter,
    runDir,
    runId: 'keyword-resume-run',
  });

  assert.deepEqual(searchCalls, [
    { query: 'headlight condensation', limit: 15 },
    { query: 'headlight protective film', limit: 10 },
    { query: 'condensation', limit: 10 },
    { query: 'vent membrane', limit: 10 },
    { query: 'headlight protective film', limit: 10 },
  ]);
  assert.equal(resumed.manifest.status, 'complete');
  assert.equal(resumed.manifest.counts.round_two_failures, 0);
  assert.equal(resumed.candidates.some((post) => post.post_id === 'p3'), true);
  assert.deepEqual(await fs.readFile(path.join(runDir, 'config.snapshot.json'), 'utf8'), snapshotBefore);
  const checkpoint = JSON.parse(await fs.readFile(path.join(runDir, 'round_two_checkpoint.json'), 'utf8'));
  assert.deepEqual(checkpoint.failures, []);
  assert.equal(checkpoint.results.some((post) => post.post_id === 'p3'), true);
});

function jsonResponse(value) {
  return {
    ok: true,
    status: 200,
    async json() { return value; },
    async text() { return JSON.stringify(value); },
  };
}

function errorResponse(status, value) {
  return { ok: false, status, async text() { return value; } };
}

function textResponse(value) {
  return { ok: true, status: 200, async text() { return value; }, async json() { throw new Error('not json'); } };
}

function fixtureAdapter({ failBad = true } = {}) {
  const adapter = {
    name: 'fixture',
    visited: [],
    async search() {
      return [
        { id: 'p1', title: 'F-150 headlight flicker', selftext: 'Texas, what should I buy?', subreddit: 'sub0', score: 20, num_comments: 12, permalink: '/comments/p1/x' },
        { id: 'p1', title: 'F-150 headlight flicker', selftext: 'duplicate', subreddit: 'sub0', score: 1, num_comments: 1, permalink: '/comments/p1/x' },
        { id: 'bad', title: 'Silverado fog light problem', selftext: 'Ohio install issue', subreddit: 'sub1', score: 8, num_comments: 4, permalink: '/comments/bad/x' },
      ];
    },
    async fetchDetails(post) {
      adapter.visited.push(post.post_id);
      if (post.post_id === 'bad' && failBad) throw new Error('rate limited');
      return {
        post: { id: post.post_id, title: post.title, selftext: post.body_original, subreddit: post.subreddit, score: post.score, num_comments: post.comment_count, permalink: post.url },
        comments: [{ id: `c-${post.post_id}`, body: 'The adapter solved my flicker issue', score: 10, permalink: `/comments/${post.post_id}/x/c1` }],
      };
    },
  };
  return adapter;
}
