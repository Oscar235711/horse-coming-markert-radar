const DEFAULT_MAX_TERMS = 20;
const DEFAULT_MINIMUM_SCORE = 65;
const DEFAULT_MINIMUM_USERS = 2;
const DEFAULT_MINIMUM_COMMUNITIES = 2;
const DEFAULT_STOPWORDS = new Set([
  'a',
  'an',
  'and',
  'another',
  'any',
  'are',
  'after',
  'be',
  'before',
  'better',
  'bought',
  'back',
  'buy',
  'came',
  'car',
  'cars',
  'considering',
  'did',
  'do',
  'does',
  'for',
  'from',
  'follow',
  'follow-up',
  'get',
  'good',
  'have',
  'here',
  'i',
  'if',
  'in',
  'into',
  'is',
  'its',
  'it',
  'just',
  'kit',
  'light',
  'lights',
  'looking',
  'me',
  'my',
  'need',
  'new',
  'now',
  'owner',
  'of',
  'on',
  'or',
  'our',
  'out',
  'problem',
  'question',
  'really',
  'replacement',
  'returned',
  'set',
  'should',
  'so',
  'still',
  'that',
  'the',
  'their',
  'them',
  'there',
  'these',
  'this',
  'to',
  'truck',
  'use',
  'what',
  'with',
]);

const CATEGORY_PATTERNS = [
  ['product', /\b(bulb|film|assembly|adapter|harness|relay|membrane|kit|housing|projector|lens|led|halogen|hid)\b/i],
  ['pain', /\b(condensation|flicker|glare|leak|fogging|hyperflash|fitment|overheat)\b/i],
  ['behavior', /\b(buy|bought|budget|recommend|worth it|looking for)\b/i],
  ['fitment', /\b(h11|9005|9006|h7|h4|9012|h13|f-?150|silverado|tacoma|wrangler)\b/i],
];

const PAIN_PATTERN = /\b(condensation|flicker|glare|fogging|leak|fitment|hyperflash|overheat|warning light)\b/i;
const WORKAROUND_PATTERN = /\b(try|tried|fix|fixed|solution|adapter|harness|film|membrane|relay)\b/i;
const PURCHASE_PATTERN = /\b(budget|under \$|around \$|looking for|what should i buy|recommend|buy|bought|paid|worth it|amazon)\b/i;
const PROMOTIONAL_PATTERN = /\b(coupon|sale|discount|promo|affiliate|shop now)\b/i;
const TOKEN_PATTERN = /[a-z0-9]+(?:-[a-z0-9]+)*/g;

export function extractKeywordCandidates(evidence, authorActivity, config = {}) {
  const context = buildContext(config);
  const aggregate = new Map();
  const sourceRecords = [
    ...flattenEvidence(evidence),
    ...flattenAuthorActivity(authorActivity),
  ]
    .filter((record) => record.record_id)
    .filter((record) => record.eligible)
    .filter((record) => record.is_author_activity || record.quality_band === 'high');

  for (const record of sourceRecords) {
    const terms = collectTermsFromRecord(record, context);
    for (const termInfo of terms) {
      if (!shouldKeepTerm(termInfo.term, context)) continue;
      const normalizedTerm = normalizeTerm(termInfo.term);
      if (!normalizedTerm || !shouldKeepTerm(normalizedTerm, context)) continue;

      const key = normalizedTerm;
      const existing = aggregate.get(key) ?? createCandidateShell(normalizedTerm);
      existing.normalized_term = normalizedTerm;
      existing.term = normalizedTerm;
      existing.unique_user_count = 0;
      existing.community_count = 0;
      existing.categories = union(existing.categories, inferCategories(normalizedTerm, termInfo.categories));
      existing.extraction_methods = union(existing.extraction_methods, [termInfo.method]);
      existing.source_evidence_ids = union(existing.source_evidence_ids, [record.record_id]);
      existing.evidence_ids = union(existing.evidence_ids, [record.record_id]);
      existing.authors = union(existing.authors, record.author ? [record.author] : []);
      existing.communities = union(existing.communities, record.community ? [record.community] : []);
      existing.parent_formal_terms = union(existing.parent_formal_terms, inferParentFormalTerms(record.text, context));
      existing.threads = union(existing.threads, record.thread_id ? [record.thread_id] : []);
      existing.purchase_signal_count += record.purchase_signal ? 1 : 0;
      existing.pain_signal_count += record.pain_signal ? 1 : 0;
      existing.workaround_signal_count += record.workaround_signal ? 1 : 0;
      existing.promotional_signal_count += record.promotional_signal ? 1 : 0;
      existing.source_quality.total += normalizeQualityWeight(record.quality_band);
      existing.source_quality.high += record.quality_band === 'high' ? 1 : 0;
      existing.source_quality.medium += record.quality_band === 'medium' ? 1 : 0;
      aggregate.set(key, existing);
    }
  }

  return [...aggregate.values()]
    .map(finalizeExtractedCandidate)
    .sort((left, right) => (
      right.unique_user_count - left.unique_user_count
      || right.community_count - left.community_count
      || right.purchase_signal_count - left.purchase_signal_count
      || left.term.localeCompare(right.term)
    ));
}

