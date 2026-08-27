const PRODUCT_CONCEPTS = [
  { id: 'product-led-headlight-upgrade', label: 'LED 头灯升级方案', category: 'headlight', pattern: /\b(led headlights?|headlight upgrade|headlight bulbs?|h11|9005|9006|\bh7\b|\bh4\b|9012|h13)\b/i },
  { id: 'product-fog-light', label: '雾灯与恶劣天气照明', category: 'fog-light', pattern: /\b(fog light|fog lamp)\b/i },
  { id: 'product-tail-brake-light', label: '尾灯与刹车灯方案', category: 'tail-brake', pattern: /\b(tail light|taillight|brake light)\b/i },
  { id: 'product-turn-signal', label: '转向灯与流水转向方案', category: 'turn-signal', pattern: /\b(turn signal|indicator light|sequential signal)\b/i },
  { id: 'product-drl', label: '日间行车灯 DRL', category: 'drl', pattern: /\b(daytime running light|\bdrl\b)\b/i },
  { id: 'product-auxiliary-light', label: '辅助驾驶灯与越野灯', category: 'auxiliary', pattern: /\b(auxiliary light|driving light|light bar|off[- ]road light)\b/i },
  { id: 'product-headlight-assembly', label: '头灯总成与密封优化', category: 'assembly', pattern: /\b(headlights?[\s\S]{0,160}(?:assembl(?:y|ies)|housings?|sealed units?)|(?:assembl(?:y|ies)|housings?|sealed units?)[\s\S]{0,160}headlights?|headlamp assemblies?|condensation|fogging)\b/i },
  { id: 'product-projector-retrofit', label: '透镜与光型改装', category: 'projector', pattern: /\b(projector|retrofit|beam pattern|cutoff)\b/i },
  { id: 'product-wiring-adapter', label: '线束、继电器与 CANbus 适配', category: 'electrical', pattern: /\b(wiring harness|relay|canbus|adapter|error code|flicker)\b/i },
];

