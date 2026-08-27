const DEFAULT_PERSONA_THRESHOLDS = {
  qualified_evidence: 200,
  qualified_users: 60,
  deep_dive_authors: 30,
  cluster_members: 12,
  representative_users: 3,
  representative_activities: 3,
  demographic_cohort: 10,
};

const REPRESENTATIVE_PRIVACY_NOTE = 'Representative cards stay behavior-only and do not expose sensitive demographic fields.';
const DEFAULT_PRIVACY_NOTE = 'Only public, research-relevant author activity is used. Personas stay behavior-only, and demographic context is aggregate-only.';
const QUALIFIED_BANDS = new Set(['high', 'medium']);
const QUALIFIED_ROLES = new Set([
  'direct_experience',
  'qualified_practitioner',
  'market_observation',
]);

const SEGMENTS = [
  {
    key: 'diy_led_upgrade',
    id: 'diy-led-upgrade',
    label: 'DIY LED Upgraders',
    signals: ['DIY install preference', 'LED replacement interest', 'Beam-pattern troubleshooting'],
  },
  {
    key: 'housing_protection',
    id: 'housing-protection',
    label: 'Housing Protection Seekers',
    signals: ['Recurring condensation repairs', 'Protective or sealing solution search', 'Repeat-failure avoidance'],
  },
  {
    key: 'truck_visibility_fixers',
    id: 'truck-visibility-fixers',
    label: 'Truck Visibility Fixers',
    signals: ['Night-driving visibility focus', 'Truck-platform context', 'Beam-control over raw brightness'],
  },
  {
    key: 'general_maintenance',
    id: 'general-maintenance',
    label: 'General Maintenance Shoppers',
    signals: ['Replacement-oriented demand', 'General repair context', 'Broad product exploration'],
  },
];

const SEGMENT_BY_KEY = new Map(SEGMENTS.map((segment) => [segment.key, segment]));
const PRODUCT_LABELS = {
  'led-headlight-bulb-kit': 'led_headlight_bulb_kit',
  'canbus-adapter-kit': 'canbus_adapter_kit',
  'protective-headlight-film': 'protective_headlight_film',
  'headlight-vent-membrane-kit': 'headlight_vent_membrane_kit',
  'headlight-assembly': 'headlight_assembly',
  'projector-upgrade-kit': 'projector_upgrade_kit',
};

export { DEFAULT_PERSONA_THRESHOLDS };

export function evaluatePersonaEligibility(evidence, authors, thresholds = DEFAULT_PERSONA_THRESHOLDS) {
  const mergedThresholds = mergeThresholds(thresholds);
  const qualifiedEvidence = filterQualifiedEvidence(evidence);
  const authorRecords = normalizeAuthorArtifacts(authors);
  const counts = {
    qualified_evidence: qualifiedEvidence.length,
    qualified_users: unique(qualifiedEvidence.map(authorKey)).length,
    deep_dive_authors: authorRecords.length,
  };
  const missing = [];

  for (const metric of ['qualified_evidence', 'qualified_users', 'deep_dive_authors']) {
    if (counts[metric] < mergedThresholds[metric]) {
      missing.push({
        metric,
        required: mergedThresholds[metric],
        actual: counts[metric],
      });
    }
  }

  return {
    status: missing.length ? 'insufficient_sample' : 'complete',
    persona_status: missing.length ? 'insufficient_sample' : 'complete',
    thresholds: mergedThresholds,
    counts,
    missing,
  };
}

export function aggregateSelfDeclaredContext(authors, { minimumCohort = DEFAULT_PERSONA_THRESHOLDS.demographic_cohort } = {}) {
  const authorRecords = normalizeAuthorArtifacts(authors);
  return {
    age_bands: aggregateContextKind(authorRecords, 'age_band', minimumCohort),
    states: aggregateContextKind(authorRecords, 'state', minimumCohort),
    budget_signals: aggregateContextKind(authorRecords, 'budget', minimumCohort),
  };
}

