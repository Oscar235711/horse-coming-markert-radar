import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

import {
  classifyUsRelevance,
  dedupePosts,
  flattenRedditComments,
  normalizeAuthorActivity,
  normalizeComments,
  normalizePost,
  scorePost,
} from './radar-core.mjs';
import { applyEvidenceGate } from './evidence-quality.mjs';
import { collectAuthorActivity, selectAuthors } from './author-deep-dive.mjs';
import {
  extractKeywordCandidates,
  scoreKeywordCandidates,
  selectRoundTwoTerms,
} from './keyword-discovery.mjs';
import {
  hashStageInput,
  readStageCheckpoint,
  writeStageCheckpoint,
} from './checkpoint-store.mjs';

const execFileAsync = promisify(execFile);

const OPTIMIZATION_ITEMS = [
  ['doctor-backend-mismatch', 'doctor', 'Agent Reach may report Reddit off while OpenCLI is installed', 'Doctor output can misrepresent the usable local transport', 'Check OpenCLI independently and report transport-level health', 'high', 'open'],
  ['hardcoded-opencli', 'collection', 'Legacy detail script still invokes bare opencli; the new radar adapter uses a resolved executable path', 'Portable installs can fail in the legacy detail command despite a valid configured path', 'Route scripts/fetch-details.ps1 and scripts/deep-dive.ps1 through the resolved executable path', 'high', 'open'],
  ['diesel-only-config', 'configuration', 'The tracked baseline only supplied a diesel research configuration', 'Lighting research could not be reproduced', 'Add a US automotive-lighting pilot config while preserving diesel history', 'high', 'resolved'],
  ['missing-orchestrator', 'collection', 'No unified scan, rank, deep-dive, and resume orchestrator existed', 'Runs required manual handoffs and stopped on failures', 'Use the checkpointed pipeline runner', 'critical', 'resolved'],
  ['missing-html', 'reporting', 'Only an Excel evidence generator existed', 'The requested interactive seller report was unavailable', 'Generate one offline HTML from analysis JSON', 'high', 'resolved'],
  ['schema-gap', 'data-contract', 'Schemas did not cover normalized comments or Audience Map graph data', 'Downstream report behavior was not contract-tested', 'Add normalized evidence and graph schemas', 'high', 'resolved'],
  ['missing-actions', 'remote-execution', 'No GitHub Actions workflow could invoke a remote run', 'The repository was storage-only for remote users', 'Add manual and scheduled workflows with artifacts', 'high', 'resolved'],
  ['public-json-blocked', 'remote-execution', 'Reddit returned HTTP 403 for unauthenticated JSON on the first real pilot', 'A GitHub-hosted or local public run can produce zero candidates', 'Fall back to Reddit Atom RSS while preserving the failure boundary', 'critical', 'mitigated'],
  ['rss-metadata-limited', 'remote-execution', 'Reddit RSS may omit score and comment-count metadata', 'RSS-only opportunity ranking has lower engagement fidelity', 'Prefer JSON/OpenCLI when available and label RSS-derived evidence', 'medium', 'open'],
  ['author-activity-gap', 'audience-analysis', 'The pilot currently normalizes public author handles but does not fetch author history', 'Behavior segments are based on in-scope post/comment evidence rather than a broader public activity sample', 'Add an adapter-level author activity endpoint with a strict automotive-relevance filter and retention cap', 'medium', 'resolved'],
];

export function buildOpenCliSearchArgs(query, { limit = 15, subreddit = '' } = {}) {
  const args = ['reddit', 'search', query, '--sort', 'relevance', '--time', 'year', '--limit', String(limit), '-f', 'json', '--window', 'background', '--site-session', 'persistent'];
  if (subreddit) args.push('--subreddit', subreddit);
  return args;
}