const PAINS = [
  ['闪烁/故障码', /\b(flicker|error code|warning light|hyperflash)\b/i],
  ['眩光/光型失控', /\b(glare|blinding|poor beam|beam pattern|cutoff)\b/i],
  ['亮度不足', /\b(dim|not bright|poor visibility|weak output)\b/i],
  ['进水/起雾', /\b(condensation|fogging|water ingress|moisture|leak)\b/i],
  ['过热/寿命短', /\b(overheat|burn(?:ed|t)? out|short life|failed early|heat sink)\b/i],
  ['安装/适配困难', /\b(doesn'?t fit|not fit|fitment|hard to install|installation issue|clearance)\b/i],
  ['法规/检测风险', /\b(illegal|inspection|dot approved|street legal|ticket)\b/i],
];

const SOLUTIONS = {
  '闪烁/故障码': '开发车辆协议兼容的驱动器或可验证的 CANbus 适配套件',
  '眩光/光型失控': '围绕原车反射碗/透镜提供光型匹配与可验证的截止线方案',
  '亮度不足': '在有效照度、散热和寿命之间重新平衡，而非只提高标称流明',
  '进水/起雾': '改进灯体密封、透气膜与安装界面，并提供可验证的防水测试',
  '过热/寿命短': '优化热路径、风扇可靠性和温控降额策略',
  '安装/适配困难': '提供车型适配清单、安装空间尺寸和连接器/防尘盖组合包',
  '法规/检测风险': '按适用法规明确道路用途边界并提供合规证据',
};

const FITMENT = /\b(h11|9005|9006|h7|h4|9012|h13|f-?150|silverado|tacoma|wrangler|ram 1500|ram 2500)\b/gi;
const PURCHASE = /\b(what should i buy|recommend|replacement|upgrade|under \$?\d+|budget|worth it|which brand|looking for)\b/i;
const PRICE = /(?:under|around|about|budget(?: is| of)?)\s*\$\s*(\d+(?:\.\d{1,2})?)/gi;

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function countBy(values) {
  const counts = new Map();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
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

function opportunityScore({ evidenceCount, engagement, painCount, purchaseCount }) {
  const score = 20 + evidenceCount * 12 + Math.log2(Math.max(1, engagement + 1)) * 6 + painCount * 7 + purchaseCount * 8;
  return Math.max(1, Math.min(100, Math.round(score)));
}

export function analyzeDetails(details, config = {}, { runId = 'unknown-run' } = {}) {
  const evidence = [];
  const usDetails = [];
  const unknownDetails = [];
  const nonUsDetails = [];
  const discoveredTerms = new Map();

  for (const detail of details) {
    const post = detail.post;
    const geography = post.geography?.status ?? 'unknown';
    if (geography === 'us') usDetails.push(detail);
    else if (geography === 'non_us') nonUsDetails.push(detail);
    else unknownDetails.push(detail);
    evidence.push({
      id: post.id,
      type: 'post',
      post_id: post.post_id,
      subreddit: post.subreddit,
      url: post.url,
      score: post.score,
      comment_count: post.comment_count,
      geography,
      quote_original: trimQuote(`${post.title}. ${post.body_original}`),
      fact_status: 'fact',
    });
    for (const comment of detail.comments ?? []) {
      evidence.push({
        id: comment.id,
        type: 'comment',
        post_id: post.post_id,
        subreddit: post.subreddit,
        url: comment.url,
        score: comment.score,
        geography,
        quote_original: trimQuote(comment.body_original),
        fact_status: 'fact',
      });
    }
    const combined = `${post.title}\n${post.body_original}\n${(detail.comments ?? []).map((comment) => comment.body_original).join('\n')}`;
    for (const brand of config.keywords?.candidate_only_brands ?? []) {
      if (new RegExp(`\\b${brand.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(combined)) {
        discoveredTerms.set(brand, (discoveredTerms.get(brand) ?? 0) + 1);
      }
    }
  }

  const opportunities = [];
  for (const concept of PRODUCT_CONCEPTS) {
    const contexts = [];
    for (const detail of usDetails) {
      const postText = `${detail.post.title}\n${detail.post.body_original}`;
      if (concept.pattern.test(postText)) contexts.push({ detail, text: postText, evidenceId: detail.post.id });
      for (const comment of detail.comments ?? []) {
        if (concept.pattern.test(comment.body_original)) contexts.push({ detail, text: comment.body_original, evidenceId: comment.id });
      }
    }
    const matched = unique(contexts.map((context) => context.detail));
    if (!matched.length) continue;
    const combined = contexts.map((context) => context.text).join('\n');
    const painPoints = PAINS.filter(([, pattern]) => pattern.test(combined)).map(([label]) => label);
    const fitmentTags = unique(combined.match(FITMENT)?.map((value) => value.toUpperCase().replace('F150', 'F-150')) ?? []);
    const prices = [...combined.matchAll(PRICE)].map((match) => Number(match[1]));
    const evidenceIds = unique(contexts.map((context) => context.evidenceId));
    const communities = unique(matched.map((detail) => detail.post.subreddit));
    const engagement = matched.reduce((sum, detail) => sum + detail.post.score + detail.post.comment_count, 0);
    const purchaseCount = matched.filter((detail) => PURCHASE.test(`${detail.post.title} ${detail.post.body_original}`)).length;
    const score = opportunityScore({ evidenceCount: matched.length, engagement, painCount: painPoints.length, purchaseCount });
    const solutionIdeas = unique(painPoints.map((pain) => SOLUTIONS[pain]));
    const facts = [
      `${matched.length} 篇具有美国信号的帖子涉及该产品/方案。`,
      `${communities.length} 个社区提供了可点击的 Reddit 证据。`,
      ...painPoints.map((pain) => `原文证据出现“${pain}”相关问题。`),
    ];
    const inferences = [
      '机会分为规则评分，用于同一批样本内排序，不代表市场规模。',
      painPoints.includes('安装/适配困难') || painPoints.includes('闪烁/故障码')
        ? '适配信息不足可能同时推高咨询和退货风险。'
        : '需要用商品、退货和供应链数据验证商业可行性。',
    ];
    opportunities.push({
      id: concept.id,
      label: concept.label,
      category: concept.category,
      opportunity_score: score,
      verdict: score >= 75 ? '高信号，建议验证' : score >= 50 ? '中等信号，继续采样' : '早期信号',
      evidence_ids: evidenceIds,
      communities,
      fitment_tags: fitmentTags,
      pain_points: painPoints,
      solution_ideas: solutionIdeas,
      behavior_segments: unique(matched.flatMap((detail) => behaviorSegments(`${detail.post.title} ${detail.post.body_original}`))),
      purchase_signal_count: purchaseCount,
      claims: {
        facts,
        inferences,
        unknowns: ['制造成本', '供应商 MOQ', '真实退货率', '美国市场销量', '法规认证状态'],
      },
      commercial: {
        pricing_band: prices.length ? { status: 'fact', value: `$${Math.min(...prices)}–$${Math.max(...prices)}`, evidence: 'Reddit user-stated budget' } : { status: 'unknown', value: null },
        margin_potential: { status: 'unknown', value: null },
        manufacturing_complexity: { status: 'unknown', value: null },
        shipping_complexity: { status: 'unknown', value: null },
        return_risk: painPoints.some((pain) => ['安装/适配困难', '闪烁/故障码', '眩光/光型失控'].includes(pain))
          ? { status: 'inference', value: '可能偏高', basis: '适配、电子兼容或光型问题在样本中出现' }
          : { status: 'unknown', value: null },
      },
      why_not_done: {
        status: 'inference',
        text: painPoints.length ? `现有方案同时受${painPoints.join('、')}影响，单一规格难覆盖全部车型。` : '样本不足，尚不能判断。',
      },
    });
  }
  opportunities.sort((a, b) => b.opportunity_score - a.opportunity_score);

  const usPostTexts = usDetails.map((detail) => `${detail.post.title} ${detail.post.body_original}`);
  const painHotspots = PAINS.map(([name, pattern]) => ({ name, count: usPostTexts.filter((text) => pattern.test(text)).length })).filter((item) => item.count).sort((a, b) => b.count - a.count);
  const segments = countBy(usDetails.flatMap((detail) => behaviorSegments(`${detail.post.title} ${detail.post.body_original}`)));

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
      communities: unique(usDetails.map((detail) => detail.post.subreddit)).length,
    },
    executive_summary: opportunities.length
      ? `本轮规则分析识别出 ${opportunities.length} 个有美国证据信号的车灯产品/解决方案方向。`
      : '本轮尚未形成有美国证据信号的产品机会，需继续采样。',
    seller_verdict: opportunities[0]
      ? `${opportunities[0].label}为当前样本中最高信号方向；在商品和供应链数据补齐前仅用于验证优先级。`
      : '证据不足，暂不建议形成商业结论。',
    opportunities,
    hotspots: {
      communities: countBy(usDetails.map((detail) => detail.post.subreddit)),
      pains: painHotspots,
      behavior_segments: segments,
    },
    evidence,
    configuration_suggestions: [...discoveredTerms.entries()].map(([term, count]) => ({
      term,
      type: 'brand-or-slang-candidate',
      evidence_count: count,
      auto_apply: false,
      status: 'pending-human-review',
    })),
    analysis_engine: {
      rules: { status: 'complete', version: '1.0.0' },
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
