const ALLOWED_TYPES = new Set(['validated_entry', 'emerging_product', 'adjacent_bundle']);
const QUALIFIED_ROLES = new Set([
  'direct_experience',
  'qualified_practitioner',
  'market_observation',
]);
const PAIN_THEME_TERMS = /\b(optimization|improvement|issue|problem|pain|glare|flicker|condensation|fogging|moisture|water ingress|fitment|installation|difficult)\b/i;
const SELLABLE_TERMS = /\b(kit|film|adapter|harness|bulb|lamp|projector|retrofit|membrane|vent|protector|cover|cleaner|module|replacement|accessory|tool|cap)\b/i;
const AMBIGUOUS_ASSEMBLY_THEME = /\b(assembly|housing)\b/i;

const DEFAULT_CONCEPTS = [
  { id: 'led-headlight-bulb-kit', label: 'LED 头灯灯泡套装', category: 'headlight', patterns: ['led headlight', 'led bulb', 'headlight bulb', 'headlight upgrade', 'h11', '9005', '9006', 'h7', 'h4', '9012', 'h13'], opportunity_type: 'validated_entry' },
  { id: 'fog-light-kit', label: '雾灯套装', category: 'fog-light', patterns: ['fog light', 'fog lamp'], opportunity_type: 'validated_entry' },
  { id: 'tail-brake-light-kit', label: '尾灯与刹车灯套装', category: 'tail-brake', patterns: ['tail light', 'taillight', 'brake light'], opportunity_type: 'validated_entry' },
  { id: 'turn-signal-kit', label: '转向灯套装', category: 'turn-signal', patterns: ['turn signal', 'sequential signal'], opportunity_type: 'validated_entry' },
  { id: 'drl-kit', label: '日间行车灯套装', category: 'drl', patterns: ['daytime running light', 'drl'], opportunity_type: 'validated_entry' },
  { id: 'auxiliary-light-kit', label: '辅助驾驶灯套装', category: 'auxiliary', patterns: ['auxiliary light', 'driving light', 'light bar', 'off-road light', 'off road light'], opportunity_type: 'validated_entry' },
  { id: 'projector-retrofit-kit', label: '透镜改装套件', category: 'projector', patterns: ['projector retrofit', 'projector kit'], opportunity_type: 'validated_entry' },
  { id: 'canbus-adapter-kit', label: 'CANbus 适配套件', category: 'electrical', patterns: ['canbus adapter', 'wiring harness', 'relay kit'], opportunity_type: 'validated_entry' },
  { id: 'headlight-vent-membrane-kit', label: '头灯透气膜维修套件', category: 'repair-accessory', patterns: ['vent membrane kit', 'breather vent'], opportunity_type: 'emerging_product' },
  { id: 'protective-headlight-film', label: '车灯保护膜', category: 'protection', patterns: ['headlight film', 'protective film', 'light film'], opportunity_type: 'adjacent_bundle' },
];

const DEFAULT_PAINS = {
  flicker: { label: '闪烁/故障码', patterns: ['flicker', 'error code', 'warning light', 'hyperflash'] },
  glare: { label: '眩光/光型失控', patterns: ['glare', 'blinding', 'poor beam', 'beam pattern', 'cutoff'] },
  dim_output: { label: '亮度不足', patterns: ['dim', 'not bright', 'poor visibility', 'weak output'] },
  condensation: { label: '进水/起雾', patterns: ['condensation', 'fogging', 'water ingress', 'moisture', 'leak'] },
  overheating: { label: '过热/寿命短', patterns: ['overheat', 'burned out', 'burnt out', 'short life', 'failed early'] },
  fitment: { label: '安装/适配困难', patterns: ["doesn't fit", 'does not fit', 'poor fitment', 'fitment', 'hard to install', 'installation issue', 'clearance'] },
  compliance: { label: '法规/检测风险', patterns: ['illegal', 'inspection', 'dot approved', 'street legal', 'ticket'] },
};

const DEFAULT_THRESHOLDS = {
  validated_entry: { unique_users: 8, communities: 2, direct_experience: 3, score: 55 },
  emerging_product: { unique_users: 5, contexts: 2, score: 50 },
  adjacent_bundle: { unique_users: 5, core_contexts: 2, score: 50 },
};

