import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  buildAudienceMap,
  classifyUsRelevance,
  collectDetails,
  dedupePosts,
  loadLightingConfig,
  normalizeAuthorActivity,
  normalizeComments,
  normalizePost,
  scorePost,
} from '../src/radar-core.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');

test('lighting pilot config preserves 14 anchors and full-category limits', async () => {
  const config = await loadLightingConfig(path.join(repoRoot, 'configs', 'automotive_lighting_us_pilot.json'));

  assert.equal(config.market.country, 'US');
  assert.equal(config.keywords.anchors.length, 14);
  assert.ok(config.keywords.anchors.includes('headlight bulb'));
  assert.ok(config.keywords.anchors.includes('h13 headlight bulb'));
  assert.ok(config.keywords.expanded.includes('fog light'));
  assert.ok(config.keywords.expanded.includes('tail light'));
  assert.ok(config.keywords.expanded.includes('CANbus adapter'));
  const queryText = config.query_groups.join(' ').toLowerCase();
  for (const anchor of config.keywords.anchors) assert.ok(queryText.includes(anchor.toLowerCase()), anchor);
  assert.ok(config.limits.posts >= 30 && config.limits.posts <= 200);
  assert.equal(config.limits.deep_dive_posts, 12);
  assert.equal(config.limits.comments_per_post, 20);
  assert.ok(config.subreddits.length >= 10 && config.subreddits.length <= 15);
});

test('normalizePost creates a canonical Reddit record', () => {
  const post = normalizePost({
    id: 'abc123',
    subreddit: 'MechanicAdvice',
    title: 'H11 LED flickering after install',
    selftext: 'Installed on my Ford F-150 in Texas.',
    author: 'example_user',
    score: 21,
    num_comments: 12,
    created_utc: 1_700_000_000,
    permalink: '/r/MechanicAdvice/comments/abc123/h11_led_flickering/',
  }, { query: 'h11 headlight bulb', transport: 'fixture' });

  assert.equal(post.post_id, 'abc123');
  assert.equal(post.subreddit, 'MechanicAdvice');
  assert.equal(post.url, 'https://www.reddit.com/r/MechanicAdvice/comments/abc123/h11_led_flickering/');
  assert.equal(post.score, 21);
  assert.equal(post.comment_count, 12);
  assert.equal(post.source.transport, 'fixture');
});

test('dedupePosts keeps the strongest copy of a canonical post', () => {
  const weak = normalizePost({ id: 'same', title: 'Dim headlights', score: 2, num_comments: 1, permalink: '/comments/same/x' });
  const strong = normalizePost({ id: 'same', title: 'Dim headlights', score: 15, num_comments: 9, permalink: '/comments/same/x' });

  const result = dedupePosts([weak, strong]);

  assert.equal(result.length, 1);
  assert.equal(result[0].score, 15);
  assert.equal(result[0].comment_count, 9);
});

test('scorePost ranks pain and purchase language above a generic mention', () => {
  const generic = normalizePost({ id: 'g', title: 'Headlights', selftext: 'Photo of my car', score: 1, num_comments: 0 });
  const signal = normalizePost({
    id: 's',
    title: 'Need help: LED headlights flicker and throw an error code',
    selftext: 'What should I buy under $100 that actually fits my F-150?',
    score: 25,
    num_comments: 18,
  });

  assert.ok(scorePost(signal).total > scorePost(generic).total);
  assert.ok(scorePost(signal).reasons.includes('pain-language'));
  assert.ok(scorePost(signal).reasons.includes('purchase-signal'));
});