function decodeXml(value) {
  return String(value ?? '')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
    .replaceAll('&apos;', "'")
    .replaceAll('&amp;', '&')
    .replace(/&#(x?[0-9a-f]+);/gi, (_, code) => String.fromCodePoint(code.toLowerCase().startsWith('x') ? Number.parseInt(code.slice(1), 16) : Number.parseInt(code, 10)));
}

function stripHtml(value) {
  return decodeXml(value).replace(/<br\s*\/?\s*>/gi, '\n').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

function tagValue(entry, name) {
  const match = entry.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${name}>`, 'i'));
  return match ? decodeXml(match[1]).trim() : '';
}

export function parseRedditAtom(xml) {
  const posts = [];
  const comments = [];
  const entries = String(xml ?? '').match(/<entry(?:\s[^>]*)?>[\s\S]*?<\/entry>/gi) ?? [];
  for (const entry of entries) {
    const id = tagValue(entry, 'id');
    const title = stripHtml(tagValue(entry, 'title'));
    const contentMatch = entry.match(/<content(?:\s[^>]*)?>([\s\S]*?)<\/content>/i);
    const body = stripHtml(contentMatch?.[1] ?? '');
    const author = tagValue(entry, 'name').replace(/^\/u\//i, '') || '[deleted]';
    const link = decodeXml(entry.match(/<link\b[^>]*\bhref=["']([^"']+)["'][^>]*\/?\s*>/i)?.[1] ?? '');
    const subreddit = decodeXml(entry.match(/<category\b[^>]*\bterm=["']([^"']+)["'][^>]*\/?\s*>/i)?.[1] ?? '').replace(/^r\//i, '').trim();
    const updated = tagValue(entry, 'updated');
    const createdUtc = updated ? Math.floor(Date.parse(updated) / 1000) : 0;
    if (id.startsWith('t3_')) {
      posts.push({ id: id.slice(3), title, selftext: body, author, subreddit, score: 0, num_comments: 0, created_utc: createdUtc, permalink: link });
    } else if (id.startsWith('t1_')) {
      comments.push({ id: id.slice(3), body, author, subreddit, score: 0, created_utc: createdUtc, permalink: link });
    }
  }
  return { posts, comments };
}

export function createPublicJsonAdapter({ fetchImpl = fetch, baseUrl = 'https://old.reddit.com', rssBaseUrl = 'https://www.reddit.com', userAgent = 'reddit-find-compatible/1.0 research tool (github.com/Oscar235711/horse-coming-markert-radar)', retryDelayMs = 15000, sleepImpl = delay } = {}) {
  async function requestJson(url, timeoutMs) {
    const response = await fetchImpl(url, {
      headers: { 'User-Agent': userAgent, Accept: 'application/json' },
      signal: typeof AbortSignal?.timeout === 'function' ? AbortSignal.timeout(timeoutMs) : undefined,
    });
    if (!response.ok) {
      const body = await response.text();
      const error = new Error(`Reddit HTTP ${response.status}: ${body.slice(0, 240)}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  async function requestText(url, timeoutMs) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const response = await fetchImpl(url, {
        headers: { 'User-Agent': userAgent, Accept: 'application/atom+xml, application/xml;q=0.9, text/xml;q=0.8' },
        signal: typeof AbortSignal?.timeout === 'function' ? AbortSignal.timeout(timeoutMs) : undefined,
      });
      if (response.ok) return response.text();
      const body = await response.text();
      if (response.status === 429 && attempt === 0) {
        await sleepImpl(retryDelayMs);
        continue;
      }
      const error = new Error(`Reddit RSS HTTP ${response.status}: ${body.slice(0, 240)}`);
      error.status = response.status;
      throw error;
    }
    throw new Error('Reddit RSS retry exhausted');
  }

  function isBlocked(error) {
    return error?.status === 403 || error?.status === 404 || error?.status === 429;
  }

  return {
    name: 'public-json',
    async search(query, { limit = 15, timeoutMs = 30000 } = {}) {
      const url = new URL('/search.json', baseUrl);
      url.searchParams.set('q', query);
      url.searchParams.set('sort', 'relevance');
      url.searchParams.set('t', 'year');
      url.searchParams.set('limit', String(limit));
      url.searchParams.set('raw_json', '1');
      try {
        const payload = await requestJson(url, timeoutMs);
        return payload?.data?.children?.map((child) => child.data ?? child) ?? [];
      } catch (error) {
        if (!isBlocked(error)) throw error;
        const rssUrl = new URL('/search.rss', rssBaseUrl);
        rssUrl.searchParams.set('q', query);
        rssUrl.searchParams.set('sort', 'relevance');
        rssUrl.searchParams.set('t', 'year');
        rssUrl.searchParams.set('limit', String(limit));
        const xml = await requestText(rssUrl, timeoutMs);
        return parseRedditAtom(xml).posts.slice(0, limit);
      }
    },
    async fetchDetails(post, { commentLimit = 20, timeoutMs = 30000 } = {}) {
      const url = new URL(`/comments/${post.post_id}.json`, baseUrl);
      url.searchParams.set('limit', String(commentLimit));
      url.searchParams.set('depth', '4');
      url.searchParams.set('sort', 'top');
      url.searchParams.set('raw_json', '1');
      try {
        const payload = await requestJson(url, timeoutMs);
        const rawPost = payload?.[0]?.data?.children?.[0]?.data ?? post;
        const rawComments = flattenRedditComments(payload?.[1]?.data?.children ?? []);
        rawComments.sort((a, b) => Number(b.score ?? 0) - Number(a.score ?? 0));
        return { post: rawPost, comments: rawComments.slice(0, commentLimit) };
      } catch (error) {
        if (!isBlocked(error)) throw error;
        const sourceUrl = new URL(post.url || `/comments/${post.post_id}`, rssBaseUrl);
        const pathname = sourceUrl.pathname.endsWith('/') ? sourceUrl.pathname : `${sourceUrl.pathname}/`;
        const rssUrl = new URL(`${pathname}.rss`, rssBaseUrl);
        const parsed = parseRedditAtom(await requestText(rssUrl, timeoutMs));
        const rawPost = parsed.posts.find((item) => item.id === post.post_id) ?? parsed.posts[0] ?? post;
        return { post: rawPost, comments: parsed.comments.slice(0, commentLimit) };
      }
    },
    async fetchAuthorActivity(username, { limit = 50, afterUtc = null, timeoutMs = 30000 } = {}) {
      const url = new URL(`/user/${encodeURIComponent(username)}/overview.json`, baseUrl);
      url.searchParams.set('limit', String(limit));
      url.searchParams.set('raw_json', '1');
      try {
        const payload = await requestJson(url, timeoutMs);
        return finalizeAuthorActivityItems(
          payload?.data?.children?.map((child) => child.data ? child : { kind: child.kind, data: child.data ?? child }) ?? [],
          { limit, afterUtc },
        );
      } catch (error) {
        if (!isBlocked(error)) throw error;
        const [submitted, comments] = await Promise.allSettled([
          requestText(new URL(`/user/${encodeURIComponent(username)}/submitted.rss`, rssBaseUrl), timeoutMs),
          requestText(new URL(`/user/${encodeURIComponent(username)}/comments.rss`, rssBaseUrl), timeoutMs),
        ]);
        const rows = [];
        const reasons = [];
        if (submitted.status === 'fulfilled') {
          rows.push(...parseRedditAtom(submitted.value).posts.map((post) => ({ kind: 't3', data: post })));
        } else {
          reasons.push(submitted.reason);
        }
        if (comments.status === 'fulfilled') {
          rows.push(...parseRedditAtom(comments.value).comments.map((comment) => ({ kind: 't1', data: comment })));
        } else {
          reasons.push(comments.reason);
        }
        if (!rows.length) throw reasons[0] ?? error;
        return finalizeAuthorActivityItems(rows, { limit, afterUtc });
      }
    },
  };
}