const SOLUTION_IDEAS = {
  '闪烁/故障码': '配套已验证协议兼容的驱动器或 CANbus 适配方案',
  '眩光/光型失控': '补充光型匹配、截止线控制或投射结构方案',
  '亮度不足': '围绕有效照度与寿命平衡优化产品规格',
  '进水/起雾': '提供透气膜、防护膜或其他可验证密封解决方案',
  '过热/寿命短': '补足散热、驱动降额和寿命验证信息',
  '安装/适配困难': '增加车型适配、线束/防尘盖或安装辅件组合',
  '法规/检测风险': '补充合规边界、认证材料和道路用途说明',
};

export function extractPainRecords(evidence, config = {}) {
  const painDefinitions = normalizePainDefinitions(config.opportunity_engine?.pain_patterns);
  const records = [];

  for (const [id, definition] of Object.entries(painDefinitions)) {
    const matched = relevantEvidence(evidence).filter((item) => matchesAny(evidenceText(item), definition.patterns));
    if (!matched.length) continue;
    records.push({
      id,
      label: definition.label,
      evidence_ids: unique(matched.map((item) => item.id)),
      unique_users: unique(matched.map(authorKey)).length,
      communities: unique(matched.map((item) => item.subreddit)),
      evidence_count: matched.length,
      qualified_evidence_count: matched.filter(isQualifiedSupport).length,
      fact_status: 'fact',
    });
  }

  return records.sort((a, b) => b.evidence_count - a.evidence_count || a.id.localeCompare(b.id));
}

export function buildOpportunityCandidates(evidence, painRecords, config = {}) {
  const concepts = Array.isArray(config.opportunity_engine?.concepts) && config.opportunity_engine.concepts.length
    ? config.opportunity_engine.concepts
    : DEFAULT_CONCEPTS;
  const matchedEvidence = relevantEvidence(evidence);
  const painByEvidence = new Map();

  for (const pain of painRecords ?? []) {
    for (const evidenceId of pain.evidence_ids ?? []) {
      const labels = painByEvidence.get(evidenceId) ?? [];
      labels.push(pain.label ?? pain.id);
      painByEvidence.set(evidenceId, labels);
    }
  }

  return concepts.filter(validConcept).flatMap((concept) => {
    const matched = matchedEvidence.filter((item) => matchesAny(evidenceText(item), concept.patterns));
    if (!matched.length) return [];

    const qualifiedMatched = matched.filter(isQualifiedSupport);
    const competitorTerms = config.opportunity_engine?.competitor_terms
      ?? config.market_rules?.dictionaries?.competitors
      ?? config.keywords?.candidate_only_brands
      ?? [];
    const competitorSignals = collectCompetitorSignals(qualifiedMatched, competitorTerms);
    const evidenceIds = unique(matched.map((item) => item.id));
    const qualifiedEvidenceIds = unique(qualifiedMatched.map((item) => item.id));
    const pains = unique(qualifiedEvidenceIds.flatMap((id) => painByEvidence.get(id) ?? []));
    const directExperience = qualifiedMatched.filter((item) => item.quality?.evidence_role === 'direct_experience');
    const contexts = unique(qualifiedMatched.map((item) => `${item.subreddit ?? 'unknown'}:${contextKey(evidenceText(item))}`));
    const coreContexts = qualifiedMatched.filter((item) => /\b(?:install|upgrade|replacement|bundle|add-on|added|protection|gift|accessor|storage|convenience)\b/i.test(evidenceText(item)));

    return [{
      id: concept.id,
      label: concept.label,
      category: concept.category,
      opportunity_type: concept.opportunity_type,
      matched_evidence: matched,
      qualified_evidence: qualifiedMatched,
      evidence_ids: evidenceIds,
      qualified_evidence_ids: qualifiedEvidenceIds,
      communities: unique(qualifiedMatched.map((item) => item.subreddit)),
      matched_communities: unique(matched.map((item) => item.subreddit)),
      unique_users: unique(qualifiedMatched.map(authorKey)).length,
      matched_unique_users: unique(matched.map(authorKey)).length,
      direct_experience_count: directExperience.length,
      workaround_evidence_count: qualifiedMatched.filter((item) => /\b(workaround|prototype|diy|tried|attempted|replace)\b/i.test(evidenceText(item))).length,
      context_count: contexts.length,
      core_context_count: coreContexts.length,
      contextual_demand_count: qualifiedMatched.filter((item) => item.quality?.evidence_role === 'contextual_demand').length,
      competitor_signals: competitorSignals,
      existing_product_signals: unique(
        qualifiedMatched
          .filter((item) => /\b(?:bought|installed|sells?|available|brand|returned|replacement|kit|adapter|film|bulb)\b/i.test(evidenceText(item)))
          .map((item) => item.id),
      ),
      entry_gaps: pains,
      pain_points: pains,
      fitment_tags: extractFitment(qualifiedMatched.map(evidenceText).join('\n')),
      is_concrete_product: isConcreteSellableConcept(concept),
    }];
  });
}

