import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const defaultRulesPath = path.join(here, '..', 'configs', 'rules', 'universal_evidence_rules.json');
const defaultMarketConfigPath = path.join(here, '..', 'configs', 'automotive_lighting_us_pilot.json');

export function loadUniversalEvidenceRules(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  const rules = JSON.parse(raw);

  validateRuleSection(rules, 'roles', (value) => Array.isArray(value) && value.length > 0);
  validateRuleSection(rules, 'component_caps', isRecordWithKeys);
  validateRuleSection(rules, 'quality_bands', isRecordWithKeys);
  validateRuleSection(rules, 'penalties', isRecordWithKeys);
  validateRuleSection(rules, 'hard_exclusions', isRecordWithKeys);

  return rules;
}

const UNIVERSAL_RULES = loadUniversalEvidenceRules(defaultRulesPath);
const BASE_MARKET_RULES = loadPilotMarketRules(defaultMarketConfigPath);

export function normalizeEvidenceText(value) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\bf[\s-]?150\b/g, 'f150')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function classifyEvidence(record, context = {}) {
  const mergedRules = mergeRules(UNIVERSAL_RULES, context.marketRules ?? {});
  const text = composeText(record);
  const normalized = normalizeEvidenceText(text);
  const reasonCodes = [];

  const hardExclusion = detectHardExclusion(record, text, normalized, mergedRules, context.market ?? {}, context.seenTexts);
  if (hardExclusion) {
    return finalizeClassification({
      role: 'noise',
      qualityScore: 0,
      hardExclusion: true,
      reasonCodes: [hardExclusion],
      components: zeroComponents(mergedRules.component_caps),
      penalties: buildPenalties(),
      minimumQualityScore: mergedRules.defaults.minimum_quality_score,
    });
  }

  const signals = collectSignals(record, text, mergedRules, context.market ?? {});
  const components = scoreComponents(record, signals, mergedRules);
  const penalties = scorePenalties(signals, mergedRules);
  const qualityScore = clamp(
    Object.values(components).reduce((sum, value) => sum + value, 0) - penalties.total,
    0,
    100,
  );
  const role = classifyRole(signals, qualityScore);

  reasonCodes.push(role);
  if (signals.lowInformation) reasonCodes.push('low_information_density');
  if (signals.uncertainGeography) reasonCodes.push('uncertain_geography');
  if (signals.marketStatus === 'target') reasonCodes.push('target_market_signal');

  if (context.seenTexts instanceof Set && normalized) {
    context.seenTexts.add(normalized);
  }

  return finalizeClassification({
    role,
    qualityScore,
    hardExclusion: false,
    reasonCodes,
    components,
    penalties,
    minimumQualityScore: mergedRules.defaults.minimum_quality_score,
  });
}

export function applyEvidenceGate(records, context = {}) {
  const seenTexts = context.seenTexts instanceof Set ? context.seenTexts : new Set();
  const qualified = [];
  const excluded = [];
  const byRole = Object.fromEntries(UNIVERSAL_RULES.roles.map((role) => [role, 0]));
  const byQualityBand = Object.fromEntries(Object.keys(UNIVERSAL_RULES.quality_bands).map((band) => [band, 0]));

  for (const record of records ?? []) {
    const quality = classifyEvidence(record, { ...context, seenTexts });
    byRole[quality.evidence_role] = (byRole[quality.evidence_role] ?? 0) + 1;
    byQualityBand[quality.quality_band] = (byQualityBand[quality.quality_band] ?? 0) + 1;

    const bucket = quality.eligible ? qualified : excluded;
    bucket.push({ ...record, quality });
  }

  return {
    qualified,
    excluded,
    distribution: {
      ...byQualityBand,
      by_role: byRole,
      by_quality_band: byQualityBand,
    },
  };
}