export function buildPersonas(evidence, authorActivity, config = {}) {
  const thresholds = mergeThresholds(config.persona_thresholds ?? config.personas?.thresholds);
  const qualifiedEvidence = filterQualifiedEvidence(evidence);
  const evidenceByAuthor = groupEvidenceByAuthor(qualifiedEvidence);
  const qualifiedUsers = new Set(evidenceByAuthor.keys());
  const authorRecords = normalizeAuthorArtifacts(authorActivity)
    .filter((author) => qualifiedUsers.has(author.username));
  const eligibility = evaluatePersonaEligibility(qualifiedEvidence, authorRecords, thresholds);
  const baseResult = createBaseResult(eligibility, authorRecords);

  if (eligibility.status !== 'complete') return baseResult;

  const userSummaries = authorRecords
    .map((author) => summarizeAuthor(author, evidenceByAuthor.get(author.username) ?? []))
    .filter((summary) => summary.retained_activity_count > 0);

  if (!userSummaries.length) {
    return withMissing(baseResult, [{
      metric: 'cluster_members',
      required: thresholds.cluster_members,
      actual: 0,
      cluster_id: SEGMENTS[0].id,
      cluster_label: SEGMENTS[0].label,
    }]);
  }

  const clusterCandidates = buildClusterCandidates(userSummaries, thresholds);
  const localMissing = collectLocalMissing(clusterCandidates, thresholds);
  if (localMissing.length) return withMissing(baseResult, localMissing);

  const aggregateContext = aggregateSelfDeclaredContext(authorRecords, {
    minimumCohort: thresholds.demographic_cohort,
  });
  const clusters = clusterCandidates.map((candidate) => ({
    id: candidate.segment.id,
    label: candidate.segment.label,
    user_count: candidate.users.length,
    evidence_count: candidate.users.reduce((sum, user) => sum + user.qualified_evidence_count, 0),
    signals: [...candidate.segment.signals],
    product_interests: topCounts(candidate.users.flatMap((user) => user.product_interests), 6),
    vehicle_platforms: topCounts(candidate.users.flatMap((user) => user.vehicle_platforms), 4),
    purchase_criteria: topCounts(candidate.users.flatMap((user) => user.purchase_criteria), 6),
    recurring_pain_points: topCounts(candidate.users.flatMap((user) => user.recurring_pain_points), 6),
    explored_solutions: topCounts(candidate.users.flatMap((user) => user.explored_solutions), 6),
    related_communities: topCounts(candidate.users.flatMap((user) => user.related_communities), 6),
    vocabulary: topCounts(candidate.users.flatMap((user) => user.vocabulary), 8),
    aggregate_context: aggregateSelfDeclaredContext(candidate.users.map((user) => user.author), {
      minimumCohort: thresholds.demographic_cohort,
    }),
    representative_users: buildRepresentativeUsers(candidate.users, thresholds),
  }));

  return {
    ...baseResult,
    status: 'complete',
    persona_status: 'complete',
    counts: {
      ...baseResult.counts,
      published_clusters: clusters.length,
    },
    missing: [],
    aggregate_context: aggregateContext,
    clusters,
  };
}

function createBaseResult(eligibility, authors) {
  return {
    schema_version: '1.0.0',
    status: eligibility.status,
    persona_status: eligibility.persona_status,
    thresholds: eligibility.thresholds,
    counts: {
      ...eligibility.counts,
      published_clusters: 0,
    },
    missing: [...eligibility.missing],
    aggregate_context: aggregateSelfDeclaredContext(authors, {
      minimumCohort: eligibility.thresholds.demographic_cohort,
    }),
    clusters: [],
    privacy_note: DEFAULT_PRIVACY_NOTE,
  };
}

function withMissing(baseResult, missing) {
  return {
    ...baseResult,
    status: 'insufficient_sample',
    persona_status: 'insufficient_sample',
    missing,
  };
}

function buildClusterCandidates(userSummaries, thresholds) {
  const buckets = new Map();

  for (const summary of userSummaries) {
    const segment = selectSegment(summary);
    const bucket = buckets.get(segment.id) ?? { segment, users: [] };
    bucket.users.push(summary);
    buckets.set(segment.id, bucket);
  }

  return [...buckets.values()]
    .map((bucket) => ({
      ...bucket,
      users: bucket.users.sort(compareUserSummary),
      representative_candidates: bucket.users.filter((user) => user.retained_activity_count >= thresholds.representative_activities),
    }))
    .sort((left, right) => segmentOrder(left.segment) - segmentOrder(right.segment));
}

