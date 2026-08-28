const CATEGORY_PRIORITY = [
  'adjacent_product',
  'product',
  'solution',
  'pain',
  'fitment',
  'competitor_brand',
  'use_case',
];

export function buildKeywordCloud(keywordCandidates, evidence, { runId = 'unknown-run', scope = {} } = {}) {
  const evidenceById = new Map((evidence ?? []).map((item) => [item.id, item]));
  const terms = (keywordCandidates ?? [])
    .filter((candidate) => candidate?.term)
    .filter((candidate) => candidate.status !== 'rejected')
    .map((candidate) => buildCloudTerm(candidate, evidenceById))
    .sort((left, right) => (
      right.display_weight - left.display_weight
      || right.discovery_score - left.discovery_score
      || left.term.localeCompare(right.term)
    ));

  return {
    schema_version: '1.0.0',
    run_id: runId,
    generated_at: new Date().toISOString(),
    scope: {
      country: scope.country ?? 'unknown',
      data_source: 'keyword_cloud.json',
      weighting_note: 'Display weight combines qualified evidence quality, unique users, cross-community coverage, and purchase/pain signals.',
    },
    terms,
    filters: {
      categories: unique(terms.flatMap((term) => term.categories)).sort(),
      statuses: unique(terms.map((term) => term.status)).sort(),
      minimum_score: 0,
    },
  };
}

function buildCloudTerm(candidate, evidenceById) {
  const representativeEvidence = unique(candidate.evidence_ids ?? [])
    .map((id) => evidenceById.get(id))
    .filter((item) => item?.quality?.eligible === true && item?.url)
    .slice(0, 3)
    .map((item) => ({
      evidence_id: item.id,
      url: item.url,
      subreddit: item.subreddit ?? 'unknown',
      quote_original: item.quote_original ?? item.body_original ?? item.title ?? '',
      quality_band: item?.quality?.quality_band ?? 'unknown',
    }));

  return {
    term: String(candidate.term),
    normalized_term: String(candidate.normalized_term ?? candidate.term),
    category: pickPrimaryCategory(candidate.categories),
    categories: unique(candidate.categories ?? []).sort(),
    status: String(candidate.status ?? 'candidate_review'),
    display_weight: clamp(Math.round(
      Number(candidate.discovery_score ?? 0) * 0.45
      + Number(candidate.unique_user_count ?? 0) * 12
      + Number(candidate.community_count ?? 0) * 10
      + Number(candidate.purchase_signal_count ?? 0) * 4
      + Number(candidate.pain_signal_count ?? 0) * 3
      + Number(candidate.average_quality_weight ?? 0) * 20,
    ), 1, 100),
    discovery_score: Number(candidate.discovery_score ?? 0),
    unique_user_count: Number(candidate.unique_user_count ?? 0),
    community_count: Number(candidate.community_count ?? 0),
    purchase_signal_count: Number(candidate.purchase_signal_count ?? 0),
    pain_signal_count: Number(candidate.pain_signal_count ?? 0),
    average_quality_weight: Number(candidate.average_quality_weight ?? 0),
    score_breakdown: { ...(candidate.score_breakdown ?? {}) },
    penalties: { ...(candidate.penalties ?? {}) },
    evidence_ids: unique(candidate.evidence_ids ?? []).sort(),
    source_evidence_ids: unique(candidate.source_evidence_ids ?? []).sort(),
    communities: unique(candidate.communities ?? []).sort(),
    parent_formal_terms: unique(candidate.parent_formal_terms ?? []).sort(),
    related_product_ids: unique(candidate.related_product_ids ?? []).sort(),
    representative_evidence: representativeEvidence,
  };
}

function pickPrimaryCategory(categories = []) {
  const available = new Set((categories ?? []).map((value) => String(value)));
  for (const category of CATEGORY_PRIORITY) {
    if (available.has(category)) return category;
  }
  return available.values().next().value ?? 'product';
}

function unique(values) {
  return [...new Set((values ?? []).filter(Boolean).map((value) => String(value)))];
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}
