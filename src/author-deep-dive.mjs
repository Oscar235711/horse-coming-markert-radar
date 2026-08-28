import fs from 'node:fs/promises';
import path from 'node:path';

import { applyEvidenceGate } from './evidence-quality.mjs';
import { normalizeAuthorActivity } from './radar-core.mjs';

const DEFAULT_AUTHOR_LIMIT = 60;
const DEFAULT_ACTIVITY_LIMIT = 50;
const DEFAULT_ACTIVITY_WINDOW_DAYS = 180;
const DEFAULT_PRIVACY_NOTE = 'Only public, research-relevant automotive content is retained; no sensitive demographic attributes are inferred.';
const COMMERCIAL_ACCOUNT = /\b(shop|store|official|coupon|sale|deals?|warehouse|vendor)\b/i;
const MODERATOR_ACCOUNT = /\b(auto moderator|moderator|mod team|modteam)\b/i;
const BOT_ACCOUNT = /\bbot\b/i;
const AUTOMOTIVE_KEYWORDS = [
  'headlight',
  'headlamp',
  'fog light',
  'tail light',
  'brake light',
  'turn signal',
  'drl',
  'daytime running light',
  'light bar',
  'projector',
  'retrofit',
  'housing',
  'bulb',
  'relay',
  'harness',
  'canbus',
  'adapter',
  'fitment',
  'beam pattern',
  'cutoff',
  'condensation',
  'flicker',
  'hyperflash',
  'glare',
  'f-150',
  'silverado',
  'tacoma',
  'wrangler',
  'jeep',
  'toyota',
  'ford',
  'chevrolet',
  'ram',
];
const PAIN_PATTERNS = {
  condensation: /\b(condensation|fogging|moisture|water ingress|leak)\b/i,
  flicker: /\b(flicker|hyperflash|warning light|error code)\b/i,
  fitment: /\b(fitment|doesn'?t fit|does not fit|clearance|dust cap|hard to install|installation issue)\b/i,
  glare: /\b(glare|blinding|beam pattern|cutoff)\b/i,
  dim_output: /\b(dim|poor visibility|weak output|not bright)\b/i,
};
const PRODUCT_CONCEPT_PATTERNS = {
  'led-headlight-bulb-kit': /\b(led headlight|led bulb|headlight bulb|h11|9005|9006|h7|h4|9012|h13)\b/i,
  'canbus-adapter-kit': /\b(canbus|adapter|relay|wiring harness)\b/i,
  'protective-headlight-film': /\b(headlight film|protective film|light film)\b/i,
  'headlight-vent-membrane-kit': /\b(vent kit|vent membrane|breather vent)\b/i,
  'headlight-assembly': /\b(headlight assembly|housing)\b/i,
  'floor-mat-bundle': /\b(floor mat|all weather mat)\b/i,
};
const DISCOVERED_TERM_PATTERNS = [
  /\bheadlight protective film\b/gi,
  /\bprotective film\b/gi,
  /\bvent kit\b/gi,
  /\bvent membrane\b/gi,
  /\bheadlight assembly\b/gi,
  /\bfloor mat\b/gi,
  /\bcanbus adapter\b/gi,
  /\bwiring harness\b/gi,
  /\bh11\b/gi,
  /\b9005\b/gi,
  /\b9006\b/gi,
  /\bf-?150\b/gi,
  /\bsilverado\b/gi,
];
const STATE_PATTERNS = [
  ['Alabama', /\b(?:alabama|al)\b/i],
  ['Arizona', /\b(?:arizona|az)\b/i],
  ['California', /\b(?:california|ca)\b/i],
  ['Florida', /\b(?:florida|fl)\b/i],
  ['Georgia', /\b(?:georgia|ga)\b/i],
  ['Illinois', /\b(?:illinois|il)\b/i],
  ['Michigan', /\b(?:michigan|mi)\b/i],
  ['New York', /\b(?:new york|ny)\b/i],
  ['North Carolina', /\b(?:north carolina|nc)\b/i],
  ['Ohio', /\b(?:ohio|oh)\b/i],
  ['Pennsylvania', /\b(?:pennsylvania|pa)\b/i],
  ['Texas', /\b(?:texas|tx)\b/i],
  ['Washington', /\b(?:washington|wa)\b/i],
];

export function selectAuthors(qualifiedEvidence, { limit = DEFAULT_AUTHOR_LIMIT } = {}) {
  const authors = new Map();

  for (const record of qualifiedEvidence ?? []) {
    if (!isQualifiedAuthorEvidence(record)) continue;
    const username = normalizeUsername(record.author);
    if (!username || isExcludedAccount(username)) continue;

    const entry = authors.get(username) ?? {
      username,
      evidence_ids: new Set(),
      source_post_ids: new Set(),
      high_quality_source_post_count: 0,
      high_quality_evidence_count: 0,
      qualified_record_count: 0,
      score: 0,
    };
    entry.evidence_ids.add(record.id);
    entry.qualified_record_count += 1;
    if (record.type === 'post') entry.source_post_ids.add(record.id);
    if (record.type === 'post' && record.quality?.quality_band === 'high') {
      entry.high_quality_source_post_count += 1;
    }
    if (record.quality?.quality_band === 'high') {
      entry.high_quality_evidence_count += 1;
    }
    entry.score += scoreAuthorEvidence(record);
    authors.set(username, entry);
  }

  return [...authors.values()]
    .filter((entry) => entry.high_quality_source_post_count > 0 && entry.high_quality_evidence_count > 0)
    .sort((left, right) => (
      right.high_quality_source_post_count - left.high_quality_source_post_count
      || right.high_quality_evidence_count - left.high_quality_evidence_count
      || right.score - left.score
      || right.qualified_record_count - left.qualified_record_count
      || left.username.localeCompare(right.username)
    ))
    .slice(0, limit)
    .map((entry) => ({
      username: entry.username,
      evidence_ids: [...entry.evidence_ids].sort(),
      source_post_ids: [...entry.source_post_ids].sort(),
      high_quality_source_post_count: entry.high_quality_source_post_count,
      high_quality_evidence_count: entry.high_quality_evidence_count,
      qualified_record_count: entry.qualified_record_count,
      score: entry.score,
    }));
}

export function retainRelevantActivity(items, context = {}) {
  const retained = [];
  let excludedCount = 0;
  const afterUtc = normalizeIsoDate(context.afterUtc);

  for (const input of items ?? []) {
    const activity = input?.activity_type ? normalizeExistingActivity(input) : normalizeAuthorActivity(input, {
      username: input?.author ?? input?.data?.author ?? context.username ?? null,
      transport: context.transport ?? 'unknown',
    });

    if (!activity.id) {
      excludedCount += 1;
      continue;
    }
    if (afterUtc && activity.created_at && activity.created_at < afterUtc) {
      excludedCount += 1;
      continue;
    }

    const relevanceReasons = collectRelevanceReasons(activity, context);
    if (!relevanceReasons.length) {
      excludedCount += 1;
      continue;
    }

    const quality = classifyActivityQuality(activity, context);
    if (quality.hard_exclusion) {
      excludedCount += 1;
      continue;
    }

    retained.push({
      ...activity,
      relevance_reasons: relevanceReasons,
      quality,
      product_concepts: extractProductConcepts(activity),
      pain_points: extractPainPoints(activity),
      discovered_terms: extractDiscoveredTerms(activity, context),
      self_declared_context: extractSelfDeclaredContext(activity, activity.id),
    });
  }

  retained.sort((left, right) => (
    compareIsoDesc(left.created_at, right.created_at)
    || right.score - left.score
    || left.id.localeCompare(right.id)
  ));

  return { retained, excluded_count: excludedCount };
}

export function extractSelfDeclaredContext(activity, evidenceId) {
  const text = activityText(activity);
  const entries = [];
  const observedAt = activity?.created_at ?? null;
  const permalink = activity?.url ?? null;
  const push = (kind, value) => {
    if (!value || entries.some((item) => item.kind === kind && item.value === value)) return;
    entries.push({
      kind,
      value,
      source: 'self_declared',
      evidence_id: evidenceId,
      permalink,
      observed_at: observedAt,
    });
  };

  const ageMatch = text.match(/\b(?:i am|i'm|im)\s+(\d{2})\b/i);
  if (ageMatch) push('age_band', ageToBand(Number(ageMatch[1])));
  const decadeMatch = text.match(/\bin my (\d{2})s\b/i);
  if (!ageMatch && decadeMatch) push('age_band', decadeToBand(Number(decadeMatch[1])));

  const explicitLocation = extractExplicitLocationText(text);
  if (explicitLocation) {
    push('state', selectStateFromExplicitLocation(explicitLocation));
  }

  const underBudget = text.match(/\b(?:my budget is|budget is|budget's|budget)\s+(under \$\d+(?:\.\d{1,2})?)/i)
    ?? text.match(/\b(under \$\d+(?:\.\d{1,2})?)\b/i);
  if (underBudget) push('budget', underBudget[1].toLowerCase());

  const aroundBudget = text.match(/\b(?:budget is|budget around|around|about)\s+\$ ?(\d+(?:\.\d{1,2})?)/i);
  if (!underBudget && aroundBudget) push('budget', `around $${aroundBudget[1]}`);

  const vehicleMatch = text.match(/\b(f-?150|silverado|tacoma|wrangler|ram 1500|ram 2500|ram 3500|jeep)\b/i);
  if (vehicleMatch && /\b(?:i|my)\b/i.test(text)) push('vehicle', normalizeVehicle(vehicleMatch[1]));

  if (/\b(?:install(?:ing)? .* myself|did it myself|do my own repairs|diy|i wrench)\b/i.test(text)) {
    push('diy_ability', 'DIY');
  }

  const occupationMatch = text.match(/\b(?:i am|i'm|im|as a)\s+(mechanic|installer|technician|shop owner)\b/i);
  if (occupationMatch) push('occupation', occupationMatch[1].toLowerCase());

  return entries.filter((item) => item.kind !== 'occupation' || isOccupationRelevant(text));
}

export async function collectAuthorActivity(authors, adapter, options = {}) {
  if (typeof adapter?.fetchAuthorActivity !== 'function') {
    throw new Error('adapter.fetchAuthorActivity is required');
  }

  const runDir = options.runDir;
  if (!runDir) throw new Error('runDir is required');

  const limitAuthors = Math.min(Number(options.limitAuthors ?? authors?.length ?? DEFAULT_AUTHOR_LIMIT), authors?.length ?? 0);
  const limitPerAuthor = clampPositiveInteger(options.limitPerAuthor, DEFAULT_ACTIVITY_LIMIT);
  const maxTotalActivities = clampPositiveInteger(
    options.maxTotalActivities,
    Math.max(limitAuthors, 1) * limitPerAuthor,
  );
  const afterUtc = normalizeIsoDate(options.afterUtc) ?? new Date(Date.now() - DEFAULT_ACTIVITY_WINDOW_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const timeoutMs = clampPositiveInteger(options.timeoutMs, 30000);
  const now = typeof options.now === 'function' ? options.now : () => new Date();
  const authorsDir = path.join(runDir, 'raw', 'authors');
  const failureAttemptsPath = path.join(runDir, 'failure_attempts.jsonl');
  const historicalAttempts = await readJsonlIfExists(failureAttemptsPath);
  const attemptCounts = new Map();
  for (const attempt of historicalAttempts) {
    const key = failureKey(attempt);
    attemptCounts.set(key, Math.max(attemptCounts.get(key) ?? 0, Number(attempt.attempt ?? 0)));
  }
  await fs.mkdir(authorsDir, { recursive: true });

  const retainedAuthors = [];
  const failures = [];
  let retainedCount = 0;
  let excludedCount = 0;

  for (const author of (authors ?? []).slice(0, limitAuthors)) {
    const username = normalizeUsername(author?.username ?? author?.author);
    if (!username) continue;

    const checkpointPath = path.join(authorsDir, `${safeFilename(username)}.json`);
    const checkpoint = await readJsonIfExists(checkpointPath);
    if (checkpoint) {
      const remainingBudget = maxTotalActivities - retainedCount;
      if (remainingBudget <= 0) break;
      const truncatedCheckpoint = truncateCheckpoint(checkpoint, {
        username,
        sourcePostIds: author?.source_post_ids ?? [],
        sourceEvidenceIds: author?.evidence_ids ?? [],
        limitPerAuthor,
        remainingBudget,
        maxTotalActivities,
        afterUtc,
      });
      retainedAuthors.push(truncatedCheckpoint);
      retainedCount += truncatedCheckpoint.retained_activity.length;
      excludedCount += truncatedCheckpoint.excluded_count ?? 0;
      await fs.writeFile(checkpointPath, `${JSON.stringify(truncatedCheckpoint, null, 2)}\n`, 'utf8');
      continue;
    }

    const remainingBudget = maxTotalActivities - retainedCount;
    if (remainingBudget <= 0) break;
    const requestLimit = Math.min(limitPerAuthor, remainingBudget);

    try {
      const rawItems = await adapter.fetchAuthorActivity(username, {
        limit: requestLimit,
        afterUtc,
        timeoutMs,
      });
      const normalizedItems = normalizeFetchedItems(rawItems, {
        username,
        transport: adapter.name ?? 'unknown',
        afterUtc,
      }).slice(0, requestLimit);
      const kept = retainRelevantActivity(normalizedItems, {
        ...options,
        username,
        afterUtc,
        transport: adapter.name ?? 'unknown',
      });
      const retained = kept.retained.slice(0, requestLimit);
      retainedCount += retained.length;
      excludedCount += kept.excluded_count;

      const payload = {
        schema_version: '1.0.0',
        username,
        source_post_ids: [...new Set(author?.source_post_ids ?? [])].sort(),
        source_evidence_ids: [...new Set(author?.evidence_ids ?? [])].sort(),
        retained_count: retained.length,
        excluded_count: kept.excluded_count,
        limits: {
          requested_limit: requestLimit,
          applied_after_utc: afterUtc,
          max_total_activities: maxTotalActivities,
        },
        retained_activity: retained,
        privacy_note: DEFAULT_PRIVACY_NOTE,
      };
      await fs.writeFile(checkpointPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
      retainedAuthors.push(payload);
    } catch (error) {
      failures.push(await recordFailureAttempt({
        attemptsPath: failureAttemptsPath,
        attemptCounts,
        stage: 'author-activity',
        transport: adapter.name ?? 'unknown',
        now,
        username,
        error,
      }));
    }
  }

  return {
    authors: retainedAuthors,
    failures,
    summary: {
      selected_authors: Math.min(limitAuthors, authors?.length ?? 0),
      authors_collected: retainedAuthors.length,
      retained_activities: retainedCount,
      excluded_activities: excludedCount,
      limit_per_author: limitPerAuthor,
      max_total_activities: maxTotalActivities,
      after_utc: afterUtc,
    },
  };
}

function truncateCheckpoint(checkpoint, {
  username,
  sourcePostIds,
  sourceEvidenceIds,
  limitPerAuthor,
  remainingBudget,
  maxTotalActivities,
  afterUtc,
}) {
  const retained = (checkpoint?.retained_activity ?? [])
    .map((item) => normalizeExistingActivity(item))
    .filter((item) => item.id)
    .filter((item) => !afterUtc || !item.created_at || item.created_at >= afterUtc)
    .sort((left, right) => compareIsoDesc(left.created_at, right.created_at) || right.score - left.score)
    .slice(0, Math.min(limitPerAuthor, remainingBudget));

  return {
    schema_version: checkpoint?.schema_version ?? '1.0.0',
    username,
    source_post_ids: [...new Set([
      ...(sourcePostIds ?? []),
      ...(checkpoint?.source_post_ids ?? []),
    ])].sort(),
    source_evidence_ids: [...new Set(sourceEvidenceIds)].sort(),
    retained_count: retained.length,
    excluded_count: Number(checkpoint?.excluded_count ?? 0),
    limits: {
      requested_limit: Math.min(limitPerAuthor, remainingBudget),
      applied_after_utc: afterUtc,
      max_total_activities: maxTotalActivities,
    },
    retained_activity: retained,
    privacy_note: checkpoint?.privacy_note ?? DEFAULT_PRIVACY_NOTE,
  };
}

function classifyActivityQuality(activity, context) {
  return applyEvidenceGate([activity], {
    market: context.market,
    marketRules: context.marketRules,
  }).qualified[0]?.quality
    ?? applyEvidenceGate([activity], {
      market: context.market,
      marketRules: context.marketRules,
    }).excluded[0]?.quality
    ?? null;
}

function isQualifiedAuthorEvidence(record) {
  const quality = record?.quality ?? {};
  return Boolean(record?.id)
    && Boolean(normalizeUsername(record?.author))
    && quality.hard_exclusion !== true
    && quality.eligible === true
    && ['high', 'medium'].includes(quality.quality_band)
    && ['direct_experience', 'qualified_practitioner', 'market_observation'].includes(quality.evidence_role);
}

function scoreAuthorEvidence(record) {
  const quality = record?.quality ?? {};
  const bandScore = quality.quality_band === 'high' ? 100 : 60;
  const sourcePostBonus = record.type === 'post' ? 25 : 0;
  const engagement = Number(record.score ?? 0) + Number(record.comment_count ?? 0);
  return bandScore + sourcePostBonus + Math.min(engagement, 25);
}

function isExcludedAccount(username) {
  const normalized = String(username).replace(/[_-]+/g, ' ');
  return COMMERCIAL_ACCOUNT.test(normalized) || MODERATOR_ACCOUNT.test(normalized) || BOT_ACCOUNT.test(normalized);
}

function normalizeExistingActivity(activity) {
  const createdAt = normalizeIsoDate(activity.created_at);
  return {
    ...activity,
    username: normalizeUsername(activity.username ?? activity.author) ?? activity.username ?? activity.author ?? null,
    author: normalizeUsername(activity.author ?? activity.username) ?? activity.author ?? activity.username ?? null,
    subreddit: String(activity.subreddit ?? '').replace(/^r\//i, '').trim(),
    title: String(activity.title ?? '').trim(),
    body_original: String(activity.body_original ?? '').trim(),
    created_at: createdAt,
    url: String(activity.url ?? '').trim(),
    score: Number(activity.score ?? 0) || 0,
    source: normalizeActivitySource(activity.source, createdAt),
  };
}

function collectRelevanceReasons(activity, context) {
  const text = activityText(activity);
  const lowered = text.toLowerCase();
  const reasons = [];
  const productTerms = buildTermList(context.productTerms, context.dictionaries);

  if (!productTerms.length && !AUTOMOTIVE_KEYWORDS.some((term) => lowered.includes(term.replace('-', '')) || lowered.includes(term))) {
    return [];
  }

  if (productTerms.some((term) => containsTerm(text, term))) reasons.push('product_term');
  if ((context.dictionaries?.vehicles ?? []).some((term) => containsTerm(text, term))) reasons.push('vehicle_context');
  if ((context.dictionaries?.fitment ?? []).some((term) => containsTerm(text, term))) reasons.push('fitment_context');
  if ((context.dictionaries?.slang ?? []).some((term) => containsTerm(text, term))) reasons.push('community_vocabulary');
  if ((context.dictionaries?.products ?? []).some((term) => containsTerm(text, term))) reasons.push('product_context');
  if (/\b(budget|under \$|around \$|recommend|looking for|what should i buy|worth it|buy|bought|paid)\b/i.test(text)) reasons.push('purchase_behavior');
  if (/\b(installed|install|fixed|repair|replaced|swap|upgrade|retrofit)\b/i.test(text)) reasons.push('installation_or_repair');
  if (/\b(mechanicadvice|cartalk|f150|silverado|wrangler|askmechanics|projectcar)\b/i.test(String(activity.subreddit ?? ''))) reasons.push('market_community');
  if (!reasons.length && AUTOMOTIVE_KEYWORDS.some((term) => containsTerm(text, term))) reasons.push('automotive_context');

  return [...new Set(reasons)];
}

function extractProductConcepts(activity) {
  const text = activityText(activity);
  return Object.entries(PRODUCT_CONCEPT_PATTERNS)
    .filter(([, pattern]) => pattern.test(text))
    .map(([concept]) => concept);
}

function extractPainPoints(activity) {
  const text = activityText(activity);
  return Object.entries(PAIN_PATTERNS)
    .filter(([, pattern]) => pattern.test(text))
    .map(([pain]) => pain);
}

function extractDiscoveredTerms(activity, context) {
  const text = activityText(activity);
  const terms = [];
  for (const term of buildTermList(context.productTerms, context.dictionaries)) {
    if (containsTerm(text, term)) terms.push(term.toLowerCase());
  }
  for (const pattern of DISCOVERED_TERM_PATTERNS) {
    for (const match of text.match(pattern) ?? []) {
      terms.push(match.toLowerCase().replace(/\s+/g, ' ').trim());
    }
  }
  return [...new Set(terms)].sort();
}

function normalizeFetchedItems(items, { username, transport, afterUtc }) {
  return (items ?? [])
    .map((item) => (item?.activity_type ? normalizeExistingActivity(item) : normalizeAuthorActivity(item, { username, transport })))
    .filter((item) => item.id)
    .filter((item) => !afterUtc || !item.created_at || item.created_at >= afterUtc)
    .sort((left, right) => compareIsoDesc(left.created_at, right.created_at) || right.score - left.score);
}

function ageToBand(value) {
  if (!Number.isFinite(value) || value < 13) return null;
  if (value < 18) return '13-17';
  if (value < 25) return '18-24';
  if (value < 35) return '25-34';
  if (value < 45) return '35-44';
  if (value < 55) return '45-54';
  if (value < 65) return '55-64';
  return '65+';
}

function decadeToBand(value) {
  if (!Number.isFinite(value)) return null;
  return ageToBand(value);
}

function normalizeVehicle(value) {
  return String(value).toUpperCase().replace('F150', 'F-150');
}

function normalizeActivitySource(source, fallbackTimestamp) {
  return {
    transport: String(source?.transport ?? 'checkpoint'),
    collected_at: normalizeIsoDate(source?.collected_at) ?? fallbackTimestamp ?? new Date(0).toISOString(),
  };
}

function extractExplicitLocationText(text) {
  const patterns = [
    /\b(?:i live in|i am based in|i'm based in|im based in|i am from|i'm from|im from)\s+([^.!?\n]+)/i,
    /\b(?:i am|i'm|im)\b[^.!?\n]{0,40}?\bbased in\s+([^.!?\n]+)/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) return match[1];
  }
  return null;
}

function selectStateFromExplicitLocation(text) {
  let bestMatch = null;
  for (const [state, pattern] of STATE_PATTERNS) {
    const match = pattern.exec(text);
    if (!match) continue;
    const candidate = { state, index: match.index };
    if (!bestMatch || candidate.index < bestMatch.index) {
      bestMatch = candidate;
    }
  }
  return bestMatch?.state ?? null;
}

function isOccupationRelevant(text) {
  return /\b(headlight|bulb|retrofit|vehicle|truck|car|install|repair|mechanic)\b/i.test(text);
}

function buildTermList(productTerms, dictionaries) {
  return [...new Set([
    ...(productTerms ?? []),
    ...(dictionaries?.products ?? []),
    ...(dictionaries?.vehicles ?? []),
    ...(dictionaries?.fitment ?? []),
    ...(dictionaries?.slang ?? []),
    ...AUTOMOTIVE_KEYWORDS,
  ].filter(Boolean))];
}

function activityText(activity) {
  return [activity?.title, activity?.body_original].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
}

function containsTerm(text, term) {
  const escaped = escapeRegExp(term).replace(/\\\s+/g, '\\s+');
  return new RegExp(`\\b${escaped}\\b`, 'i').test(text);
}

function compareIsoDesc(left, right) {
  const leftValue = left ? Date.parse(left) : 0;
  const rightValue = right ? Date.parse(right) : 0;
  return rightValue - leftValue;
}

function normalizeUsername(value) {
  const text = String(value ?? '').trim();
  return text && text !== '[deleted]' ? text : null;
}

function normalizeIsoDate(value) {
  if (!value) return null;
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

function clampPositiveInteger(value, fallback) {
  const normalized = Number.parseInt(value, 10);
  return Number.isFinite(normalized) && normalized > 0 ? normalized : fallback;
}

function safeFilename(value) {
  return String(value).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isRetryable(error) {
  const status = Number(error?.status ?? 0);
  return status === 429 || status >= 500;
}

async function readJsonIfExists(filePath) {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'));
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
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

function failureKey(value) {
  return JSON.stringify({
    stage: value.stage,
    username: value.username ?? null,
  });
}

async function recordFailureAttempt({
  attemptsPath,
  attemptCounts,
  stage,
  transport,
  now,
  username,
  error,
}) {
  const key = failureKey({ stage, username });
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
    username,
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