export function scoreKeywordCandidates(candidates, config = {}) {
  const context = buildContext(config);
  return (candidates ?? [])
    .map((candidate) => {
      const uniqueUsers = clamp(Math.min(candidate.unique_user_count, 5) * 8, 0, 25);
      const crossCommunity = clamp(Math.min(candidate.community_count, 3) * 5, 0, 15);
      const specificity = scoreSpecificity(candidate, context);
      const purchaseIntent = clamp(candidate.purchase_signal_count * 5, 0, 15);
      const painOrWorkaround = clamp(candidate.pain_signal_count * 4 + candidate.workaround_signal_count * 2, 0, 10);
      const anchorCooccurrence = clamp(candidate.parent_formal_terms.length * 5, 0, 10);
      const novelty = context.formalTerms.has(candidate.normalized_term) ? 0 : 10;

      const penalties = {
        one_user_dominance: candidate.unique_user_count < 2 ? 10 : 0,
        one_thread_dominance: candidate.threads.length < 2 && candidate.evidence_ids.length > 1 ? 6 : 0,
        brand_only: isBrandOnly(candidate, context) ? 40 : 0,
        promotional_language: clamp(candidate.promotional_signal_count * 5, 0, 10),
        generic_language: isGenericTerm(candidate, context) ? 12 : 0,
        excluded_evidence: 0,
      };
      penalties.total = Object.entries(penalties)
        .filter(([key]) => key !== 'total')
        .reduce((sum, [, value]) => sum + value, 0);

      const scoreBreakdown = {
        unique_users: uniqueUsers,
        cross_community: crossCommunity,
        specificity,
        purchase_intent: purchaseIntent,
        pain_or_workaround: painOrWorkaround,
        anchor_cooccurrence: anchorCooccurrence,
        novelty,
      };
      const discoveryScore = clamp(
        Object.values(scoreBreakdown).reduce((sum, value) => sum + value, 0) - penalties.total,
        0,
        100,
      );

      return {
        ...candidate,
        unique_user_count: candidate.unique_user_count,
        community_count: candidate.community_count,
        score_breakdown: scoreBreakdown,
        penalties,
        discovery_score: discoveryScore,
        status: deriveCandidateStatus(candidate, discoveryScore, context),
      };
    })
    .sort((left, right) => (
      right.discovery_score - left.discovery_score
      || right.unique_user_count - left.unique_user_count
      || right.community_count - left.community_count
      || left.term.localeCompare(right.term)
    ));
}

