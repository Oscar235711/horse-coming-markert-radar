import { applyEvidenceGate } from './evidence-quality.mjs';
import {
  buildOpportunityCandidates,
  classifyOpportunities,
  extractPainRecords,
} from './opportunity-engine.mjs';

const TARGET_SIGNALS = [
  /\b(usa|u\.s\.|united states|texas|california|florida|pensacola|new york|ohio|michigan|pennsylvania|illinois|arizona|georgia|north carolina)\b/i,
  /\b(f-?150|silverado|tacoma|wrangler|crown ?victoria)\b/i,
];
const NON_TARGET_SIGNALS = [
  /\b(mot|united kingdom|\buk\b|cartalkuk|canada|ontario|australia|europe|eu inspection|carsph|philippines|i20[_ -]?india|\bindia\b)\b/i,
];

export function analyzeDetails(details, config = {}, { runId = 'unknown-run' } = {}) {
  const evidence = [];
  const usDetails = [];
  const unknownDetails = [];
  const nonUsDetails = [];
  const discoveredTerms = new Map();

  for (const detail of details) {
    const post = detail.post ?? {};
    const geography = resolveGeography(post, config);
    if (geography === 'us') usDetails.push(detail);
    else if (geography === 'non_us') nonUsDetails.push(detail);
    else unknownDetails.push(detail);

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
      geography,
      quote_original: trimQuote(`${post.title ?? ''}. ${post.body_original ?? post.selftext ?? ''}`),
      fact_status: 'fact',
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
        geography,
        quote_original: trimQuote(comment.body_original ?? comment.body ?? ''),
        fact_status: 'fact',
      });
    }

    const combined = `${post.title ?? ''}\n${post.body_original ?? post.selftext ?? ''}\n${(detail.comments ?? []).map((comment) => comment.body_original ?? comment.body ?? '').join('\n')}`;
    for (const brand of config.keywords?.candidate_only_brands ?? []) {
      if (new RegExp(`\\b${brand.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(combined)) {
        discoveredTerms.set(brand, (discoveredTerms.get(brand) ?? 0) + 1);
      }
    }
  }

  const gated = applyEvidenceGate(evidence, {
    market: config.market,
    marketRules: config.market_rules,
  });
  const classifiedEvidence = [...gated.qualified, ...gated.excluded];
  const usEvidence = classifiedEvidence.filter((item) => item.geography === 'us');
  const painPoints = extractPainRecords(usEvidence, config);
  const opportunityResults = classifyOpportunities(
    buildOpportunityCandidates(usEvidence, painPoints, config),
    config,
  );
  const painHotspots = painPoints.map((pain) => ({ name: pain.label, count: pain.evidence_count }));

  return {
    schema_version: '1.0.0',
    run_id: runId,
    generated_at: new Date().toISOString(),
    scope: {
      country: 'US',
      seasonality_in_scope: false,
      geography_rule: 'Explicit US location/market/vehicle signals only; unknown geography excluded from US conclusions.',
    },
    metrics: {
      posts_analyzed: details.length,
      comments_analyzed: details.reduce((sum, detail) => sum + (detail.comments?.length ?? 0), 0),
      us_posts: usDetails.length,
      unknown_geography_posts: unknownDetails.length,
      excluded_non_us_posts: nonUsDetails.length,
      communities: unique(usDetails.map((detail) => detail.post?.subreddit)).length,
    },
    executive_summary: opportunityResults.opportunities.length
      ? `本轮规则分析识别出 ${opportunityResults.opportunities.length} 个有美国合格证据支撑的可销售机会。`
      : opportunityResults.candidate_signals.length
        ? `本轮尚未形成正式产品机会，但已沉淀 ${opportunityResults.candidate_signals.length} 个待验证候选方向。`
        : '本轮尚未形成有美国证据信号的产品机会，需继续采样。',
    seller_verdict: opportunityResults.opportunities[0]
      ? `${opportunityResults.opportunities[0].label}为当前样本中最高信号方向；在商品和供应链数据补齐前仅用于验证优先级。`
      : opportunityResults.candidate_signals[0]
        ? `${opportunityResults.candidate_signals[0].label}目前仍是候选信号，尚未达到正式机会门槛。`
        : '证据不足，暂不建议形成商业结论。',
    opportunities: opportunityResults.opportunities,
    candidate_signals: opportunityResults.candidate_signals,
    competitors: opportunityResults.competitors,
    pain_points: painPoints,
    hotspots: {
      communities: countBy(usDetails.map((detail) => detail.post?.subreddit)),
      pains: painHotspots,
      behavior_segments: countBy(usDetails.flatMap((detail) => behaviorSegments(`${detail.post?.title ?? ''} ${detail.post?.body_original ?? detail.post?.selftext ?? ''}`))),
    },
    evidence: classifiedEvidence,
    configuration_suggestions: [...discoveredTerms.entries()].map(([term, count]) => ({
      term,
      type: 'brand-or-slang-candidate',
      evidence_count: count,
      auto_apply: false,
      status: 'pending-human-review',
    })),
    analysis_engine: {
      rules: { status: 'complete', version: '1.2.0' },
      llm: { status: 'not_requested' },
      active_result: 'rules',
    },
    privacy_note: 'Only public, research-relevant automotive content is retained; no sensitive demographic attributes are inferred.',
  };
}

export async function analyzeWithOptionalLlm(ruleAnalysis, llmAnalyzer) {
  if (!llmAnalyzer) return ruleAnalysis;
  try {
    const enriched = await llmAnalyzer(ruleAnalysis);
    return {
      ...ruleAnalysis,
      ...enriched,
      analysis_engine: {
        ...ruleAnalysis.analysis_engine,
        llm: { status: 'complete' },
        active_result: 'llm-enriched',
      },
    };
  } catch (error) {
    return {
      ...ruleAnalysis,
      analysis_engine: {
        ...ruleAnalysis.analysis_engine,
        llm: { status: 'failed', error: error instanceof Error ? error.message : String(error) },
        active_result: 'rules',
      },
    };
  }
}

function resolveGeography(post, config) {
  const explicit = post?.geography?.status;
  if (explicit === 'us' || explicit === 'unknown' || explicit === 'non_us') return explicit;

  const text = `${post?.title ?? ''}\n${post?.body_original ?? post?.selftext ?? ''}\n${post?.subreddit ?? ''}`;
  const targetPatterns = (config.market_rules?.geography?.target_signals ?? []).map((pattern) => new RegExp(pattern, 'i'));
  const nonTargetPatterns = (config.market_rules?.geography?.non_target_signals ?? []).map((pattern) => new RegExp(pattern, 'i'));

  if (nonTargetPatterns.some((pattern) => pattern.test(text)) || NON_TARGET_SIGNALS.some((pattern) => pattern.test(text))) return 'non_us';
  if (targetPatterns.some((pattern) => pattern.test(text)) || TARGET_SIGNALS.some((pattern) => pattern.test(text))) return 'us';
  return 'unknown';
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function countBy(values) {
  const counts = new Map();
  for (const value of values.filter(Boolean)) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

function trimQuote(value, limit = 500) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function behaviorSegments(text) {
  const segments = [];
  if (/replace|burn(?:ed|t)? out|failed|repair/i.test(text)) segments.push('维修替换');
  if (/upgrade|led|hid|retrofit|projector/i.test(text)) segments.push('升级改装');
  if (/off[- ]road|trail|truck|light bar|jeep|wrangler/i.test(text)) segments.push('越野/卡车');
  if (/style|appearance|sequential|smoked/i.test(text)) segments.push('外观改装');
  if (/night|visibility|safety|glare|dim/i.test(text)) segments.push('夜间安全');
  if (/fog|snow|rain|weather/i.test(text)) segments.push('恶劣天气');
  return segments;
}