function collectLocalMissing(clusterCandidates, thresholds) {
  const missing = [];

  for (const candidate of clusterCandidates) {
    if (candidate.users.length < thresholds.cluster_members) {
      missing.push({
        metric: 'cluster_members',
        required: thresholds.cluster_members,
        actual: candidate.users.length,
        cluster_id: candidate.segment.id,
        cluster_label: candidate.segment.label,
      });
      continue;
    }

    if (candidate.representative_candidates.length < thresholds.representative_users) {
      missing.push({
        metric: 'representative_users',
        required: thresholds.representative_users,
        actual: candidate.representative_candidates.length,
        cluster_id: candidate.segment.id,
        cluster_label: candidate.segment.label,
      });
    }
  }

  return missing;
}

function buildRepresentativeUsers(users, thresholds) {
  return users
    .filter((user) => user.retained_activity_count >= thresholds.representative_activities)
    .sort(compareRepresentative)
    .slice(0, thresholds.representative_users)
    .map((user, index) => ({
      user_code: `REP-${String(index + 1).padStart(2, '0')}-${safeCode(user.username)}`,
      public_username: user.username,
      selection_score: user.selection_score,
      retained_activity_count: user.retained_activity_count,
      observable_behaviors: user.observable_behaviors,
      supporting_evidence_ids: user.supporting_evidence_ids,
      supporting_evidence_urls: user.supporting_evidence_urls,
      confidence: confidenceForUser(user),
      privacy_note: REPRESENTATIVE_PRIVACY_NOTE,
    }));
}

function summarizeAuthor(author, evidence) {
  const activities = normalizeRetainedActivity(author.retained_activity)
    .sort(compareActivityDesc);
  const productInterests = topCounts(activities.flatMap((activity) => activity.product_concepts), 6);
  const vehiclePlatforms = topCounts(activities.flatMap(vehicleValuesForActivity), 4);
  const purchaseCriteria = topCounts(activities.flatMap(purchaseCriteriaForActivity), 6);
  const recurringPainPoints = topCounts(activities.flatMap((activity) => activity.pain_points), 6);
  const exploredSolutions = topCounts(activities.flatMap(solutionSignalsForActivity), 6);
  const communities = topCounts(activities.map((activity) => activity.subreddit), 6);
  const vocabulary = topCounts(activities.flatMap((activity) => activity.discovered_terms), 8);
  const installPreference = resolveInstallPreference(activities);
  const supportingActivities = activities.slice(0, 3);
  const observableBehaviors = describeObservableBehaviors({
    installPreference,
    productInterests,
    purchaseCriteria,
    recurringPainPoints,
    vehiclePlatforms,
  });
  const selectionScore = clamp(
    supportingActivities.length * 18
      + evidence.length * 6
      + productInterests.length * 5
      + purchaseCriteria.length * 4
      + communities.length * 2
      + vocabulary.length,
    0,
    100,
  );

  return {
    author,
    username: author.username,
    retained_activity_count: activities.length,
    qualified_evidence_count: evidence.length,
    product_interests: productInterests,
    vehicle_platforms: vehiclePlatforms,
    purchase_criteria: purchaseCriteria,
    recurring_pain_points: recurringPainPoints,
    explored_solutions: exploredSolutions,
    related_communities: communities,
    vocabulary,
    install_preference: installPreference,
    observable_behaviors: observableBehaviors,
    supporting_evidence_ids: supportingActivities.map((activity) => activity.id),
    supporting_evidence_urls: supportingActivities.map((activity) => activity.url),
    selection_score: selectionScore,
  };
}

function selectSegment(summary) {
  const products = new Set(summary.product_interests);
  const painPoints = new Set(summary.recurring_pain_points);
  const vocabulary = new Set(summary.vocabulary);
  const vehicles = new Set(summary.vehicle_platforms);

  if (
    products.has('protective_headlight_film')
    || products.has('headlight_vent_membrane_kit')
    || products.has('headlight_assembly')
    || painPoints.has('condensation')
  ) {
    return SEGMENT_BY_KEY.get('housing_protection');
  }

  if (
    summary.install_preference === 'diy'
    && (
      products.has('led_headlight_bulb_kit')
      || products.has('canbus_adapter_kit')
      || vocabulary.has('h11')
      || vocabulary.has('canbus adapter')
    )
  ) {
    return SEGMENT_BY_KEY.get('diy_led_upgrade');
  }

  if (
    products.has('projector_upgrade_kit')
    || vocabulary.has('night visibility')
    || painPoints.has('glare')
    || painPoints.has('dim_output')
    || vehicles.has('Silverado')
  ) {
    return SEGMENT_BY_KEY.get('truck_visibility_fixers');
  }

  return SEGMENT_BY_KEY.get('general_maintenance');
}