function mergeRules(universalRules, marketRules) {
  const baselineRules = BASE_MARKET_RULES ?? {};
  const minimumQualityScore = Number.isFinite(marketRules.minimum_quality_score)
    ? marketRules.minimum_quality_score
    : baselineRules.minimum_quality_score ?? universalRules.defaults.minimum_quality_score;

  return {
    ...universalRules,
    defaults: {
      ...universalRules.defaults,
      minimum_quality_score: minimumQualityScore,
    },
    geography: {
      ...(baselineRules.geography ?? {}),
      ...(marketRules.geography ?? {}),
      target_signals: [
        ...(baselineRules.geography?.target_signals ?? []),
        ...(marketRules.geography?.target_signals ?? []),
      ],
      non_target_signals: [
        ...(baselineRules.geography?.non_target_signals ?? []),
        ...(marketRules.geography?.non_target_signals ?? []),
      ],
    },
    dictionaries: normalizeDictionaries({
      ...(baselineRules.dictionaries ?? {}),
      ...(marketRules.dictionaries ?? {}),
    }),
    relevance: {
      required_any: [
        ...(baselineRules.relevance?.required_any ?? []),
        ...(marketRules.relevance?.required_any ?? []),
      ],
      excluded_communities: [
        ...(baselineRules.relevance?.excluded_communities ?? []),
        ...(marketRules.relevance?.excluded_communities ?? []),
      ],
      excluded_patterns: [
        ...(baselineRules.relevance?.excluded_patterns ?? []),
        ...(marketRules.relevance?.excluded_patterns ?? []),
      ],
    },
    hard_exclusions: mergeHardExclusionPatterns(universalRules.hard_exclusions, marketRules.hard_exclusions),
  };
}

function normalizeDictionaries(dictionaries) {
  const names = ['products', 'vehicles', 'fitment', 'competitors', 'retailers', 'slang', 'stopwords'];
  return Object.fromEntries(
    names.map((key) => [key, Array.isArray(dictionaries[key]) ? dictionaries[key] : []]),
  );
}

function mergeHardExclusionPatterns(universal, overrides = {}) {
  const merged = {};
  for (const [key, patterns] of Object.entries(universal ?? {})) {
    merged[key] = [...patterns];
    if (Array.isArray(overrides[key])) {
      merged[key].push(...overrides[key]);
    }
  }
  return merged;
}

function detectHardExclusion(record, text, normalized, rules, market, seenTexts) {
  const author = String(record?.author ?? '').trim();
  const subreddit = String(record?.subreddit ?? '').trim();

  if (isUrlOnly(record?.body_original ?? record?.title ?? '')) return 'url_only';

  const hardPatterns = [
    ['deleted_or_removed', text],
    ['bot_authors', author],
    ['moderation_boilerplate', text],
    ['generic_banter', text],
    ['affiliate_or_coupon', text],
    ['seller_solicitation', text],
    ['promotional_copy', text],
    ['news_or_repost', text],
    ['meme_or_motorsport', text],
    ['household_lighting', text],
    ['unsupported_hearsay', text],
  ];

  for (const [reasonCode, value] of hardPatterns) {
    if (matchesAny(value, rules.hard_exclusions?.[reasonCode] ?? [])) return reasonCode;
  }

  const marketStatus = classifyMarket(text, subreddit, rules, market);
  if (marketStatus === 'off_market') return 'off_market';

  if (seenTexts instanceof Set && normalized && seenTexts.has(normalized)) {
    return 'duplicate_or_near_duplicate';
  }

  const community = subreddit.toLowerCase();
  if ((rules.relevance?.excluded_communities ?? []).some((item) => community === String(item).toLowerCase())) {
    return 'excluded_community';
  }

  if (matchesAny(text, rules.relevance?.excluded_patterns ?? [])) return 'excluded_pattern';

  return null;
}