test('normalizeComments caps output and preserves English evidence links', () => {
  const comments = Array.from({ length: 25 }, (_, index) => ({
    id: `c${index}`,
    author: `u${index}`,
    body: `Comment ${index}`,
    score: 25 - index,
    created_utc: 1_700_000_000 + index,
    permalink: `/r/cars/comments/p1/x/c${index}/`,
  }));

  const normalized = normalizeComments(comments, { postId: 'p1', limit: 20 });

  assert.equal(normalized.length, 20);
  assert.equal(normalized[0].body_original, 'Comment 0');
  assert.match(normalized[0].url, /^https:\/\/www\.reddit\.com\//);
});

test('normalizeAuthorActivity creates a canonical author activity record for posts and comments', () => {
  const post = normalizeAuthorActivity({
    kind: 't3',
    data: {
      id: 'post1',
      author: 'writer',
      subreddit: 'Cartalk',
      title: 'F-150 headlight condensation',
      selftext: 'Still comparing vent kits in Texas.',
      score: 12,
      permalink: '/r/Cartalk/comments/post1/x',
      created_utc: 1_700_000_000,
    },
  }, { username: 'writer', transport: 'fixture' });
  const comment = normalizeAuthorActivity({
    kind: 't1',
    data: {
      id: 'comment1',
      author: 'writer',
      subreddit: 'Cartalk',
      body: 'My H11 bulbs still flicker.',
      score: 5,
      permalink: '/r/Cartalk/comments/post1/x/comment1',
      created_utc: 1_700_000_100,
    },
  }, { username: 'writer', transport: 'fixture' });

  assert.equal(post.activity_type, 'post');
  assert.equal(post.username, 'writer');
  assert.equal(post.body_original, 'Still comparing vent kits in Texas.');
  assert.equal(comment.activity_type, 'comment');
  assert.equal(comment.title, '');
  assert.match(comment.url, /comment1/);
});

test('collectDetails records an item failure and continues', async () => {
  const candidates = [{ post_id: 'one' }, { post_id: 'bad' }, { post_id: 'three' }];
  const visited = [];
  const fetcher = async (post) => {
    visited.push(post.post_id);
    if (post.post_id === 'bad') throw new Error('rate limited');
    return { post, comments: [] };
  };

  const result = await collectDetails(candidates, fetcher);

  assert.deepEqual(visited, ['one', 'bad', 'three']);
  assert.equal(result.items.length, 2);
  assert.equal(result.failures.length, 1);
  assert.equal(result.failures[0].post_id, 'bad');
});

test('classifyUsRelevance separates explicit US evidence from unknown geography', () => {
  assert.equal(classifyUsRelevance('F-150 headlight inspection in Texas').status, 'us');
  assert.equal(classifyUsRelevance('Toyota dealer in Pensacola denied the warranty').status, 'us');
  assert.equal(classifyUsRelevance('My headlights are dim').status, 'unknown');
  assert.equal(classifyUsRelevance('MOT failed in the UK').status, 'non_us');
  assert.equal(classifyUsRelevance('CarsPH projector retrofit').status, 'non_us');
  assert.equal(classifyUsRelevance('i20_India headlight upgrade').status, 'non_us');
  assert.equal(classifyUsRelevance('CarTalkUK headlight bulb price').status, 'non_us');
  assert.equal(classifyUsRelevance('CrownVictoria headlight assembly').status, 'us');
});

test('buildAudienceMap creates only product-community edges with evidence', () => {
  const analysis = {
    opportunities: [{
      id: 'product-led-upgrade',
      label: 'LED headlight upgrade',
      category: 'headlight',
      opportunity_score: 72,
      fitment_tags: ['H11'],
      pain_points: ['flicker'],
      solution_ideas: ['CANbus-safe driver'],
      evidence_ids: ['post-1'],
      communities: ['MechanicAdvice'],
    }],
    evidence: [{ id: 'post-1', subreddit: 'MechanicAdvice', url: 'https://www.reddit.com/comments/1' }],
  };

  const map = buildAudienceMap(analysis);

  assert.equal(map.nodes.filter((node) => node.type === 'product').length, 1);
  assert.equal(map.nodes.filter((node) => node.type === 'community').length, 1);
  assert.equal(map.edges.length, 1);
  assert.equal(map.edges[0].source_type, 'product');
  assert.equal(map.edges[0].target_type, 'community');
  assert.deepEqual(map.edges[0].evidence_ids, ['post-1']);
});

test('buildAudienceMap keeps evidence scoped to the current product-community edge', () => {
  const analysis = {
    opportunities: [
      { id: 'product-a', label: 'A', category: 'headlight', opportunity_score: 70, evidence_ids: ['post-a'], communities: ['Cars'] },
      { id: 'product-b', label: 'B', category: 'fog-light', opportunity_score: 60, evidence_ids: ['post-b'], communities: ['Cars'] },
    ],
    evidence: [
      { id: 'post-a', subreddit: 'Cars', url: 'https://www.reddit.com/comments/a' },
      { id: 'post-b', subreddit: 'Cars', url: 'https://www.reddit.com/comments/b' },
    ],
  };
  const map = buildAudienceMap(analysis);
  assert.deepEqual(map.edges.find((edge) => edge.source === 'product-a').evidence_ids, ['post-a']);
  assert.deepEqual(map.edges.find((edge) => edge.source === 'product-b').evidence_ids, ['post-b']);
});

test('buildAudienceMap separates formal opportunities from adjacent bundles without changing product-community edges', () => {
  const analysis = {
    opportunities: [
      {
        id: 'formal-a',
        label: 'Formal A',
        category: 'headlight',
        opportunity_type: 'validated_entry',
        opportunity_score: 70,
        evidence_ids: ['post-a'],
        communities: ['Cars'],
      },
      {
        id: 'adjacent-b',
        label: 'Adjacent B',
        category: 'protection',
        opportunity_type: 'adjacent_bundle',
        opportunity_score: 55,
        evidence_ids: ['post-b'],
        communities: ['Cars'],
      },
    ],
    evidence: [
      { id: 'post-a', subreddit: 'Cars', url: 'https://www.reddit.com/comments/a' },
      { id: 'post-b', subreddit: 'Cars', url: 'https://www.reddit.com/comments/b' },
    ],
  };

  const map = buildAudienceMap(analysis);
  const formalNode = map.nodes.find((node) => node.id === 'formal-a');
  const adjacentNode = map.nodes.find((node) => node.id === 'adjacent-b');
  const communityNode = map.nodes.find((node) => node.id === 'community-cars');

  assert.equal(formalNode.type, 'product');
  assert.equal(formalNode.entry_type, 'formal_opportunity');
  assert.equal(adjacentNode.type, 'product');
  assert.equal(adjacentNode.entry_type, 'adjacent_bundle');
  assert.equal(communityNode.formal_product_count, 1);
  assert.equal(communityNode.adjacent_product_count, 1);
  assert.deepEqual(map.filters.entry_types, ['adjacent_bundle', 'formal_opportunity']);
  assert.equal(map.edges.every((edge) => edge.source_type === 'product' && edge.target_type === 'community'), true);
});
