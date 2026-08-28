import fs from 'node:fs/promises';

const REDDIT_ORIGIN = 'https://www.reddit.com';

export async function loadLightingConfig(configPath) {
  const raw = await fs.readFile(configPath, 'utf8');
  const config = JSON.parse(raw);
  const required = ['market', 'keywords', 'subreddits', 'limits'];
  for (const key of required) {
    if (!config[key]) throw new Error(`Config missing required section: ${key}`);
  }
  if (config.market.country !== 'US') throw new Error('Lighting pilot config must target US');
  if (!Array.isArray(config.keywords.anchors) || config.keywords.anchors.length !== 14) {
    throw new Error('Lighting pilot config must preserve exactly 14 anchor keywords');
  }
  if (config.limits.posts < 30 || config.limits.posts > 200) {
    throw new Error('Pilot post limit must be between 30 and 200');
  }
  if (config.limits.comments_per_post > 20) {
    throw new Error('Pilot comment limit must not exceed 20');
  }
  if (config.subreddits.length < 10 || config.subreddits.length > 15) {
    throw new Error('Pilot subreddit list must contain 10 to 15 communities');
  }
  return config;
}

function asRedditUrl(value, fallbackId = '') {
  if (typeof value === 'string' && /^https?:\/\//i.test(value)) {
    const parsed = new URL(value);
    return `${REDDIT_ORIGIN}${parsed.pathname}`;
  }
  if (typeof value === 'string' && value.startsWith('/')) return `${REDDIT_ORIGIN}${value}`;
  return fallbackId ? `${REDDIT_ORIGIN}/comments/${fallbackId}` : '';
}