export function classifyOpportunities(candidates, config = {}) {
  const thresholds = mergeThresholds(config.opportunity_engine?.thresholds);
  const opportunities = [];
  const candidateSignals = [];
  const competitors = new Map();

  for (const candidate of candidates ?? []) {
    if (!candidate?.id || !candidate?.label || !ALLOWED_TYPES.has(candidate.opportunity_type)) continue;

    for (const signal of candidate.competitor_signals ?? []) {
      const ids = competitors.get(signal.name) ?? [];
      competitors.set(signal.name, unique([...ids, ...signal.evidence_ids]));
    }

    const scoreComponents = scoreCandidate(candidate);
    const scorePenalties = scorePenaltiesForCandidate(candidate);
    const opportunityScore = clamp(Object.values(scoreComponents).reduce((sum, value) => sum + value, 0) - scorePenalties.total, 0, 100);
    const thresholdCheck = checkThresholds(candidate, opportunityScore, thresholds[candidate.opportunity_type]);
    const publicCandidate = {
      id: candidate.id,
      label: candidate.label,
      category: candidate.category,
      opportunity_type: candidate.opportunity_type,
      opportunity_score: opportunityScore,
      verdict: verdictForCandidate(opportunityScore, thresholdCheck.passed),
      score_components: scoreComponents,
      score_penalties: scorePenalties,
      threshold_check: thresholdCheck,
      evidence_ids: candidate.evidence_ids,
      qualified_evidence_ids: candidate.qualified_evidence_ids,
      unique_user_count: candidate.unique_users,
      matched_user_count: candidate.matched_unique_users,
      community_count: candidate.communities.length,
      communities: candidate.communities,
      matched_communities: candidate.matched_communities,
      direct_experience_count: candidate.direct_experience_count,
      fitment_tags: candidate.fitment_tags,
      pain_points: candidate.pain_points,
      solution_ideas: unique(candidate.pain_points.map((pain) => SOLUTION_IDEAS[pain] ?? `${candidate.label} 仍需补充可验证解决方案`)),
      competitor_signals: candidate.competitor_signals,
      existing_product_signals: candidate.existing_product_signals,
      entry_gaps: candidate.entry_gaps,
      claims: buildClaims(candidate),
      commercial: buildCommercial(candidate),
      why_not_done: {
        status: candidate.entry_gaps.length ? 'inference' : 'unknown',
        text: candidate.entry_gaps.length ? `现有方案仍出现${candidate.entry_gaps.join('、')}。` : null,
      },
    };

    (thresholdCheck.passed ? opportunities : candidateSignals).push(publicCandidate);
  }

  opportunities.sort(compareOpportunity);
  candidateSignals.sort(compareOpportunity);
  return {
    opportunities,
    candidate_signals: candidateSignals,
    competitors: [...competitors.entries()].map(([name, evidence_ids]) => ({ name, evidence_ids })),
  };
}