function collectSignals(record, text, rules, market) {
  const normalized = normalizeEvidenceText(text);
  const tokens = normalized ? normalized.split(' ') : [];
  const tokenSet = new Set(tokens);
  const matches = collectDictionaryMatches(text, rules.dictionaries);
  const firstPerson = /\b(i|i'm|i’ve|ive|my|we|our)\b/i.test(text);
  const experienceVerb = /\b(installed|bought|swapped|replaced|fixed|used|tried|adjusted|added|diagnose|diagnosed|checked)\b/i.test(text);
  const outcome = /\b(fixed|worked|brighter|better|failed|flicker(?:ed)?|hyperflash|warning light|beam|cutoff)\b/i.test(text);
  const request = /\b(what should i buy|what should i get|recommend|looking for|need\b|under \$?\d+|budget|which (?:bulb|brand|light)|preferably)\b/i.test(text)
    || /\?/.test(String(record?.title ?? ''));
  const location = /\b(texas|california|florida|washington|ohio|michigan|pennsylvania|illinois|arizona|georgia|north carolina)\b/i.test(text);
  const situationalConstraint = /\b(night driving|dust cap|limited space|factory|behind|warning light|ground)\b/i.test(text);
  const diagnostic = /\b(canbus|adapter|ground|relay|wiring harness|warning light|beam pattern|cutoff|dust cap|fitment)\b/i.test(text);
  const procedure = /\b(check|checking|inspect|diagnose|diagnosed|test|trace|verify|measure|start with|look for|clear(?:s)?|usually)\b/i.test(text);
  const practitioner = diagnostic && procedure && outcome;
  const marketAvailability = /\b(available at|sold at|carried by|in stock at|found at|auto parts stores?)\b/i.test(text);
  const marketStatus = classifyMarket(text, record?.subreddit, rules, market);
  const relevanceMatches = collectRegexMatches(text, rules.relevance?.required_any ?? []);
  const lowInformation = tokenSet.size <= 6 || (!matches.total && !request && !outcome);
  const quotedWithoutPersonalContext = !firstPerson && /["“”][^"“”]{3,}["“”]/.test(text);

  return {
    firstPerson,
    practitioner,
    experienceVerb,
    outcome,
    request,
    location,
    situationalConstraint,
    diagnostic,
    marketAvailability,
    marketStatus,
    uncertainGeography: Boolean(market?.country) && marketStatus === 'unknown',
    lowInformation,
    quotedWithoutPersonalContext,
    textLength: tokens.length,
    matches,
    relevanceMatches,
  };
}

function scoreComponents(record, signals, rules) {
  const caps = rules.component_caps;
  const productSignals = signals.matches.products.size + signals.matches.vehicles.size + signals.matches.fitment.size + Math.min(signals.relevanceMatches.length, 2);
  const contextSignals = Number(signals.location) + Number(signals.situationalConstraint) + Number(signals.marketStatus === 'target');
  const purchaseSignal = signals.request || /\b(bought|paid|under \$?\d+)\b/i.test(composeText(record));
  const diagnosticSignals = signals.matches.slang.size + Number(signals.diagnostic) + Number(/\bwarning light\b/i.test(composeText(record)));

  return {
    first_person_or_practitioner: clamp(
      signals.practitioner ? 18 : signals.firstPerson && signals.experienceVerb ? 20 : signals.firstPerson ? 10 : 0,
      0,
      caps.first_person_or_practitioner,
    ),
    product_specificity: clamp(productSignals * 7, 0, caps.product_specificity),
    context: clamp(contextSignals * 5, 0, caps.context),
    observable_outcome: clamp((signals.outcome ? 12 : 0) + (signals.experienceVerb ? 4 : 0) + (signals.request ? 0 : 4) + (signals.marketAvailability ? 8 : 0), 0, caps.observable_outcome),
    purchase_signal: clamp(purchaseSignal ? (signals.request ? 10 : 5) : 0, 0, caps.purchase_signal),
    diagnostic_detail: clamp(diagnosticSignals * 5, 0, caps.diagnostic_detail),
    corroboration: clamp(
      signals.matches.competitors.size || signals.matches.retailers.size || signals.marketAvailability ? 5 : signals.outcome && signals.matches.products.size ? 2 : 0,
      0,
      caps.corroboration,
    ),
    engagement: clamp(Math.log2(Math.max(1, Number(record?.score ?? 0) + 1)) * 2, 0, caps.engagement),
  };
}

function scorePenalties(signals, rules) {
  const penalties = buildPenalties();

  if (signals.lowInformation) penalties.low_information_density = rules.penalties.low_information_density;
  if (signals.uncertainGeography) penalties.uncertain_geography = rules.penalties.uncertain_geography;
  if (signals.quotedWithoutPersonalContext) {
    penalties.quotation_without_personal_context = rules.penalties.quotation_without_personal_context;
  }

  penalties.total = Object.entries(penalties)
    .filter(([key]) => key !== 'total')
    .reduce((sum, [, value]) => sum + value, 0);

  return penalties;
}

function classifyRole(signals, qualityScore) {
  const relevanceCount = signals.matches.total + signals.relevanceMatches.length;
  if (signals.practitioner && (signals.diagnostic || signals.outcome)) {
    return 'qualified_practitioner';
  }
  if ((signals.firstPerson && signals.experienceVerb) && (signals.outcome || signals.diagnostic || relevanceCount >= 2)) {
    return 'direct_experience';
  }
  if (signals.request && (signals.matches.total > 0 || signals.relevanceMatches.length > 0)) {
    return 'contextual_demand';
  }
  if (signals.lowInformation && relevanceCount > 0) {
    return 'weak';
  }
  if (relevanceCount > 0) {
    return 'market_observation';
  }
  return qualityScore >= 10 ? 'weak' : 'noise';
}

function finalizeClassification({ role, qualityScore, hardExclusion, reasonCodes, components, penalties, minimumQualityScore }) {
  const qualityBand = qualityBandForScore(qualityScore, UNIVERSAL_RULES.quality_bands);
  const eligible = !hardExclusion
    && !['contextual_demand', 'weak', 'noise'].includes(role)
    && qualityScore >= minimumQualityScore;

  return {
    evidence_role: role,
    quality_band: qualityBand,
    quality_score: qualityScore,
    eligible,
    hard_exclusion: hardExclusion,
    components,
    penalties,
    reason_codes: [...new Set(reasonCodes)],
  };
}

function qualityBandForScore(score, bands) {
  for (const [band, [minimum, maximum]] of Object.entries(bands)) {
    if (score >= minimum && score <= maximum) return band;
  }
  return 'noise';
}

function buildPenalties() {
  return {
    advertising_language: 0,
    low_information_density: 0,
    quotation_without_personal_context: 0,
    uncertain_geography: 0,
    suspected_duplication: 0,
    total: 0,
  };
}

function zeroComponents(componentCaps) {
  return Object.fromEntries(Object.keys(componentCaps).map((key) => [key, 0]));
}

function composeText(record) {
  return [record?.title, record?.body_original]
    .filter((value) => typeof value === 'string' && value.trim())
    .join('\n')
    .trim();
}

function matchesAny(value, patterns) {
  return patterns.some((pattern) => new RegExp(pattern, 'i').test(String(value ?? '')));
}

function isUrlOnly(value) {
  const text = String(value ?? '').trim();
  return Boolean(text) && /^https?:\/\/\S+$/i.test(text);
}

function collectDictionaryMatches(text, dictionaries) {
  const results = {};
  let total = 0;

  for (const [name, words] of Object.entries(dictionaries ?? {})) {
    const matches = new Set();
    for (const word of words) {
      const escaped = escapeRegExp(word).replace(/\\\s+/g, '\\s+');
      const pattern = new RegExp(`\\b${escaped}\\b`, 'i');
      if (pattern.test(text)) matches.add(word.toLowerCase());
    }
    results[name] = matches;
    total += matches.size;
  }

  return { ...results, total };
}

function collectRegexMatches(text, patterns) {
  return patterns.filter((pattern) => new RegExp(pattern, 'i').test(text));
}

function classifyMarket(text, subreddit, rules, market) {
  if (!market?.country) return 'unknown';
  const combined = `${text}\n${subreddit ?? ''}`;
  if (matchesAny(combined, rules.geography?.non_target_signals ?? [])) return 'off_market';
  if (matchesAny(combined, rules.geography?.target_signals ?? [])) return 'target';
  return 'unknown';
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, Math.round(value)));
}

function loadPilotMarketRules(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  const config = JSON.parse(raw);
  return config.market_rules ?? {};
}

function validateRuleSection(rules, key, predicate) {
  if (!predicate(rules?.[key])) {
    throw new Error(`Tracked universal evidence rules must include ${key}`);
  }
}

function isRecordWithKeys(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0;
}