export function selectRoundTwoTerms(candidates, options = {}) {
  const maxTerms = clampPositiveInteger(options.maxTerms, DEFAULT_MAX_TERMS);
  const minimumScore = clampPositiveInteger(options.minimumScore, DEFAULT_MINIMUM_SCORE);
  const minimumUsers = clampPositiveInteger(options.minimumUsers, DEFAULT_MINIMUM_USERS);
  const minimumCommunities = clampPositiveInteger(options.minimumCommunities, DEFAULT_MINIMUM_COMMUNITIES);

  return (candidates ?? [])
    .filter((candidate) => candidate.status !== 'formal' && candidate.status !== 'rejected')
    .filter((candidate) => Number(candidate.discovery_score ?? 0) >= minimumScore)
    .filter((candidate) => Number(candidate.unique_user_count ?? 0) >= minimumUsers)
    .filter((candidate) => Number(candidate.community_count ?? 0) >= minimumCommunities)
    .slice(0, maxTerms)
    .map((candidate) => candidate.term);
}

function flattenEvidence(evidence) {
  return (evidence ?? []).map((record) => ({
    record_id: record.id,
    thread_id: record.post_id ?? record.id,
    author: normalizeActor(record.author),
    community: normalizeCommunity(record.subreddit),
    text: [record.title, record.body_original].filter(Boolean).join(' ').trim(),
    eligible: record?.quality?.eligible === true,
    quality_band: String(record?.quality?.quality_band ?? 'noise'),
    pain_signal: PAIN_PATTERN.test([record.title, record.body_original].filter(Boolean).join(' ')),
    workaround_signal: WORKAROUND_PATTERN.test([record.title, record.body_original].filter(Boolean).join(' ')),
    purchase_signal: PURCHASE_PATTERN.test([record.title, record.body_original].filter(Boolean).join(' ')),
    promotional_signal: PROMOTIONAL_PATTERN.test([record.title, record.body_original].filter(Boolean).join(' ')),
    discovered_terms: [],
    is_author_activity: false,
  }));
}

function flattenAuthorActivity(authorActivity) {
  const rows = [];
  for (const author of authorActivity ?? []) {
    for (const activity of author?.retained_activity ?? []) {
      rows.push({
        record_id: activity.id,
        thread_id: activity.activity_id ?? activity.id,
        author: normalizeActor(activity.author ?? author.username),
        community: normalizeCommunity(activity.subreddit),
        text: [activity.title, activity.body_original].filter(Boolean).join(' ').trim(),
        eligible: activity?.quality?.hard_exclusion !== true,
        quality_band: String(activity?.quality?.quality_band ?? 'medium'),
        pain_signal: PAIN_PATTERN.test([activity.title, activity.body_original].filter(Boolean).join(' ')),
        workaround_signal: WORKAROUND_PATTERN.test([activity.title, activity.body_original].filter(Boolean).join(' ')),
        purchase_signal: PURCHASE_PATTERN.test([activity.title, activity.body_original].filter(Boolean).join(' ')),
        promotional_signal: PROMOTIONAL_PATTERN.test([activity.title, activity.body_original].filter(Boolean).join(' ')),
        discovered_terms: Array.isArray(activity.discovered_terms) ? activity.discovered_terms : [],
        is_author_activity: true,
      });
    }
  }
  return rows;
}

function collectTermsFromRecord(record, context) {
  const text = record.text;
  const terms = [];
  const termKeys = new Set();
  const push = (term, method, categories = []) => {
    const normalized = normalizeTerm(term);
    if (!normalized || termKeys.has(`${method}:${normalized}`)) return;
    termKeys.add(`${method}:${normalized}`);
    terms.push({ term: normalized, method, categories });
  };

  for (const term of record.discovered_terms ?? []) {
    push(term, 'activity');
  }

  for (const term of context.dictionaryTerms) {
    if (containsTerm(text, term.match_term)) {
      push(term.normalized_term, 'dictionary', inferCategories(term.normalized_term));
    }
  }

  const ngrams = collectNgrams(text, context);
  for (const term of ngrams) {
    push(term, 'ngram');
  }

  return terms;
}