function scoreCandidate(candidate) {
  const weightedEvidence = candidate.qualified_evidence.reduce((sum, item) => sum + evidenceWeight(item), 0);
  const purchaseSignals = candidate.qualified_evidence.filter((item) => /\b(?:buy|bought|paid|price|budget|under \$|returned|recommend|looking for|need)\b/i.test(evidenceText(item))).length;
  const competitorValidated = candidate.competitor_signals.length > 0 || candidate.existing_product_signals.length > 0;

  return {
    qualified_demand: clamp(candidate.unique_users * 3 + weightedEvidence, 0, 25),
    existing_market_validation: clamp(competitorValidated ? 12 + candidate.competitor_signals.length * 4 : 0, 0, 20),
    unresolved_entry_gap: clamp(candidate.entry_gaps.length * 7, 0, 20),
    purchase_price_signals: clamp(purchaseSignals * 3, 0, 10),
    diversity: clamp(candidate.unique_users + candidate.communities.length * 3, 0, 10),
    adjacency_bundle_logic: clamp(candidate.opportunity_type === 'adjacent_bundle' ? 5 + candidate.core_context_count * 2 : 0, 0, 10),
    evidence_quality: clamp(weightedEvidence, 0, 5),
  };
}

function scorePenaltiesForCandidate(candidate) {
  const oneUser = candidate.unique_users <= 1 ? 10 : 0;
  const oneCommunity = candidate.communities.length <= 1 ? 8 : 0;
  const contextualDominance = candidate.qualified_evidence.length > 0 && candidate.contextual_demand_count > candidate.qualified_evidence.length / 2 ? 8 : 0;
  const noQualifiedEvidence = candidate.qualified_evidence.length === 0 ? 20 : 0;
  const nonConcreteConcept = candidate.is_concrete_product ? 0 : 20;
  const total = oneUser + oneCommunity + contextualDominance + noQualifiedEvidence + nonConcreteConcept;

  return {
    one_user_concentration: oneUser,
    one_community_concentration: oneCommunity,
    contextual_question_dominance: contextualDominance,
    missing_qualified_support: noQualifiedEvidence,
    non_sellable_concept: nonConcreteConcept,
    total,
  };
}

function checkThresholds(candidate, score, threshold) {
  const checks = {
    qualified_evidence: candidate.qualified_evidence_ids.length > 0,
    unique_users: candidate.unique_users >= threshold.unique_users,
    communities: candidate.communities.length >= (threshold.communities ?? 0),
    direct_experience: candidate.direct_experience_count >= (threshold.direct_experience ?? 0),
    contexts: candidate.context_count >= (threshold.contexts ?? 0),
    core_contexts: candidate.core_context_count >= (threshold.core_contexts ?? 0),
    score: score >= threshold.score,
    concrete_product: candidate.is_concrete_product,
    existing_market: candidate.opportunity_type !== 'validated_entry' || candidate.existing_product_signals.length > 0 || candidate.competitor_signals.length > 0,
    entry_gap: candidate.opportunity_type !== 'validated_entry' || candidate.entry_gaps.length > 0,
    solution_validation: candidate.opportunity_type !== 'emerging_product' || candidate.workaround_evidence_count > 0,
  };
  const failures = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name);
  return { passed: failures.length === 0, checks, failures, required: threshold };
}

function buildClaims(candidate) {
  return {
    facts: [
      `${candidate.qualified_evidence_ids.length} 条合格 Reddit 证据直接支撑该可销售产品概念。`,
      `${candidate.unique_users} 名独立合格用户、${candidate.communities.length} 个社区构成当前正式评分样本。`,
    ],
    inferences: [
      '该评分只用于当前合格样本内排序，不代表市场规模。',
      candidate.entry_gaps.length ? `当前机会主要围绕${candidate.entry_gaps.join('、')}等未解决缺口展开。` : '仍需补充更多跨社区证据验证进入空间。',
    ],
    unknowns: ['制造成本', '供应商 MOQ', '真实退货率', '美国市场销量', '法规认证状态'],
  };
}

function buildCommercial(candidate) {
  const prices = candidate.qualified_evidence.flatMap((item) => [...evidenceText(item).matchAll(/\$\s*(\d+(?:\.\d{1,2})?)/g)].map((match) => Number(match[1])));
  return {
    pricing_band: prices.length ? { status: 'fact', value: `$${Math.min(...prices)}–$${Math.max(...prices)}`, evidence_ids: candidate.qualified_evidence_ids } : { status: 'unknown', value: null },
    margin_potential: { status: 'unknown', value: null },
    manufacturing_complexity: { status: 'unknown', value: null },
    shipping_complexity: { status: 'unknown', value: null },
    return_risk: candidate.entry_gaps.some((pain) => /适配|闪烁|眩光/.test(pain))
      ? { status: 'inference', value: '可能偏高', basis: '合格样本出现适配、电子兼容或光型问题' }
      : { status: 'unknown', value: null },
  };
}