export function normalizePost(input, source = {}) {
  const post = input?.data ?? input ?? {};
  const id = String(post.id ?? post.post_id ?? '').replace(/^t3_/, '');
  const created = Number(post.created_utc ?? post.created ?? 0);
  return {
    id: `post-${id}`,
    post_id: id,
    subreddit: String(post.subreddit ?? '').replace(/^r\//i, ''),
    title: String(post.title ?? '').trim(),
    body_original: String(post.selftext ?? post.body ?? '').trim(),
    author: post.author && post.author !== '[deleted]' ? String(post.author) : null,
    score: Number(post.score ?? post.ups ?? 0) || 0,
    comment_count: Number(post.num_comments ?? post.comment_count ?? 0) || 0,
    created_at: created > 0 ? new Date(created * 1000).toISOString() : null,
    url: asRedditUrl(post.permalink ?? post.url, id),
    query: source.query ?? null,
    source: {
      transport: source.transport ?? 'unknown',
      collected_at: source.collected_at ?? new Date().toISOString(),
    },
  };
}

export function dedupePosts(posts) {
  const byId = new Map();
  for (const post of posts) {
    const key = post.post_id || post.url;
    if (!key) continue;
    const existing = byId.get(key);
    const weight = (post.score ?? 0) + (post.comment_count ?? 0) * 2;
    const existingWeight = existing ? (existing.score ?? 0) + (existing.comment_count ?? 0) * 2 : -1;
    if (!existing || weight > existingWeight) byId.set(key, post);
  }
  return [...byId.values()];
}

export function scorePost(post) {
  const text = `${post.title ?? ''}\n${post.body_original ?? ''}`.toLowerCase();
  const reasons = [];
  let total = Math.min(20, Math.log2(Math.max(1, (post.score ?? 0) + 1)) * 3);
  total += Math.min(25, Math.log2(Math.max(1, (post.comment_count ?? 0) + 1)) * 5);

  const pain = /(dim|flicker|error code|warning|glare|blinding|condensation|fogging|water|overheat|burn(?:ed|t)? out|failed|failure|problem|issue|doesn'?t fit|not fit|hard to install|poor beam)/i;
  const purchase = /(what should i buy|recommend|replacement|upgrade|under \$?\d+|budget|worth it|which (?:bulb|light|brand)|looking for|where can i buy)/i;
  const comparison = /\b(vs\.?|versus|better than|alternative|switched from|oem|aftermarket)\b/i;
  const fitment = /\b(h11|9005|9006|h7|h4|9012|h13|canbus|f-?150|silverado|ram|wrangler|tacoma)\b/i;
  if (pain.test(text)) { total += 25; reasons.push('pain-language'); }
  if (purchase.test(text)) { total += 20; reasons.push('purchase-signal'); }
  if (comparison.test(text)) { total += 12; reasons.push('comparison-language'); }
  if (fitment.test(text)) { total += 8; reasons.push('fitment-signal'); }
  return { total: Math.max(0, Math.min(100, Math.round(total))), reasons };
}

function normalizeComment(comment, postId) {
  const item = comment?.data ?? comment ?? {};
  const id = String(item.id ?? '').replace(/^t1_/, '');
  const created = Number(item.created_utc ?? item.created ?? 0);
  return {
    id: `comment-${id}`,
    comment_id: id,
    post_id: postId,
    author: item.author && item.author !== '[deleted]' ? String(item.author) : null,
    body_original: String(item.body ?? '').trim(),
    score: Number(item.score ?? item.ups ?? 0) || 0,
    created_at: created > 0 ? new Date(created * 1000).toISOString() : null,
    url: asRedditUrl(item.permalink ?? item.url, postId),
  };
}

export function normalizeAuthorActivity(input, { username = null, transport = 'unknown', collectedAt = new Date().toISOString() } = {}) {
  const item = input?.data ?? input ?? {};
  const activityType = inferAuthorActivityType(input, item);
  const id = String(item.id ?? item.activity_id ?? '').replace(/^t[13]_/, '');
  const createdAt = normalizeTimestamp(item.created_at ?? item.createdAt ?? item.created_utc ?? item.created);

  return {
    id: input?.activity_type ? String(input.id ?? '') : `${activityType}-${id}`,
    activity_id: id,
    activity_type: activityType,
    username: username ?? (item.author && item.author !== '[deleted]' ? String(item.author) : null),
    author: item.author && item.author !== '[deleted]' ? String(item.author) : (username ?? null),
    subreddit: String(item.subreddit ?? '').replace(/^r\//i, ''),
    title: activityType === 'post' ? String(item.title ?? '').trim() : String(item.title ?? '').replace(/^\/u\/[^ ]+\s+on\s+/i, '').trim(),
    body_original: String(item.selftext ?? item.body ?? item.body_original ?? '').trim(),
    score: Number(item.score ?? item.ups ?? 0) || 0,
    created_at: createdAt,
    url: asRedditUrl(item.permalink ?? item.url, id),
    source: {
      transport,
      collected_at: collectedAt,
    },
  };
}

export function flattenRedditComments(children, output = []) {
  for (const child of children ?? []) {
    if (!child || child.kind === 'more') continue;
    const data = child.data ?? child;
    if (data.body) output.push(data);
    const replies = data.replies?.data?.children ?? data.replies?.children ?? [];
    flattenRedditComments(replies, output);
  }
  return output;
}

export function normalizeComments(comments, { postId, limit = 20 } = {}) {
  return [...comments]
    .map((comment) => normalizeComment(comment, postId))
    .filter((comment) => comment.comment_id && comment.body_original)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

export async function collectDetails(candidates, fetcher) {
  const items = [];
  const failures = [];
  for (const post of candidates) {
    try {
      items.push(await fetcher(post));
    } catch (error) {
      failures.push({
        post_id: post.post_id,
        stage: 'detail-fetch',
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }
  return { items, failures };
}

export function classifyUsRelevance(text) {
  const value = String(text ?? '').toLowerCase();
  const nonUs = /\b(mot|united kingdom|\buk\b|cartalkuk|canada|ontario|australia|europe|eu inspection|carsph|philippines|i20[_ -]?india|\bindia\b)\b/i;
  const us = /\b(usa|u\.s\.|united states|texas|california|florida|pensacola|new york|ohio|michigan|pennsylvania|illinois|arizona|georgia|north carolina|f-?150|silverado|tacoma|wrangler|crown ?victoria)\b/i;
  if (nonUs.test(value)) return { status: 'non_us', confidence: 0.9, signals: value.match(nonUs) ?? [] };
  if (us.test(value)) return { status: 'us', confidence: 0.8, signals: value.match(us) ?? [] };
  return { status: 'unknown', confidence: 0, signals: [] };
}

export function buildAudienceMap(analysis) {
  const nodes = [];
  const edges = [];
  const communityStats = new Map();

  for (const opportunity of analysis.opportunities ?? []) {
    const entryType = opportunity.opportunity_type === 'adjacent_bundle' ? 'adjacent_bundle' : 'formal_opportunity';
    nodes.push({
      id: opportunity.id,
      type: 'product',
      entry_type: entryType,
      label: opportunity.label,
      category: opportunity.category,
      size: opportunity.opportunity_score,
      opportunity_score: opportunity.opportunity_score,
      product_count: 1,
      formal_product_count: entryType === 'formal_opportunity' ? 1 : 0,
      adjacent_product_count: entryType === 'adjacent_bundle' ? 1 : 0,
      fitment_tags: opportunity.fitment_tags ?? [],
      pain_points: opportunity.pain_points ?? [],
      solution_ideas: opportunity.solution_ideas ?? [],
      evidence_ids: opportunity.evidence_ids ?? [],
    });
    for (const subreddit of opportunity.communities ?? []) {
      const normalizedSubreddit = String(subreddit).toLowerCase();
      const communityId = `community-${normalizedSubreddit}`;
      const stat = communityStats.get(communityId) ?? {
        id: communityId,
        type: 'community',
        entry_type: 'community',
        label: `r/${subreddit}`,
        subreddit,
        products: new Set(),
        evidence: new Set(),
        formalProducts: new Set(),
        adjacentProducts: new Set(),
      };
      stat.products.add(opportunity.id);
      if (entryType === 'formal_opportunity') stat.formalProducts.add(opportunity.id);
      if (entryType === 'adjacent_bundle') stat.adjacentProducts.add(opportunity.id);
      const edgeEvidence = new Set();
      for (const evidenceId of opportunity.evidence_ids ?? []) {
        const evidence = (analysis.evidence ?? []).find((item) => item.id === evidenceId);
        if (evidence?.subreddit?.toLowerCase() === normalizedSubreddit) {
          stat.evidence.add(evidenceId);
          edgeEvidence.add(evidenceId);
        }
      }
      communityStats.set(communityId, stat);
      edges.push({
        id: `${opportunity.id}__${communityId}`,
        source: opportunity.id,
        source_type: 'product',
        target: communityId,
        target_type: 'community',
        evidence_ids: [...edgeEvidence],
      });
    }
  }

  for (const stat of communityStats.values()) {
    nodes.push({
      id: stat.id,
      type: 'community',
      entry_type: 'community',
      label: stat.label,
      subreddit: stat.subreddit,
      size: stat.products.size,
      product_count: stat.products.size,
      formal_product_count: stat.formalProducts.size,
      adjacent_product_count: stat.adjacentProducts.size,
      evidence_ids: [...stat.evidence],
    });
  }

  return {
    schema_version: '1.0.0',
    generated_at: new Date().toISOString(),
    nodes,
    edges,
    filters: {
      categories: [...new Set(nodes.filter((node) => node.type === 'product').map((node) => node.category).filter(Boolean))],
      entry_types: ['adjacent_bundle', 'formal_opportunity'],
    },
  };
}

function inferAuthorActivityType(input, item) {
  const kind = String(input?.kind ?? item?.kind ?? item?.name ?? '').toLowerCase();
  if (kind.startsWith('t1') || item.body || input?.activity_type === 'comment') return 'comment';
  return 'post';
}

function normalizeTimestamp(value) {
  if (!value && value !== 0) return null;
  if (typeof value === 'string') {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : new Date(parsed).toISOString();
  }
  if (Number.isFinite(value)) {
    const milliseconds = value > 9_999_999_999 ? value : value * 1000;
    return new Date(milliseconds).toISOString();
  }
  return null;
}