function collectNgrams(text, context) {
  const tokens = tokenize(normalizeText(text));
  const phrases = new Set();

  for (let size = 2; size <= 3; size += 1) {
    for (let index = 0; index <= tokens.length - size; index += 1) {
      const slice = tokens.slice(index, index + size);
      if (!slice.length) continue;
      if (slice.every((token) => context.stopwords.has(token))) continue;
      if (!isMeaningfulToken(slice[0], context) || !isMeaningfulToken(slice.at(-1), context)) continue;
      if (!slice.some((token) => isMeaningfulToken(token, context))) continue;
      const phrase = normalizeTerm(slice.join(' '));
      if (!phrase || phrase.length < 4) continue;
      if (context.formalTerms.has(phrase)) continue;
      if (context.brandTerms.has(phrase)) continue;
      if (context.stopwords.has(phrase)) continue;
      if (!/^[a-z0-9][a-z0-9 -]*[a-z0-9]$/.test(phrase)) continue;
      phrases.add(phrase);
    }
  }

  return [...phrases];
}

function buildContext(config) {
  const keywords = config?.keywords ?? {};
  const dictionaries = config?.market_rules?.dictionaries ?? {};
  const formalTerms = new Set([
    ...(keywords.anchors ?? []),
    ...(keywords.expanded ?? []),
  ].map(normalizeTerm).filter(Boolean));
  const brandTerms = new Set([
    ...(keywords.candidate_only_brands ?? []),
    ...(dictionaries.competitors ?? []),
  ].map(normalizeTerm).filter(Boolean));
  const dictionaryTerms = [
    ...(dictionaries.products ?? []),
    ...(dictionaries.vehicles ?? []),
    ...(dictionaries.fitment ?? []),
    ...(dictionaries.retailers ?? []),
    ...(dictionaries.slang ?? []),
  ]
    .map((term) => ({
      match_term: normalizeMatchTerm(term),
      normalized_term: normalizeTerm(term),
    }))
    .filter((term) => term.match_term && term.normalized_term)
    .filter((term) => !formalTerms.has(term.normalized_term))
    .filter((term) => !brandTerms.has(term.normalized_term))
    .filter((term, index, values) => values.findIndex((candidate) => (
      candidate.match_term === term.match_term
      && candidate.normalized_term === term.normalized_term
    )) === index);
  const stopwords = new Set([
    ...DEFAULT_STOPWORDS,
    ...((dictionaries.stopwords ?? []).map((term) => normalizeTerm(term)).filter(Boolean)),
  ]);

  return {
    formalTerms,
    brandTerms,
    dictionaryTerms,
    stopwords,
  };
}

function createCandidateShell(term) {
  return {
    term,
    normalized_term: term,
    categories: [],
    extraction_methods: [],
    evidence_ids: [],
    source_evidence_ids: [],
    authors: [],
    communities: [],
    parent_formal_terms: [],
    threads: [],
    purchase_signal_count: 0,
    pain_signal_count: 0,
    workaround_signal_count: 0,
    promotional_signal_count: 0,
    source_quality: {
      high: 0,
      medium: 0,
      total: 0,
    },
  };
}

function finalizeExtractedCandidate(candidate) {
  return {
    ...candidate,
    categories: [...candidate.categories].sort(),
    extraction_methods: [...candidate.extraction_methods].sort(),
    evidence_ids: [...candidate.evidence_ids].sort(),
    source_evidence_ids: [...candidate.source_evidence_ids].sort(),
    authors: [...candidate.authors].sort(),
    communities: [...candidate.communities].sort(),
    parent_formal_terms: [...candidate.parent_formal_terms].sort(),
    threads: [...candidate.threads].sort(),
    unique_user_count: candidate.authors.length,
    community_count: candidate.communities.length,
    average_quality_weight: candidate.evidence_ids.length
      ? Number((candidate.source_quality.total / candidate.evidence_ids.length).toFixed(3))
      : 0,
  };
}

