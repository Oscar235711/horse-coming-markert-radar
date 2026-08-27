import fs from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

import {
  classifyUsRelevance,
  dedupePosts,
  flattenRedditComments,
  normalizeComments,
  normalizePost,
  scorePost,
} from './radar-core.mjs';

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
  ['author-activity-gap', 'audience-analysis', 'The pilot currently normalizes public author handles but does not fetch author history', 'Behavior segments are based on in-scope post/comment evidence rather than a broader public activity sample', 'Add an adapter-level author activity endpoint with a strict automotive-relevance filter and retention cap', 'medium', 'open'],
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
  };
}

export function createOpenCliAdapter({ executablePath, execImpl = execFileAsync } = {}) {
  if (!executablePath) throw new Error('OpenCLI executable path is required');
  async function invoke(args) {
    const { stdout } = await execImpl(executablePath, args, {
      encoding: 'utf8',
      maxBuffer: 20 * 1024 * 1024,
      windowsHide: true,
      shell: process.platform === 'win32',
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
      const args = ['reddit', 'read', post.post_id, '-f', 'json', '--window', 'background', '--site-session', 'persistent', '--limit', String(commentLimit), '--depth', '4', '--replies', '10', '--expand-more', 'true', '--expand-rounds', '3', '--max-length', '5000'];
      const payload = await invoke(args);
      const rows = Array.isArray(payload) ? payload : payload.items ?? [];
      const rawPost = rows.find((row) => row.kind === 'post' || row.type === 'post' || row.title) ?? post;
      const comments = rows.filter((row) => row !== rawPost && (row.body || row.type === 'comment' || row.kind === 'comment')).slice(0, commentLimit);
      return { post: rawPost, comments };
    },
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
  if (!(await readJsonIfExists(configSnapshotPath))) await writeJson(configSnapshotPath, config);
  await writeJsonl(path.join(runDir, 'optimization_backlog.jsonl'), OPTIMIZATION_ITEMS.map(([id, stage, issue, impact, recommendation, priority, status]) => ({ id, stage, issue, evidence: issue, impact, recommendation, priority, status })));

  const candidatePath = path.join(runDir, 'candidates.json');
  const searchFailurePath = path.join(runDir, 'search_failures.json');
  let candidates = await readJsonIfExists(candidatePath);
  const previousSearchFailures = (await readJsonIfExists(searchFailurePath)) ?? [];
  const failures = [];
  const rawPosts = candidates ? [...candidates] : [];
  const queriesToRun = candidates
    ? previousSearchFailures.map((item) => item.query).filter(Boolean)
    : config.query_groups;
  const searchFailures = [];
  if (queriesToRun.length) {
    for (const query of queriesToRun) {
      try {
        const results = await adapter.search(query, {
          limit: config.limits.search_results_per_query,
          timeoutMs: config.transport?.timeout_ms ?? 30000,
        });
        rawPosts.push(...results.map((post) => normalizePost(post, { query, transport: adapter.name })));
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        searchFailures.push({ query, error: message });
      }
      await delay(config.transport?.request_interval_ms ?? 0);
    }
  }
  candidates = deriveCandidates(rawPosts, config);
  await writeJson(searchFailurePath, searchFailures);
  failures.push(...searchFailures.map((item) => ({ stage: 'search', ...item })));
  await writeJson(candidatePath, candidates);

  const details = [];
  const deepDiveCandidates = candidates.slice(0, config.limits.deep_dive_posts ?? candidates.length);
  const selectedDetailFiles = new Set(deepDiveCandidates.map((post) => `${post.post_id}.json`));
  for (const file of await fs.readdir(detailsDir)) {
    if (file.endsWith('.json') && !selectedDetailFiles.has(file)) await fs.rm(path.join(detailsDir, file), { force: true });
  }
  for (const post of deepDiveCandidates) {
    const detailPath = path.join(detailsDir, `${post.post_id}.json`);
    const checkpoint = await readJsonIfExists(detailPath);
    if (checkpoint) {
      details.push(checkpoint);
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
      await writeJson(detailPath, normalized);
      details.push(normalized);
    } catch (error) {
      failures.push({ post_id: post.post_id, stage: 'detail-fetch', error: error instanceof Error ? error.message : String(error) });
    }
    await delay(config.transport?.request_interval_ms ?? 0);
  }

  await writeJsonl(path.join(runDir, 'failures.jsonl'), failures);
  const manifest = {
    schema_version: '1.0.0',
    run_id: runId,
    status: failures.length ? 'partial' : 'complete',
    transport: adapter.name,
    updated_at: now().toISOString(),
    counts: {
      candidates: candidates.length,
      deep_dive_target: deepDiveCandidates.length,
      details: details.length,
      comments: details.reduce((sum, item) => sum + item.comments.length, 0),
      failures: failures.length,
    },
  };
  await writeJson(path.join(runDir, 'manifest.json'), manifest);
  return { candidates, details, failures, manifest, runDir };
}
