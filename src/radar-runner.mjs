import fs from 'node:fs/promises';
import path from 'node:path';

import { analyzeDetails, analyzeWithOptionalLlm } from './radar-analysis.mjs';
import { buildKeywordCloud } from './keyword-cloud.mjs';
import { buildAudienceMap } from './radar-core.mjs';
import { runRadarPipeline } from './radar-pipeline.mjs';
import { writeReportArtifacts } from './radar-report.mjs';

export async function runLightingRadar({ config, adapter, runDir, runId, llmAnalyzer = null }) {
  const collection = await runRadarPipeline({ config, adapter, runDir, runId });
  const rules = analyzeDetails(collection.details, config, { runId: collection.manifest.run_id });
  const keywordCandidates = await readKeywordCandidates(runDir);
  const analysis = {
    ...(await analyzeWithOptionalLlm(rules, llmAnalyzer)),
    collection_failures: collection.failures,
    research_keywords: {
      anchors: config.keywords?.anchors ?? [],
      expanded: config.keywords?.expanded ?? [],
      exploratory_used: keywordCandidates
        .filter((item) => item.status === 'exploratory_used')
        .map((item) => item.term),
    },
  };
  const cloudCandidates = keywordCandidates.length
    ? keywordCandidates
    : synthesizeKeywordCandidatesFromAnalysis(analysis);
  const audienceMap = buildAudienceMap(analysis);
  const keywordCloud = buildKeywordCloud(cloudCandidates, analysis.evidence, {
    runId: collection.manifest.run_id,
    scope: config.market,
  });
  const manifest = {
    ...collection.manifest,
    counts: {
      ...collection.manifest.counts,
      opportunities: analysis.opportunities.length,
      candidate_signals: analysis.candidate_signals.length,
      audience_nodes: audienceMap.nodes.length,
      audience_edges: audienceMap.edges.length,
      keyword_cloud_terms: keywordCloud.terms.length,
    },
    artifacts: {
      analysis: 'analysis.json',
      evidence: 'evidence.jsonl',
      audience_map: 'audience_map.json',
      keyword_cloud: 'keyword_cloud.json',
      opportunities: 'opportunities.json',
      personas: 'personas.json',
      quality_evidence: 'quality_evidence.jsonl',
      excluded_evidence: 'excluded_evidence.jsonl',
      report: 'report.html',
      optimization_backlog: 'optimization_backlog.jsonl',
      failures: 'failures.jsonl',
    },
  };
  await writeReportArtifacts({ runDir, analysis, audienceMap, keywordCloud, manifest });
  await fs.writeFile(path.join(runDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return { ...collection, analysis, audienceMap, keywordCloud, keywordCandidates: cloudCandidates, manifest };
}

async function readKeywordCandidates(runDir) {
  try {
    const raw = await fs.readFile(path.join(runDir, 'keyword_candidates.json'), 'utf8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.candidates) ? parsed.candidates : [];
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
}

function synthesizeKeywordCandidatesFromAnalysis(analysis) {
  const evidenceById = new Map((analysis.evidence ?? []).map((item) => [item.id, item]));
  const formal = (analysis.opportunities ?? []).map((item) => createSyntheticCandidate(item, evidenceById, 'formal'));
  const exploratory = (analysis.candidate_signals ?? []).map((item) => createSyntheticCandidate(item, evidenceById, 'candidate_review'));
  return [...formal, ...exploratory].filter(Boolean);
}

function createSyntheticCandidate(item, evidenceById, status) {
  const evidenceItems = (item.evidence_ids ?? item.qualified_evidence_ids ?? [])
    .map((id) => evidenceById.get(id))
    .filter(Boolean);
  const communities = uniqueStrings(item.communities ?? evidenceItems.map((evidence) => evidence.subreddit));
  const authors = uniqueStrings(evidenceItems.map((evidence) => evidence.author));
  const categories = item.opportunity_type === 'adjacent_bundle'
    ? ['adjacent_product', 'product']
    : ['product'];
  return {
    term: String(item.label ?? item.id ?? '').trim(),
    normalized_term: String(item.label ?? item.id ?? '').trim().toLowerCase(),
    categories,
    extraction_methods: ['analysis-fallback'],
    evidence_ids: uniqueStrings(item.evidence_ids ?? item.qualified_evidence_ids ?? []),
    source_evidence_ids: uniqueStrings(item.evidence_ids ?? item.qualified_evidence_ids ?? []),
    authors,
    communities,
    parent_formal_terms: [],
    related_product_ids: item.id ? [String(item.id)] : [],
    threads: uniqueStrings(evidenceItems.map((evidence) => evidence.post_id ?? evidence.id)),
    unique_user_count: Math.max(Number(item.unique_user_count ?? item.matched_user_count ?? authors.length), authors.length, 1),
    community_count: Math.max(Number(item.community_count ?? communities.length), communities.length, 1),
    purchase_signal_count: item.commercial?.pricing_band?.status === 'fact' ? 1 : 0,
    pain_signal_count: (item.pain_points ?? []).length,
    average_quality_weight: evidenceItems.length
      ? Number((evidenceItems.reduce((sum, evidence) => sum + qualityWeight(evidence.quality?.quality_band), 0) / evidenceItems.length).toFixed(3))
      : 0.5,
    score_breakdown: {},
    penalties: {},
    discovery_score: Number(item.opportunity_score ?? 45),
    status,
  };
}

function qualityWeight(qualityBand) {
  if (qualityBand === 'high') return 1;
  if (qualityBand === 'medium') return 0.5;
  return 0.25;
}

function uniqueStrings(values) {
  return [...new Set((values ?? []).filter(Boolean).map((value) => String(value)))];
}