function aggregateContextKind(authors, kind, minimumCohort) {
  const counts = new Map();

  for (const author of authors) {
    const values = new Set(
      normalizeRetainedActivity(author.retained_activity)
        .flatMap((activity) => activity.self_declared_context ?? [])
        .filter((entry) => entry?.kind === kind && entry?.source === 'self_declared')
        .map((entry) => String(entry.value ?? '').trim())
        .filter(Boolean),
    );

    for (const value of values) {
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
  }

  return [...counts.entries()]
    .filter(([, count]) => count >= minimumCohort)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([value, count]) => ({ value, count }));
}

function groupEvidenceByAuthor(evidence) {
  const byAuthor = new Map();

  for (const record of evidence) {
    const key = authorKey(record);
    if (!key) continue;
    const bucket = byAuthor.get(key) ?? [];
    bucket.push(record);
    byAuthor.set(key, bucket);
  }

  return byAuthor;
}

function normalizeAuthorArtifacts(authors) {
  return (authors ?? [])
    .map((author) => ({
      ...author,
      username: authorKey(author),
      retained_activity: normalizeRetainedActivity(author?.retained_activity),
    }))
    .filter((author) => author.username && author.retained_activity.length > 0)
    .sort((left, right) => left.username.localeCompare(right.username));
}