function normalizePainDefinitions(overrides) {
  if (!overrides) return DEFAULT_PAINS;
  const merged = { ...DEFAULT_PAINS };
  for (const [id, value] of Object.entries(overrides)) {
    merged[id] = {
      label: DEFAULT_PAINS[id]?.label ?? value.label ?? id,
      patterns: Array.isArray(value) ? value : value.patterns,
    };
  }
  return merged;
}

function mergeThresholds(overrides = {}) {
  return Object.fromEntries(Object.entries(DEFAULT_THRESHOLDS).map(([type, values]) => [type, { ...values, ...(overrides[type] ?? {}) }]));
}

function validConcept(concept) {
  return Boolean(concept?.id && concept?.label && ALLOWED_TYPES.has(concept.opportunity_type) && Array.isArray(concept.patterns) && concept.patterns.length);
}

function relevantEvidence(evidence) {
  return (evidence ?? []).filter((item) => {
    const quality = item.quality ?? {};
    return quality.hard_exclusion !== true
      && quality.evidence_role !== 'noise'
      && quality.quality_band !== 'noise';
  });
}

function isQualifiedSupport(item) {
  const quality = item?.quality ?? {};
  return QUALIFIED_ROLES.has(quality.evidence_role)
    && quality.eligible === true
    && ['high', 'medium'].includes(quality.quality_band)
    && quality.hard_exclusion !== true;
}

function collectCompetitorSignals(evidence, competitorTerms) {
  return competitorTerms.flatMap((name) => {
    const records = evidence.filter((item) => containsTerm(evidenceText(item), name));
    return records.length ? [{ name, evidence_ids: unique(records.map((item) => item.id)) }] : [];
  });
}

function isConcreteSellableConcept(concept) {
  const summary = `${concept.id} ${concept.label} ${concept.category ?? ''}`.replace(/[-_]/g, ' ');
  if (/\boptimization\b/i.test(summary)) return false;
  if (PAIN_THEME_TERMS.test(summary) && !SELLABLE_TERMS.test(summary)) return false;
  if (AMBIGUOUS_ASSEMBLY_THEME.test(summary) && !/\b(replacement|sealed|vent|membrane|kit|module)\b/i.test(summary)) return false;
  return true;
}

function evidenceWeight(item) {
  return item.quality?.quality_band === 'high' ? 1 : item.quality?.quality_band === 'medium' ? 0.5 : 0;
}

function verdictForCandidate(score, passed) {
  if (!passed) return '研究候选，仍需补足门槛证据';
  if (score >= 75) return '高信号，建议进入商品验证';
  if (score >= 55) return '中高信号，可继续验证切入点';
  return '达到最低门槛，但仍需继续采样';
}

function evidenceText(item) {
  return [item?.title, item?.body_original, item?.quote_original].filter(Boolean).join(' ');
}

function containsTerm(text, term) {
  return buildTermPattern(term).test(text);
}

function matchesAny(text, patterns = []) {
  return patterns.some((pattern) => containsTerm(text, pattern));
}

function authorKey(item) {
  return item.author || item.post_id || item.id;
}

function contextKey(text) {
  if (/workaround|diy|made|prototype/i.test(text)) return 'workaround';
  if (/need|want|which|looking for|recommend/i.test(text)) return 'demand';
  if (/bought|installed|used|returned/i.test(text)) return 'experience';
  return 'observation';
}

function extractFitment(text) {
  return unique(text.match(/\b(?:h11|9005|9006|h7|h4|9012|h13|f-?150|silverado|tacoma|wrangler|ram 1500|ram 2500)\b/gi)?.map((value) => value.toUpperCase().replace('F150', 'F-150')) ?? []);
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildTermPattern(term) {
  const normalized = escapeRegExp(term).replace(/\\\s+/g, '\\s+');
  const pluralized = normalized.replace(/([A-Za-z]+)$/, '$1s?');
  return new RegExp(`\\b${pluralized}\\b`, 'i');
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Math.round(value)));
}

function compareOpportunity(a, b) {
  return b.opportunity_score - a.opportunity_score || a.id.localeCompare(b.id);
}