function scoreSpecificity(candidate, context) {
  const tokenCount = tokenize(candidate.normalized_term).length;
  if (context.formalTerms.has(candidate.normalized_term)) return 0;
  if (candidate.categories.includes('product') && tokenCount >= 2) return 15;
  if (candidate.categories.includes('fitment') && tokenCount >= 1) return 12;
  if (candidate.categories.includes('behavior')) return 8;
  return tokenCount >= 2 ? 10 : 6;
}

function deriveCandidateStatus(candidate, score, context) {
  if (context.formalTerms.has(candidate.normalized_term)) return 'formal';
  if (isBrandOnly(candidate, context) || isGenericTerm(candidate, context) || score < 1) return 'rejected';
  return 'candidate_review';
}

function inferParentFormalTerms(text, context) {
  return [...context.formalTerms].filter((term) => containsTerm(text, term));
}

function inferCategories(term, preset = []) {
  const categories = new Set(preset ?? []);
  for (const [name, pattern] of CATEGORY_PATTERNS) {
    if (pattern.test(term)) categories.add(name);
  }
  if (!categories.size) categories.add('product');
  return [...categories];
}

function shouldKeepTerm(term, context) {
  if (!term) return false;
  const normalized = normalizeTerm(term);
  if (!normalized) return false;
  if (context.formalTerms.has(normalized)) return false;
  if (context.brandTerms.has(normalized)) return false;
  if (context.stopwords.has(normalized)) return false;
  if (tokenize(normalized).every((token) => context.stopwords.has(token))) return false;
  return true;
}

function isBrandOnly(candidate, context) {
  return context.brandTerms.has(candidate.normalized_term)
    || (candidate.categories.length === 1 && candidate.categories[0] === 'competitor_brand');
}

function isGenericTerm(candidate, context) {
  const tokens = tokenize(candidate.normalized_term);
  return !tokens.length
    || tokens.every((token) => context.stopwords.has(token))
    || (tokens.length === 1 && tokens[0].length < 4);
}

function isMeaningfulToken(token, context) {
  if (!token) return false;
  if (context.stopwords.has(token)) return false;
  if (token.length >= 3 && /\d/.test(token)) return true;
  return /\b(film|membrane|assembly|adapter|harness|relay|fix|condensation|flicker|fitment|glare|headlight|bulb|led|hid|halogen)\b/i.test(token);
}

function normalizeQualityWeight(qualityBand) {
  if (qualityBand === 'high') return 1;
  if (qualityBand === 'medium') return 0.5;
  return 0.25;
}

function normalizeText(value) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\bf[\s-]?150\b/g, 'f-150')
    .replace(/[^a-z0-9\s-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function tokenize(value) {
  return normalizeMatchTerm(value).match(TOKEN_PATTERN) ?? [];
}

function normalizeTerm(value) {
  let text = normalizeMatchTerm(value);
  if (text === 'protective film') text = 'headlight protective film';
  return text.trim();
}

function normalizeMatchTerm(value) {
  return normalizeText(value)
    .replace(/\bheadlights\b/g, 'headlight')
    .replace(/\bassemblies\b/g, 'assembly')
    .replace(/\bbulbs\b/g, 'bulb')
    .replace(/\bmembranes\b/g, 'membrane')
    .replace(/\bfilms\b/g, 'film')
    .replace(/\bkits\b/g, 'kit')
    .replace(/\brelays\b/g, 'relay')
    .replace(/\badapters\b/g, 'adapter')
    .trim();
}

function normalizeActor(value) {
  const text = String(value ?? '').trim();
  return text || null;
}

function normalizeCommunity(value) {
  const text = String(value ?? '').replace(/^r\//i, '').trim();
  return text || null;
}

function containsTerm(text, term) {
  const escaped = escapeRegExp(normalizeMatchTerm(term)).replace(/\\\s+/g, '\\s+');
  return new RegExp(`\\b${escaped}\\b`, 'i').test(normalizeMatchTerm(text));
}

function union(values, additions) {
  return [...new Set([...(values ?? []), ...(additions ?? [])].filter(Boolean))];
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, Math.round(value)));
}

function clampPositiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