export function createOpenCliAdapter({ executablePath, execImpl = execFileAsync } = {}) {
  if (!executablePath) throw new Error('OpenCLI executable path is required');
  async function invoke(args) {
    const invocation = buildOpenCliInvocation(executablePath, args);
    const { stdout } = await execImpl(invocation.file, invocation.args, {
      encoding: 'utf8',
      maxBuffer: 20 * 1024 * 1024,
      windowsHide: true,
      ...invocation.options,
    });
    const value = String(stdout).trim();
    if (!value.startsWith('[') && !value.startsWith('{')) throw new Error(`OpenCLI returned non-JSON output: ${value.slice(0, 240)}`);
    return JSON.parse(value);
  }
  return {
    name: 'opencli',
    async search(query, { limit = 15 } = {}) {
      const payload = await invoke(buildOpenCliSearchArgs(query, { limit }));
      return Array.isArray(payload) ? payload : payload.items ?? [];
    },
    async fetchDetails(post, { commentLimit = 20 } = {}) {
      const args = ['reddit', 'read', post.post_id, '-f', 'json', '--window', 'background', '--site-session', 'persistent', '--limit', String(commentLimit), '--depth', '4', '--replies', '10', '--expand-more', 'false', '--max-length', '5000'];
      const payload = await invoke(args);
      const rows = Array.isArray(payload) ? payload : payload.items ?? [];
      const openCliPost = rows.find((row) => {
        const type = String(row.type ?? row.kind ?? '').toLowerCase();
        return type === 'post' || row.title || row.selftext;
      });
      const rawPost = openCliPost
        ? { ...post, ...openCliPost, body: openCliPost.text ?? post.selftext ?? post.body ?? '', subreddit: openCliPost.subreddit ?? post.subreddit ?? '' }
        : post;
      const postSubreddit = String(rawPost.subreddit ?? '').replace(/^r\//i, '');
      const canonicalPostUrl = `https://www.reddit.com/r/${postSubreddit}/comments/${post.post_id}/`;
      if (!rawPost.url || !/^https?:/i.test(rawPost.url) || rawPost.url.startsWith('https://www.reddit.com/comments/')) {
        rawPost.url = canonicalPostUrl;
      }
      if (!rawPost.permalink) {
        rawPost.permalink = `/r/${postSubreddit}/comments/${post.post_id}/`;
      }
      const commentRows = rows.filter((row) => {
        const type = String(row.type ?? '').toLowerCase();
        const text = String(row.text ?? '').trim();
        return type.startsWith('l') && text.length > 0 && !/^\[\+?\d+ more (?:replies|top-level comments)\]$/i.test(text) && !/^\[\+?\d+ more(?: replies)?\]$/i.test(text);
      });
      const commentIdentityCounts = new Map();
      const comments = commentRows
        .map((row) => {
          const body = String(row.text ?? '').trim();
          return {
            row,
            body,
            identity: stableSyntheticCommentIdentity(post.post_id, body),
          };
        })
        .sort((left, right) => (
          left.identity.sort_key.localeCompare(right.identity.sort_key)
          || String(left.row.author ?? '').localeCompare(String(right.row.author ?? ''))
          || Number(right.row.score ?? 0) - Number(left.row.score ?? 0)
        ))
        .map(({ row, body, identity }) => {
          const occurrence = (commentIdentityCounts.get(identity.hash) ?? 0) + 1;
          commentIdentityCounts.set(identity.hash, occurrence);
          const commentId = `${post.post_id}-cmt-${identity.hash}${occurrence > 1 ? `-${occurrence}` : ''}`;
          return {
            id: commentId,
            comment_id: commentId,
            post_id: post.post_id,
            author: row.author && row.author !== '[deleted]' ? String(row.author) : null,
            body_original: body,
            body,
            score: Number(row.score ?? 0) || 0,
            created_at: null,
            url: `https://www.reddit.com/r/${String(post.subreddit ?? '').replace(/^r\//i, '')}/comments/${post.post_id}/`,
            precision: 'limited',
            link_precision: 'post',
          };
        });
      return { post: rawPost, comments: comments.slice(0, commentLimit) };
    },
    async fetchAuthorActivity(username, { limit = 50, afterUtc = null } = {}) {
      const postLimit = Math.max(1, Math.ceil(limit / 2));
      const commentLimit = Math.max(1, limit - postLimit);
      const [postsResult, commentsResult] = await Promise.allSettled([
        invoke(['reddit', 'user-posts', username, '--limit', String(postLimit), '-f', 'json', '--window', 'background', '--site-session', 'persistent']),
        invoke(['reddit', 'user-comments', username, '--limit', String(commentLimit), '-f', 'json', '--window', 'background', '--site-session', 'persistent']),
      ]);
      const rows = [];
      const reasons = [];
      if (postsResult.status === 'fulfilled') {
        const items = Array.isArray(postsResult.value) ? postsResult.value : postsResult.value.items ?? [];
        rows.push(...items.map((item) => ({ kind: 't3', data: item })));
      } else {
        reasons.push(postsResult.reason);
      }
      if (commentsResult.status === 'fulfilled') {
        const items = Array.isArray(commentsResult.value) ? commentsResult.value : commentsResult.value.items ?? [];
        rows.push(...items.map((item) => ({ kind: 't1', data: item })));
      } else {
        reasons.push(commentsResult.reason);
      }
      if (!rows.length) throw reasons[0] ?? new Error(`No public activity returned for ${username}`);
      return finalizeAuthorActivityItems(rows, { limit, afterUtc });
    },
  };
}

export function buildOpenCliInvocation(executablePath, args, {
  platform = process.platform,
  comSpec = process.env.ComSpec || 'cmd.exe',
} = {}) {
  const normalizedPath = String(executablePath ?? '');
  const normalizedArgs = Array.isArray(args) ? args.map((value) => String(value)) : [];
  const baseOptions = { shell: false };
  if (platform !== 'win32' || !/\.(?:cmd|bat)$/i.test(normalizedPath)) {
    return { file: normalizedPath, args: normalizedArgs, options: baseOptions };
  }

  return {
    file: comSpec,
    args: ['/d', '/c', 'call', path.resolve(normalizedPath), ...normalizedArgs],
    options: baseOptions,
  };
}

async function readJsonIfExists(filePath) {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'));
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

async function writeJsonl(filePath, rows) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const text = rows.length ? `${rows.map((row) => JSON.stringify(row)).join('\n')}\n` : '';
  await fs.writeFile(filePath, text, 'utf8');
}

async function readJsonlIfExists(filePath) {
  try {
    const text = await fs.readFile(filePath, 'utf8');
    return text
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
}

async function appendJsonl(filePath, rows) {
  if (!rows.length) return;
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.appendFile(filePath, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`, 'utf8');
}

function delay(milliseconds) {
  if (!milliseconds) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function deriveCandidates(posts, config) {
  const allowed = new Set(config.subreddits.map((subreddit) => subreddit.toLowerCase()));
  const automotiveLighting = /\b(headlights?|headlamps?|fog lights?|tail ?lights?|brake lights?|turn signals?|daytime running lights?|drl|light bars?|projector retrofit|canbus|f-?150|silverado|tacoma|wrangler|car|truck|vehicle)\b/i;
  const irrelevantCommunity = /^(standardissuecat|cats?|formula1|f1technical|flashlight|flashlights|gardening|houseplants)$/i;
  const geographyRank = { us: 2, unknown: 1, non_us: 0 };
  return dedupePosts(posts)
    .filter((post) => !irrelevantCommunity.test(post.subreddit))
    .filter((post) => !post.subreddit || allowed.has(post.subreddit.toLowerCase()) || automotiveLighting.test(`${post.title}\n${post.body_original}`))
    .map((post) => ({
      ...post,
      high_signal: scorePost(post),
      geography: classifyUsRelevance(`${post.subreddit}\n${post.title}\n${post.body_original}`),
    }))
    .filter((post) => post.geography.status !== 'non_us')
    .sort((a, b) => geographyRank[b.geography.status] - geographyRank[a.geography.status] || b.high_signal.total - a.high_signal.total)
    .slice(0, config.limits.posts);
}

export async function runRadarPipeline({ config, adapter, runDir, runId = new Date().toISOString().replace(/[:.]/g, '-'), now = () => new Date() }) {
  if (!config || !adapter || !runDir) throw new Error('config, adapter, and runDir are required');
  await fs.mkdir(runDir, { recursive: true });
  const detailsDir = path.join(runDir, 'raw', 'details');
  await fs.mkdir(detailsDir, { recursive: true });
  const configSnapshotPath = path.join(runDir, 'config.snapshot.json');
  const configSnapshot = await readJsonIfExists(configSnapshotPath);
  if (!configSnapshot) await writeJson(configSnapshotPath, config);
  const configDriftDetected = configSnapshot
    ? hashStageInput(configSnapshot) !== hashStageInput(config)
    : false;
  const failureAttemptsPath = path.join(runDir, 'failure_attempts.jsonl');
  const historicalAttempts = await readJsonlIfExists(failureAttemptsPath);
  const attemptCounts = new Map();
  for (const attempt of historicalAttempts) {
    const key = failureKey(attempt);
    attemptCounts.set(key, Math.max(attemptCounts.get(key) ?? 0, Number(attempt.attempt ?? 0)));
  }
  await writeJsonl(path.join(runDir, 'optimization_backlog.jsonl'), OPTIMIZATION_ITEMS.map(([id, stage, issue, impact, recommendation, priority, status]) => ({ id, stage, issue, evidence: issue, impact, recommendation, priority, status })));

  const candidatePath = path.join(runDir, 'candidates.json');
  const unresolvedFailurePath = path.join(runDir, 'failures.jsonl');
  const searchFailurePath = path.join(runDir, 'search_failures.json');
  const keywordCandidatePath = path.join(runDir, 'keyword_candidates.json');
  const roundTwoCheckpointPath = path.join(runDir, 'round_two_checkpoint.json');
  const previousUnresolvedFailures = await readJsonlIfExists(unresolvedFailurePath);
  const resumeLockedToSnapshot = previousUnresolvedFailures.length > 0 && configSnapshot;
  const activeConfig = resumeLockedToSnapshot ? configSnapshot : config;
  const failures = [];
  const rawPosts = [];
  const storedCandidates = await readJsonIfExists(candidatePath);
  const previousSearchFailures = (await readJsonIfExists(searchFailurePath)) ?? [];
  const hasPendingSearchFailures = previousSearchFailures.length > 0;
  const queryCacheEntries = [];
  let hasSearchCheckpoint = false;
  for (const query of activeConfig.query_groups) {
    const inputHash = hashStageInput({
      stage: 'search-query',
      query,
      transport: adapter.name,
      search_results_per_query: activeConfig.limits.search_results_per_query,
      market: activeConfig.market,
      subreddits: activeConfig.subreddits,
    });
    const checkpoint = await readStageCheckpoint(runDir, 'search-query', inputHash, '1.0.0');
    queryCacheEntries.push({ query, inputHash, checkpoint });
    if (checkpoint) {
      hasSearchCheckpoint = true;
      rawPosts.push(...(checkpoint.results ?? []));
    }
  }
  const canReuseStoredCandidates = Array.isArray(storedCandidates)
    && (resumeLockedToSnapshot || hasPendingSearchFailures || (!hasSearchCheckpoint && !configDriftDetected));
  if (canReuseStoredCandidates) rawPosts.push(...storedCandidates);
  const searchFailures = [];
  const queriesToRun = hasPendingSearchFailures
    ? previousSearchFailures.map((item) => item.query).filter(Boolean).map((query) => ({
      query,
      inputHash: hashStageInput({
        stage: 'search-query',
        query,
        transport: adapter.name,
        search_results_per_query: activeConfig.limits.search_results_per_query,
        market: activeConfig.market,
        subreddits: activeConfig.subreddits,
      }),
      checkpoint: null,
    }))
    : resumeLockedToSnapshot
      ? []
      : queryCacheEntries;
  for (const entry of queriesToRun) {
    if (!hasPendingSearchFailures && (entry.checkpoint || canReuseStoredCandidates)) continue;
    try {
      const results = await adapter.search(entry.query, {
        limit: activeConfig.limits.search_results_per_query,
        timeoutMs: activeConfig.transport?.timeout_ms ?? 30000,
      });
      const normalized = results.map((post) => normalizePost(post, {
        query: entry.query,
        transport: adapter.name,
      }));
      rawPosts.push(...normalized);
      await writeStageCheckpoint(runDir, 'search-query', entry.inputHash, '1.0.0', {
        schema_version: '1.0.0',
        query: entry.query,
        results: normalized,
      });
    } catch (error) {
      const failure = await recordFailureAttempt({
        attemptsPath: failureAttemptsPath,
        attemptCounts,
        stage: 'search',
        transport: adapter.name,
        now,
        identifiers: { query: entry.query },
        error,
      });
      failures.push(failure);
      searchFailures.push({ query: entry.query, error: failure.message });
    }
    await delay(activeConfig.transport?.request_interval_ms ?? 0);
  }
  let candidates = deriveCandidates(rawPosts, activeConfig);
  await writeJson(searchFailurePath, searchFailures);
  await writeJson(candidatePath, candidates);

  let details = await collectCandidateDetails({
    candidates,
    adapter,
    config: activeConfig,
    detailsDir,
    failures,
    failureAttemptsPath,
    attemptCounts,
    now,
    configDriftDetected,
  });

  const authorSelectionEvidence = buildAuthorSelectionEvidence(details);
  const gatedAuthorEvidence = applyEvidenceGate(authorSelectionEvidence, {
    market: activeConfig.market,
    marketRules: activeConfig.market_rules,
  });
  const authorCandidates = selectAuthors(gatedAuthorEvidence.qualified, {
    limit: activeConfig.limits?.profile_users ?? 60,
  });
  await cleanupAuthorCheckpoints(runDir, authorCandidates);
  const authorActivity = typeof adapter.fetchAuthorActivity === 'function'
    ? await collectAuthorActivity(authorCandidates, adapter, {
      runDir,
      limitAuthors: activeConfig.limits?.profile_users ?? 60,
      limitPerAuthor: activeConfig.limits?.profile_items_per_user ?? 50,
      maxTotalActivities: activeConfig.limits?.total_profile_items
        ?? (activeConfig.limits?.profile_users ?? 60) * (activeConfig.limits?.profile_items_per_user ?? 50),
      timeoutMs: activeConfig.transport?.timeout_ms ?? 30000,
      afterUtc: new Date(now().getTime() - 180 * 24 * 60 * 60 * 1000).toISOString(),
      market: activeConfig.market,
      marketRules: activeConfig.market_rules,
      productTerms: [
        ...(activeConfig.keywords?.anchors ?? []),
        ...(activeConfig.keywords?.expanded ?? []),
      ],
      dictionaries: activeConfig.market_rules?.dictionaries ?? {},
    })
    : { authors: [], failures: [], summary: { selected_authors: authorCandidates.length, authors_collected: 0, retained_activities: 0, excluded_activities: 0 } };
  failures.push(...authorActivity.failures);

  const scoredKeywordCandidates = scoreKeywordCandidates(
    extractKeywordCandidates(gatedAuthorEvidence.qualified, authorActivity.authors, activeConfig),
    activeConfig,
  );
  const roundTwoTerms = selectRoundTwoTerms(scoredKeywordCandidates, {
    maxTerms: activeConfig.limits?.round_two_terms ?? 20,
    minimumScore: activeConfig.limits?.round_two_minimum_score ?? 65,
    minimumUsers: activeConfig.limits?.round_two_minimum_users ?? 2,
    minimumCommunities: activeConfig.limits?.round_two_minimum_communities ?? 2,
  });
  const roundTwo = await runRoundTwoSearch({
    adapter,
    config: activeConfig,
    runId,
    roundTwoTerms,
    checkpointPath: roundTwoCheckpointPath,
    runDir,
    failureAttemptsPath,
    attemptCounts,
    now,
  });
  failures.push(...roundTwo.failures);

  const usedTerms = new Set(roundTwo.selected_terms);
  const keywordCandidateArtifact = {
    schema_version: '1.0.0',
    run_id: runId,
    generated_at: now().toISOString(),
    selected_terms: roundTwo.selected_terms,
    candidates: scoredKeywordCandidates.map((candidate) => ({
      ...candidate,
      status: usedTerms.has(candidate.term) ? 'exploratory_used' : candidate.status,
    })),
  };
  await writeJson(keywordCandidatePath, keywordCandidateArtifact);

  const roundOneCandidateIds = new Set(candidates.map((post) => post.post_id));
  const combinedRawPosts = [...rawPosts, ...roundTwo.results];
  const combinedCandidates = deriveCandidates(combinedRawPosts, activeConfig);
  const candidateListChanged = combinedCandidates.length !== candidates.length
    || combinedCandidates.some((post, index) => post.post_id !== candidates[index]?.post_id);
  candidates = combinedCandidates;
  await writeJson(candidatePath, candidates);
  if (candidateListChanged) {
    details = await collectCandidateDetails({
      candidates,
      adapter,
      config: activeConfig,
      detailsDir,
      failures,
      failureAttemptsPath,
      attemptCounts,
      now,
      configDriftDetected,
    });
  }
  const deepDiveTarget = inferDeepDiveTarget(activeConfig, candidates.length);
  const roundTwoAdditions = candidates.filter((post) => !roundOneCandidateIds.has(post.post_id)).length;

  await writeJsonl(path.join(runDir, 'failures.jsonl'), failures);
  const cumulativeAttempts = (await readJsonlIfExists(failureAttemptsPath)).length;
  const sampleStatus = inferPipelineSampleStatus({ config: activeConfig, candidates, details });
  const personaStatus = inferPipelinePersonaStatus({
    sampleStatus,
    config: activeConfig,
    authorCandidates,
    authorsCollected: authorActivity.summary.authors_collected,
  });
  const status = inferPipelineStatus({
    failures,
    candidates,
    config: activeConfig,
  });
  const manifest = {
    schema_version: '1.0.0',
    run_id: runId,
    status,
    sample_status: sampleStatus,
    persona_status: personaStatus,
    unresolved_failures: failures.length,
    cumulative_attempts: cumulativeAttempts,
    transport: adapter.name,
    updated_at: now().toISOString(),
    counts: {
      candidates: candidates.length,
      deep_dive_target: deepDiveTarget,
      details: details.length,
      comments: details.reduce((sum, item) => sum + item.comments.length, 0),
      author_candidates: authorCandidates.length,
      authors_collected: authorActivity.summary.authors_collected,
      author_activities: authorActivity.summary.retained_activities,
      keyword_candidates: keywordCandidateArtifact.candidates.length,
      round_two_terms: roundTwo.selected_terms.length,
      round_two_additions: roundTwoAdditions,
      round_two_failures: roundTwo.failures.length,
      failures: failures.length,
      opportunities: 0,
      candidate_signals: 0,
      audience_nodes: 0,
      audience_edges: 0,
      keyword_cloud_terms: 0,
    },
    artifacts: {
      analysis: 'analysis.json',
      evidence: 'evidence.jsonl',
      keyword_candidates: 'keyword_candidates.json',
      audience_map: 'audience_map.json',
      keyword_cloud: 'keyword_cloud.json',
      opportunities: 'opportunities.json',
      personas: 'personas.json',
      quality_evidence: 'quality_evidence.jsonl',
      excluded_evidence: 'excluded_evidence.jsonl',
      manifest: 'manifest.json',
      report: 'report.html',
      optimization_backlog: 'optimization_backlog.jsonl',
      failures: 'failures.jsonl',
    },
  };
  await writeJson(path.join(runDir, 'manifest.json'), manifest);
  return {
    candidates,
    details,
    authorCandidates,
    authorActivity: authorActivity.authors,
    authorFailures: authorActivity.failures,
    failures,
    manifest,
    runDir,
  };
}

async function collectCandidateDetails({
  candidates,
  adapter,
  config,
  detailsDir,
  failures,
  failureAttemptsPath,
  attemptCounts,
  now,
  configDriftDetected,
}) {
  const details = [];
  const deepDiveTarget = inferDeepDiveTarget(config, candidates.length);
  const deepDiveCandidates = (candidates ?? []).slice(0, deepDiveTarget || candidates.length);
  const selectedDetailFiles = new Set(deepDiveCandidates.map((post) => `${post.post_id}.json`));
  for (const file of await fs.readdir(detailsDir)) {
    if (file.endsWith('.json') && !selectedDetailFiles.has(file)) await fs.rm(path.join(detailsDir, file), { force: true });
  }
  for (const post of deepDiveCandidates) {
    const detailPath = path.join(detailsDir, `${post.post_id}.json`);
    const inputHash = hashStageInput({
      stage: 'detail-fetch',
      post_id: post.post_id,
      query: post.query,
      url: post.url,
      transport: adapter.name,
      comments_per_post: config.limits.comments_per_post,
      comment_identity: adapter.name === 'opencli' ? 'synthetic_post_scoped_post_link_only' : 'native_comment_id',
    });
    const checkpoint = await readStageCheckpoint(runDirFromDetailsDir(detailsDir), 'detail-fetch', inputHash, '1.0.0');
    if (checkpoint) {
      await writeJson(detailPath, checkpoint);
      details.push(checkpoint);
      continue;
    }
    const legacyDetail = !configDriftDetected ? await readJsonIfExists(detailPath) : null;
    if (legacyDetail) {
      await writeStageCheckpoint(runDirFromDetailsDir(detailsDir), 'detail-fetch', inputHash, '1.0.0', legacyDetail);
      details.push(legacyDetail);
      continue;
    }
    try {
      const raw = await adapter.fetchDetails(post, {
        commentLimit: config.limits.comments_per_post,
        timeoutMs: config.transport?.timeout_ms ?? 30000,
      });
      const normalizedPost = { ...post, ...normalizePost(raw.post, { query: post.query, transport: adapter.name }), high_signal: post.high_signal, geography: post.geography };
      const normalized = {
        post: normalizedPost,
        comments: normalizeComments(raw.comments ?? [], { postId: post.post_id, limit: config.limits.comments_per_post }),
      };
      await writeStageCheckpoint(runDirFromDetailsDir(detailsDir), 'detail-fetch', inputHash, '1.0.0', normalized);
      await writeJson(detailPath, normalized);
      details.push(normalized);
    } catch (error) {
      failures.push(await recordFailureAttempt({
        attemptsPath: failureAttemptsPath,
        attemptCounts,
        stage: 'detail-fetch',
        transport: adapter.name,
        now,
        identifiers: { post_id: post.post_id },
        error,
      }));
    }
    await delay(config.transport?.request_interval_ms ?? 0);
  }
  return details;
}

function buildAuthorSelectionEvidence(details) {
  const evidence = [];
  for (const detail of details ?? []) {
    const post = detail.post ?? {};
    evidence.push({
      id: post.id,
      type: 'post',
      post_id: post.post_id,
      author: post.author ?? null,
      subreddit: post.subreddit,
      title: post.title,
      body_original: post.body_original ?? post.selftext ?? '',
      url: post.url,
      score: post.score,
      comment_count: post.comment_count,
    });
    for (const comment of detail.comments ?? []) {
      evidence.push({
        id: comment.id,
        type: 'comment',
        post_id: post.post_id,
        author: comment.author ?? null,
        subreddit: post.subreddit,
        body_original: comment.body_original ?? comment.body ?? '',
        url: comment.url,
        score: comment.score,
        ...(comment.precision ? { precision: comment.precision } : {}),
        ...(comment.link_precision ? { link_precision: comment.link_precision } : {}),
      });
    }
  }
  return evidence.filter((item) => item.id);
}

function finalizeAuthorActivityItems(items, { limit, afterUtc }) {
  const cutoff = afterUtc ? Date.parse(afterUtc) : null;
  return (items ?? [])
    .map((item) => normalizeAuthorActivity(item))
    .filter((item) => item.id)
    .filter((item) => !cutoff || !item.created_at || Date.parse(item.created_at) >= cutoff)
    .sort((left, right) => Date.parse(right.created_at ?? 0) - Date.parse(left.created_at ?? 0))
    .slice(0, limit);
}

async function cleanupAuthorCheckpoints(runDir, authorCandidates) {
  const authorsDir = path.join(runDir, 'raw', 'authors');
  await fs.mkdir(authorsDir, { recursive: true });
  const selectedFiles = new Set((authorCandidates ?? []).map((author) => `${safeFilename(author.username)}.json`));
  for (const file of await fs.readdir(authorsDir)) {
    if (!file.endsWith('.json')) continue;
    if (selectedFiles.has(file)) continue;
    const filePath = path.join(authorsDir, file);
    const resolvedDir = path.resolve(authorsDir);
    const resolvedFile = path.resolve(filePath);
    if (!resolvedFile.startsWith(`${resolvedDir}${path.sep}`) && resolvedFile !== path.join(resolvedDir, file)) {
      throw new Error(`Refusing to delete checkpoint outside author directory: ${resolvedFile}`);
    }
    await fs.rm(filePath, { force: true });
  }
}

function safeFilename(value) {
  return String(value).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
}

async function runRoundTwoSearch({
  adapter,
  config,
  runId,
  roundTwoTerms,
  checkpointPath,
  runDir,
  failureAttemptsPath,
  attemptCounts,
  now,
}) {
  const signaturePayload = {
    selected_terms: [...roundTwoTerms],
    max_terms: config.limits?.round_two_terms ?? 20,
    minimum_score: config.limits?.round_two_minimum_score ?? 65,
    max_posts_per_term: config.limits?.round_two_posts_per_term ?? 10,
  };
  const signature = JSON.stringify(signaturePayload);
  const results = [];
  const failures = [];
  for (const query of roundTwoTerms) {
    const inputHash = hashStageInput({
      stage: 'round-two-search',
      query,
      transport: adapter.name,
      round_two_posts_per_term: config.limits?.round_two_posts_per_term ?? 10,
    });
    const checkpoint = await readStageCheckpoint(runDir, 'round-two-search', inputHash, '1.0.0');
    if (checkpoint) {
      results.push(...(checkpoint.results ?? []));
      continue;
    }
    try {
      const rawResults = await adapter.search(query, {
        limit: config.limits?.round_two_posts_per_term ?? 10,
        timeoutMs: config.transport?.timeout_ms ?? 30000,
      });
      const normalized = rawResults.map((post) => normalizePost(post, { query, transport: adapter.name }));
      await writeStageCheckpoint(runDir, 'round-two-search', inputHash, '1.0.0', {
        schema_version: '1.0.0',
        query,
        results: normalized,
      });
      results.push(...normalized);
    } catch (error) {
      failures.push(await recordFailureAttempt({
        attemptsPath: failureAttemptsPath,
        attemptCounts,
        stage: 'round-two-search',
        transport: adapter.name,
        now,
        identifiers: { query },
        error,
      }));
    }
    await delay(config.transport?.request_interval_ms ?? 0);
  }

  const dedupedResults = dedupePosts(results);
  const payload = {
    schema_version: '1.0.0',
    run_id: runId,
    candidate_signature: signature,
    completed_rounds: 1,
    selected_terms: [...roundTwoTerms],
    results: dedupedResults,
    failures: failures.map(({ query, message }) => ({ query, error: message })),
  };
  await writeJson(checkpointPath, payload);
  return { ...payload, failures };
}

function inferDeepDiveTarget(config, candidateCount) {
  if (Number.isFinite(Number(config.limits?.deep_dive_posts))) {
    return Math.max(0, Math.min(candidateCount, Number(config.limits.deep_dive_posts)));
  }
  return candidateCount;
}

function inferMinimumCompleteCandidates(config) {
  if (Number.isFinite(Number(config.limits?.minimum_complete_candidates))) {
    return Math.max(0, Number(config.limits.minimum_complete_candidates));
  }
  return 0;
}

function inferPipelineSampleStatus({ config, candidates }) {
  const minimumCompleteCandidates = inferMinimumCompleteCandidates(config);
  if (!minimumCompleteCandidates) return 'sufficient';
  return candidates.length >= minimumCompleteCandidates ? 'sufficient' : 'insufficient';
}

function inferPipelinePersonaStatus({ sampleStatus, config, authorCandidates, authorsCollected }) {
  if (sampleStatus !== 'sufficient') return 'insufficient_sample';
  const requestedAuthors = Number(config.limits?.profile_users ?? 0);
  if (requestedAuthors <= 0) return 'complete';
  return authorsCollected >= Math.min(requestedAuthors, authorCandidates.length)
    ? 'complete'
    : 'insufficient_sample';
}

function inferPipelineStatus({ failures, candidates, config }) {
  if (failures.length) return 'partial';
  const minimumCompleteCandidates = inferMinimumCompleteCandidates(config);
  if (minimumCompleteCandidates && candidates.length < minimumCompleteCandidates) return 'partial';
  return 'complete';
}

function failureKey(value) {
  return JSON.stringify({
    stage: value.stage,
    query: value.query ?? null,
    post_id: value.post_id ?? null,
    username: value.username ?? null,
  });
}

function stableSyntheticCommentIdentity(postId, body) {
  const normalizedBody = String(body ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  const hash = crypto.createHash('sha256')
    .update(`${postId}\n${normalizedBody}`)
    .digest('hex')
    .slice(0, 12);
  return {
    hash,
    sort_key: `${hash}:${normalizedBody}`,
  };
}

async function recordFailureAttempt({
  attemptsPath,
  attemptCounts,
  stage,
  transport,
  now,
  identifiers,
  error,
}) {
  const key = failureKey({ stage, ...identifiers });
  const attempt = (attemptCounts.get(key) ?? 0) + 1;
  attemptCounts.set(key, attempt);
  const message = error instanceof Error ? error.message : String(error);
  const failure = {
    stage,
    attempt,
    transport,
    occurred_at: now().toISOString(),
    error_category: classifyFailure(message, error),
    retryable: isRetryableFailure(error, message),
    message,
    ...identifiers,
  };
  await appendJsonl(attemptsPath, [failure]);
  return failure;
}

function classifyFailure(message, error) {
  const text = `${message} ${error?.status ?? ''}`.toLowerCase();
  if (/\b(429|rate limit(?:ed)?|throttle|timeout|temporar)/.test(text)) return 'transient';
  if (/\b(403|404|private|deleted|suspended)\b/.test(text)) return 'access';
  return 'runtime';
}

function isRetryableFailure(error, message) {
  if (typeof error?.status === 'number') return error.status === 403 || error.status === 404 || error.status === 429;
  return /\b(rate limit(?:ed)?|throttle|timeout|temporar|private|deleted|suspended|403|404|429)\b/i.test(message);
}

function runDirFromDetailsDir(detailsDir) {
  return path.resolve(detailsDir, '..', '..');
}