function normalizeRetainedActivity(activities) {
  return (activities ?? [])
    .map((activity) => ({
      ...activity,
      id: String(activity?.id ?? '').trim(),
      subreddit: String(activity?.subreddit ?? '').replace(/^r\//i, '').trim(),
      url: String(activity?.url ?? '').trim(),
      created_at: normalizeIso(activity?.created_at),
      product_concepts: unique((activity?.product_concepts ?? []).map((value) => PRODUCT_LABELS[value] ?? value)),
      pain_points: unique((activity?.pain_points ?? []).map((value) => String(value).trim())),
      discovered_terms: unique((activity?.discovered_terms ?? []).map((value) => String(value).trim().toLowerCase())),
      self_declared_context: (activity?.self_declared_context ?? []).filter((entry) => entry?.source === 'self_declared'),
      quality: activity?.quality ?? {},
      body_original: String(activity?.body_original ?? '').trim(),
      title: String(activity?.title ?? '').trim(),
    }))
    .filter((activity) => activity.id && activity.url);
}

function filterQualifiedEvidence(evidence) {
  return (evidence ?? [])
    .filter((record) => {
      const quality = record?.quality ?? {};
      return quality.eligible === true
        && QUALIFIED_BANDS.has(quality.quality_band)
        && QUALIFIED_ROLES.has(quality.evidence_role)
        && quality.hard_exclusion !== true;
    });
}

function authorKey(value) {
  const username = String(value?.username ?? value?.author ?? '').trim();
  return username || null;
}

function vehicleValuesForActivity(activity) {
  const declared = (activity.self_declared_context ?? [])
    .filter((entry) => entry.kind === 'vehicle')
    .map((entry) => String(entry.value ?? '').trim());
  if (declared.length) return unique(declared);

  const text = activityText(activity);
  const matches = [];
  if (/\bf-?150\b/i.test(text)) matches.push('F-150');
  if (/\bsilverado\b/i.test(text)) matches.push('Silverado');
  if (/\btacoma\b/i.test(text)) matches.push('Tacoma');
  if (/\bwrangler\b/i.test(text)) matches.push('Wrangler');
  if (/\btruck\b/i.test(text) && !matches.length) matches.push('Truck');
  return unique(matches);
}

function purchaseCriteriaForActivity(activity) {
  const text = activityText(activity);
  const criteria = [];

  if (
    (activity.self_declared_context ?? []).some((entry) => entry.kind === 'budget')
    || /\b(?:budget|under \$|around \$|price|worth it|paid)\b/i.test(text)
  ) {
    criteria.push('budget_sensitive');
  }
  if (/\b(?:beam pattern|cutoff|glare|visibility|night)\b/i.test(text)) criteria.push('beam_quality');
  if (/\b(?:fitment|dust cap|adapter|clearance)\b/i.test(text)) criteria.push('fitment_sensitive');
  if (/\b(?:durable|last|warranty|repeat|longer-lasting)\b/i.test(text)) criteria.push('durability');
  if (/\b(?:myself|diy|easy to install|install these myself)\b/i.test(text)) criteria.push('install_effort');
  if (/\b(?:water|moisture|condensation|seal)\b/i.test(text)) criteria.push('weather_resistance');

  return criteria;
}

function solutionSignalsForActivity(activity) {
  const solutions = new Set(activity.product_concepts ?? []);
  for (const term of activity.discovered_terms ?? []) {
    if (/\b(adapter|film|vent|projector|upgrade|assembly)\b/i.test(term)) solutions.add(term);
  }
  return [...solutions];
}

function resolveInstallPreference(activities) {
  const text = activities.map(activityText).join('\n');
  const diy = activities.some((activity) => (activity.self_declared_context ?? []).some((entry) => entry.kind === 'diy_ability'))
    || /\b(?:install these myself|did it myself|diy|myself)\b/i.test(text);
  const professional = activities.some((activity) => (activity.self_declared_context ?? []).some((entry) => entry.kind === 'occupation'))
    || /\b(?:mechanic|shop|installer|technician)\b/i.test(text);

  if (diy && professional) return 'mixed';
  if (diy) return 'diy';
  if (professional) return 'professional';
  return 'unknown';
}

function describeObservableBehaviors({
  installPreference,
  productInterests,
  purchaseCriteria,
  recurringPainPoints,
  vehiclePlatforms,
}) {
  const behaviors = [];

  if (installPreference === 'diy') behaviors.push('self-directed installation');
  if (installPreference === 'professional') behaviors.push('professional-install preference');
  if (productInterests[0]) behaviors.push(`focuses on ${productInterests[0]}`);
  if (purchaseCriteria[0]) behaviors.push(`screens for ${purchaseCriteria[0]}`);
  if (recurringPainPoints[0]) behaviors.push(`repeats ${recurringPainPoints[0]} troubleshooting`);
  if (vehiclePlatforms[0]) behaviors.push(`mentions ${vehiclePlatforms[0]} platform context`);

  return unique(behaviors).slice(0, 5);
}

function compareRepresentative(left, right) {
  return right.selection_score - left.selection_score
    || right.qualified_evidence_count - left.qualified_evidence_count
    || right.retained_activity_count - left.retained_activity_count
    || left.username.localeCompare(right.username);
}

function compareUserSummary(left, right) {
  return segmentOrder(selectSegment(left)) - segmentOrder(selectSegment(right))
    || right.qualified_evidence_count - left.qualified_evidence_count
    || right.retained_activity_count - left.retained_activity_count
    || left.username.localeCompare(right.username);
}

function compareActivityDesc(left, right) {
  return (Date.parse(right.created_at ?? 0) - Date.parse(left.created_at ?? 0))
    || ((right.quality?.quality_score ?? 0) - (left.quality?.quality_score ?? 0))
    || left.id.localeCompare(right.id);
}

function confidenceForUser(user) {
  if (user.retained_activity_count >= 4 && user.qualified_evidence_count >= 4) return 'high';
  if (user.retained_activity_count >= 3 && user.qualified_evidence_count >= 2) return 'medium';
  return 'low';
}

function topCounts(values, limit) {
  const counts = new Map();
  for (const value of values.filter(Boolean)) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit)
    .map(([value]) => value);
}

function normalizeIso(value) {
  const parsed = Date.parse(String(value ?? ''));
  return Number.isNaN(parsed) ? null : new Date(parsed).toISOString();
}

function activityText(activity) {
  return [activity?.title, activity?.body_original].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function safeCode(value) {
  return String(value).replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 24).toUpperCase();
}

function mergeThresholds(value) {
  return {
    ...DEFAULT_PERSONA_THRESHOLDS,
    ...(value ?? {}),
  };
}

function segmentOrder(segment) {
  return SEGMENTS.findIndex((entry) => entry.id === segment.id);
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, Math.round(value)));
}
