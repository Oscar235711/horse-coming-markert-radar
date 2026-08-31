import fs from 'node:fs/promises';
import path from 'node:path';
import { REPORT_VISUAL_STYLES, reportVisualScript } from './report-visuals.mjs';

const THRESHOLD_CHECK_KEYS = [
  'qualified_evidence',
  'unique_users',
  'communities',
  'direct_experience',
  'contexts',
  'core_contexts',
  'score',
  'concrete_product',
  'existing_market',
  'entry_gap',
  'solution_validation',
];

const THRESHOLD_REQUIRED_DEFAULTS = {
  validated_entry: {
    unique_users: 8,
    communities: 2,
    direct_experience: 3,
    contexts: 0,
    core_contexts: 0,
    score: 55,
  },
  emerging_product: {
    unique_users: 5,
    communities: 0,
    direct_experience: 0,
    contexts: 2,
    core_contexts: 0,
    score: 50,
  },
  adjacent_bundle: {
    unique_users: 5,
    communities: 0,
    direct_experience: 0,
    contexts: 0,
    core_contexts: 2,
    score: 50,
  },
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function safeJson(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('&', '\\u0026');
}

function slug(value) {
  return String(value ?? 'item')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    || 'item';
}

function list(items, empty = '暂无') {
  if (!items?.length) return `<p class="muted">${escapeHtml(empty)}</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
}

function linkedEvidenceList(evidenceItems, empty = '暂无可点击证据') {
  if (!evidenceItems.length) return `<p class="muted">${escapeHtml(empty)}</p>`;
  return `<ul>${evidenceItems.map((item) => `<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.subreddit ?? 'unknown')} · ${escapeHtml(trim(item.quote_original ?? item.body_original ?? item.title ?? '', 120))}</a></li>`).join('')}</ul>`;
}

function statusField(label, value) {
  if (!value || value.status === 'unknown' || value.value == null || value.value === '' || (label === '价格带' && value.source !== 'product-bound')) return '';
  const status = value?.status ?? 'unknown';
  const display = value.value;
  return `<div class="commercial-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(display)}</strong><em class="status ${escapeHtml(status)}">${escapeHtml(status)}</em></div>`;
}

function buildEvidenceMap(items = []) {
  return new Map(items.map((item) => [item.id, item]));
}

function collectUnknowns(analysis) {
  const values = [];
  for (const item of analysis.opportunities ?? []) values.push(...(item.claims?.unknowns ?? []));
  for (const item of analysis.candidate_signals ?? []) values.push(...(item.claims?.unknowns ?? []));
  return [...new Set(values.filter(Boolean).map((value) => String(value)))];
}

function flattenExistingProducts(analysis) {
  const evidenceById = buildEvidenceMap(analysis.evidence ?? []);
  return (analysis.opportunities ?? []).flatMap((item) => (item.reference_products ?? item.existing_product_signals ?? []).map((signal) => {
    const evidence = typeof signal === 'string' ? evidenceById.get(signal) : null;
    return ({
    ...(typeof signal === 'string' ? {
      name: evidence?.title?.trim() || `相关产品提及 · ${item.label}`,
      evidence_ids: [signal],
      source_url: evidence?.url ?? null,
      specification: extractReferenceSpecification(evidence),
      market_heat: { status: 'unknown', value: null },
    } : signal),
    from: item.label,
  });
  }));
}

function extractReferenceSpecification(evidence) {
  const text = `${evidence?.title ?? ''} ${evidence?.body_original ?? ''}`;
  return (text.match(/\b(?:H11|9005|9006|H7|H4|9012|H13|F-?150|Silverado|Tacoma|Wrangler)\b/gi) ?? []).join(' · ') || null;
}

function renderOpportunityCard(item, evidenceById, { attributeName = 'data-opportunity-type' } = {}) {
  const evidenceItems = uniqueItems((item.evidence_ids ?? []).map((id) => evidenceById.get(id)).filter(Boolean));
  return `
    <article class="opportunity-card" ${attributeName}="${escapeHtml(item.opportunity_type ?? 'unknown')}">
      <div class="score-ring">${escapeHtml(item.opportunity_score ?? '候选')}</div>
      <div class="opportunity-main">
        <p class="eyebrow">${escapeHtml(item.opportunity_type ?? 'unknown')} · ${escapeHtml(item.verdict ?? '待验证')}</p>
        <h3>${escapeHtml(item.label ?? item.id ?? '未命名机会')}</h3>
        <div class="chips">${(item.fitment_tags ?? []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join('')}</div>
        <h4>痛点</h4>${list(item.pain_points)}
        <h4>机会/解决方向</h4>${list(item.solution_ideas ?? item.entry_gaps ?? [])}
        <h4>为什么还没有被很好解决</h4><p><span class="status ${escapeHtml(item.why_not_done?.status ?? 'unknown')}">${escapeHtml(item.why_not_done?.status ?? 'unknown')}</span> ${escapeHtml(item.why_not_done?.text ?? '未知')}</p>
        <h4>事实</h4>${list(item.claims?.facts)}
        <h4>推断</h4>${list(item.claims?.inferences)}
        <h4>未知项</h4>${list(item.claims?.unknowns)}
        <h4>参考产品与价格</h4>${renderReferenceProducts(item)}
        <details><summary>代表证据</summary>${linkedEvidenceList(evidenceItems)}</details>
      </div>
    </article>`;
}

function renderCandidateSignalCard(item, evidenceById) {
  const evidenceItems = uniqueItems((item.evidence_ids ?? item.qualified_evidence_ids ?? []).map((id) => evidenceById.get(id)).filter(Boolean));
  const failures = item.threshold_check?.failures ?? [];
  return `
    <article class="signal-card">
      <p class="eyebrow">候选信号 · ${escapeHtml(item.opportunity_type ?? 'candidate')}</p>
      <h3>${escapeHtml(item.label ?? item.id ?? '未命名候选')}</h3>
      <p>${escapeHtml(item.threshold_check?.passed ? '已达到正式机会门槛。' : `尚未达到正式机会门槛：${failures.join(' · ') || '待补证据'}`)}</p>
      <h4>事实</h4>${list(item.claims?.facts)}
      <h4>推断</h4>${list(item.claims?.inferences)}
      <h4>未知项</h4>${list(item.claims?.unknowns)}
      <details><summary>代表证据</summary>${linkedEvidenceList(evidenceItems)}</details>
    </article>`;
}

function renderPainCard(item, evidenceById) {
  const evidenceItems = uniqueItems((item.evidence_ids ?? []).map((id) => evidenceById.get(id)).filter(Boolean));
  return `
    <article class="signal-card">
      <p class="eyebrow">痛点</p>
      <h3>${escapeHtml(item.label ?? item.id ?? '未命名痛点')}</h3>
      <p>证据 ${escapeHtml(item.evidence_count ?? evidenceItems.length)} 条 · 社区 ${escapeHtml((item.communities ?? []).join(' · ') || '未知')}</p>
      <h4>关联正式机会</h4>${list(item.related_opportunity_ids)}
      <h4>关联解决方向</h4>${list(item.related_solution_ids)}
      <details><summary>代表证据</summary>${linkedEvidenceList(evidenceItems)}</details>
    </article>`;
}

function renderCompetitorCard(item, evidenceById, emptyLabel = '暂无') {
  const evidenceItems = uniqueItems((item.evidence_ids ?? []).map((id) => evidenceById.get(id)).filter(Boolean));
  return `
    <article class="signal-card">
      <h3>${escapeHtml(item.name ?? emptyLabel)}</h3>
      ${item.brand ? `<p>${escapeHtml(item.brand)} · ${escapeHtml(item.specification ?? '规格待核实')}</p>` : ''}
      ${item.source_url ? `<p><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">查看来源讨论</a></p>` : ''}
      ${item.from ? `<p class="muted">来源机会：${escapeHtml(item.from)}</p>` : ''}
      <details open><summary>证据</summary>${linkedEvidenceList(evidenceItems)}</details>
    </article>`;
}

function renderReferenceProducts(item) {
  const products = item.reference_products ?? [];
  const price = statusField('价格带', item.commercial?.pricing_band);
  const potential = statusField('市场参考热度', item.commercial?.market_potential);
  if (!products.length && !price && !potential) return '<p class="muted">暂无已核实的官网 / Amazon 产品资料</p>';
  const cards = products.map((product) => `<article class="reference-product"><h5>${escapeHtml(product.name ?? '未命名参考产品')}</h5><p>${escapeHtml(product.specification ?? '')}</p><p>${escapeHtml(product.packaging ?? '')}</p><p>${escapeHtml(product.heat ?? '')}</p><p>${product.official_url ? `<a href="${escapeHtml(product.official_url)}" target="_blank" rel="noreferrer">官网</a>` : ''} ${product.amazon_url ? `<a href="${escapeHtml(product.amazon_url)}" target="_blank" rel="noreferrer">Amazon</a>` : ''}</p></article>`).join('');
  return `<div class="reference-products">${cards}${price || potential ? `<div class="commercial-grid">${price}${potential}</div>` : ''}</div>`;
}

function renderEvidenceGroups(evidence) {
  const groups = new Map();
  for (const item of evidence ?? []) {
    const key = String(item.subreddit ?? 'unknown');
    const bucket = groups.get(key) ?? [];
    bucket.push(item);
    groups.set(key, bucket);
  }
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([community, items]) => {
    const representative = [...items]
      .sort((left, right) => (right.quality?.quality_score ?? 0) - (left.quality?.quality_score ?? 0) || (right.score ?? 0) - (left.score ?? 0))
      .slice(0, 3);
    const cards = representative.map((item) => `<article class="evidence-card" data-search="${escapeHtml(`${item.subreddit ?? ''} ${item.quote_original ?? ''}`.toLowerCase())}">
      <div class="evidence-meta"><span>r/${escapeHtml(item.subreddit ?? 'unknown')}</span><span>${escapeHtml(item.type ?? 'evidence')}</span><span>${escapeHtml(item.quality?.quality_band ?? 'unknown')}</span><span>${escapeHtml(item.geography ?? 'unknown')}</span></div>
      <blockquote lang="en">${escapeHtml(item.quote_original ?? item.body_original ?? item.title ?? '')}</blockquote><p class="muted">evidence_id: ${escapeHtml(item.id ?? 'unknown')}</p><a href="${escapeHtml(item.url ?? '#')}" target="_blank" rel="noreferrer">查看 Reddit 原文</a>
    </article>`).join('');
    return `<details class="evidence-community"><summary>r/${escapeHtml(community)} · ${items.length} 条（展开显示 3 条代表证据）</summary><div class="evidence-group">${cards || '<div class="empty">暂无证据。</div>'}</div></details>`;
  }).join('');
}

function renderPersonaPanel(personas) {
  if ((personas?.persona_status ?? personas?.status) === 'insufficient_sample') {
    return `
      <div class="empty">
        <p><strong>persona_status:</strong> insufficient_sample</p>
        <p>当前样本不足，不发布画像。下面列出缺口，方便继续采样。</p>
        ${list((personas?.missing ?? []).map((item) => `${item.metric}: ${item.actual}/${item.required}`), '暂无缺口明细')}
      </div>`;
  }
  return `
    <div class="panel stack">
      <h3>用户画像</h3>
      ${(personas?.clusters ?? []).map((cluster) => `
        <article class="signal-card">
          <h4>${escapeHtml(cluster.label ?? cluster.id ?? '未命名画像')}</h4>
          <p>${escapeHtml(cluster.user_count ?? 0)} 用户 · ${escapeHtml(cluster.evidence_count ?? 0)} 证据</p>
          <h5>重复痛点</h5>${list(cluster.recurring_pain_points)}
          <h5>探索过的方案</h5>${list(cluster.explored_solutions)}
          <h5>相关社区</h5>${list(cluster.related_communities)}
        </article>`).join('')}
    </div>`;
}


function renderReportHtml({ analysis, audienceMap, keywordCloud, manifest = {} }) {
  analysis = sanitizeAnalysisForReport(analysis);
  const evidenceById = buildEvidenceMap(analysis.evidence ?? []);
  const formalOpportunities = (analysis.opportunities ?? []).filter((item) => item.opportunity_type !== 'adjacent_bundle');
  const adjacentOpportunities = (analysis.opportunities ?? []).filter((item) => item.opportunity_type === 'adjacent_bundle');
  const renderedPainPoints = normalizePainPoints(analysis, formalOpportunities, analysis.candidate_signals ?? []);
  const candidateSignals = analysis.candidate_signals ?? [];
  const adjacentCandidates = candidateSignals.filter((item) => item.opportunity_type === 'adjacent_bundle');
  const competitorSignals = analysis.competitors ?? [];
  const existingProducts = flattenExistingProducts(analysis);
  const unknownItems = collectUnknowns(analysis);
  const qualifiedEvidence = (analysis.evidence ?? []).filter((item) => item.quality?.eligible !== false);
  const excludedEvidence = (analysis.evidence ?? []).filter((item) => item.quality?.eligible === false);
  const evidenceGroups = renderEvidenceGroups(analysis.evidence ?? []);

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>WhatToSell Radar · ${escapeHtml(analysis.run_id)}</title>
  <style>
    :root{--ink:#15221d;--muted:#67746c;--paper:#f3efe6;--panel:#fffdf9;--line:#d8d2c5;--green:#0d7c61;--gold:#c88a22;--red:#b24841;--shadow:0 18px 50px rgba(21,34,29,.08)}
    *{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#f6f2ea 0%,#efe8da 100%);color:var(--ink);font:15px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}button,input,select{font:inherit}a{color:var(--green)}
    header{position:sticky;top:0;z-index:30;padding:14px 4vw;border-bottom:1px solid var(--line);background:rgba(246,242,234,.96);backdrop-filter:blur(10px)}
    .header-row{display:flex;gap:16px;justify-content:space-between;align-items:flex-start}.brand{font-size:14px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.tabs{display:flex;gap:8px;flex-wrap:wrap}
    .tabs button,.pill,.cloud-term,.filter-btn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:8px 14px;cursor:pointer}.tabs button.active,.filter-btn.active,.pill.active{background:var(--ink);color:#fff;border-color:var(--ink)}
    main{max-width:1440px;margin:auto;padding:28px 4vw 72px}.tab-panel{display:none}.tab-panel.active{display:block}.hero{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:20px}
    .hero-main,.hero-side,.panel,.opportunity-card,.signal-card,.evidence-card,.map-layout{background:var(--panel);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}.hero-main,.hero-side,.panel,.signal-card,.evidence-card{padding:22px}
    .hero-main h1{margin:10px 0 16px;font-size:clamp(34px,5vw,64px);line-height:1.02;letter-spacing:-.05em;max-width:860px}.eyebrow{margin:0 0 8px;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--green);font-weight:800}
    .verdict{margin:14px 0 0;padding-left:16px;border-left:4px solid var(--gold);font-size:18px}.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:20px 0 0}.stat{padding:18px;border:1px solid var(--line);border-radius:16px;background:#fcfaf5}.stat strong{display:block;font-size:28px}.stat span{color:var(--muted)}
    h2{margin:28px 0 14px;font-size:28px;letter-spacing:-.03em}h3{margin:0 0 8px;font-size:23px}h4{margin:16px 0 6px}h5{margin:12px 0 6px;font-size:14px}.muted{color:var(--muted)}
    .grid-2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.stack{display:grid;gap:16px}.opportunity-card{display:grid;grid-template-columns:88px 1fr;gap:18px;padding:22px}.score-ring{width:72px;height:72px;border-radius:50%;border:7px solid var(--green);display:grid;place-items:center;font-size:24px;font-weight:800}.chips{display:flex;gap:6px;flex-wrap:wrap}.chips span{padding:3px 9px;background:#e7efe8;border-radius:999px;font-size:12px}
    .commercial-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:16px}.commercial-item{padding:10px;border:1px solid var(--line);border-radius:12px}.commercial-item span,.commercial-item strong{display:block}.commercial-item span{font-size:12px;color:var(--muted)}
    .status{display:inline-block;padding:2px 8px;border-radius:999px;background:#ece8df;font-style:normal;font-size:11px}.status.fact{background:#d7efe5;color:#0c5c47}.status.inference{background:#fff0cb;color:#7c5400}.status.unknown{background:#ececec;color:#5d5d5d}
    .empty{padding:24px;border:1px dashed var(--line);border-radius:18px;color:var(--muted);background:#fbf8f2}
    details.failures-detail{margin-top:10px;border:1px solid var(--line);border-radius:14px;background:#fcfaf5;padding:0 14px}
    details.failures-detail summary{cursor:pointer;padding:12px 2px;font-weight:700;user-select:none;list-style:none}
    details.failures-detail summary::-webkit-details-marker{display:none}
    details.failures-detail summary::before{content:"▸ ";color:var(--gold)}
    details.failures-detail[open] summary::before{content:"▾ "}
    .failures-list{margin:0 0 14px;padding-left:20px}.failures-list li{margin:4px 0;font-size:13px;line-height:1.5}.failures-list code{background:#efeae0;border-radius:6px;padding:1px 6px;font-size:12px}
    .map-empty,.cloud-empty{padding:48px 24px;text-align:center;color:var(--muted);font-size:16px}
    .evidence-tools{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px}.evidence-tools input,.evidence-tools select,.map-controls input{width:100%;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#fff}.evidence-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.evidence-card blockquote{margin:12px 0;font-family:Georgia,serif;font-size:17px}
    .evidence-community{grid-column:1/-1;border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff}.evidence-community summary{cursor:pointer;font-weight:700}.evidence-group{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}
    footer{margin-top:42px;color:var(--muted);font-size:12px}
    @media(max-width:1100px){.hero,.keyword-layout,.map-layout{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.commercial-grid,.grid-2,.evidence-list{grid-template-columns:1fr}.map-sidebar,.map-detail{border:0;border-bottom:1px solid var(--line)}}
    @media(max-width:720px){.header-row{flex-direction:column}.tabs{width:100%}.opportunity-card{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}}
    ${REPORT_VISUAL_STYLES}
  </style>
</head>
<body>
  <header>
    <div class="header-row">
      <div>
        <div class="brand">WhatToSell Style Offline Radar</div>
        <div class="muted">Seller Verdict、痛点、机会、Audience Map、关键词词云全部离线可读</div>
      </div>
      <nav class="tabs">
        <button class="active" data-tab="overview">卖家报告</button>
        <button data-tab="map">Audience Map</button>
        <button data-tab="keyword-cloud">关键词词云</button>
        <button data-tab="pain">痛点</button>
        <button data-tab="competitors">竞品/现有产品</button>
        <button data-tab="adjacent">邻近配套</button>
        <button data-tab="personas">用户画像</button>
        <button data-tab="evidence">证据库</button>
      </nav>
    </div>
  </header>
  <main>
    <section id="overview" class="tab-panel active">
      <div class="hero">
        <section class="hero-main">
          <p class="eyebrow">US automotive lighting · file:// offline</p>
          <h1>从真实抱怨与购买线索里，筛出能卖的机会。</h1>
          <p>${escapeHtml(analysis.executive_summary)}</p>
          <p class="verdict"><strong>Seller Verdict：</strong>${escapeHtml(analysis.seller_verdict)}</p>
          <div class="stats">
            <div class="stat"><strong>${escapeHtml(analysis.metrics?.posts_analyzed ?? 0)}</strong><span>帖子</span></div>
            <div class="stat"><strong>${escapeHtml(analysis.metrics?.comments_analyzed ?? 0)}</strong><span>评论</span></div>
            <div class="stat"><strong>${escapeHtml(qualifiedEvidence.length)}</strong><span>合格证据</span></div>
            <div class="stat"><strong>${escapeHtml(candidateSignals.length)}</strong><span>候选信号</span></div>
            <div class="stat"><strong>${escapeHtml(manifest.counts?.failures ?? 0)}</strong><span>失败记录</span></div>
          </div>
        </section>
        <aside class="hero-side">
          <p class="eyebrow">研究边界</p>
          <p><strong>国家：</strong>${escapeHtml(analysis.scope?.country ?? '未知')}</p>
          <p><strong>地理规则：</strong>${escapeHtml(analysis.scope?.geography_rule ?? '未知')}</p>
          <p><strong>分析引擎：</strong>${escapeHtml(analysis.analysis_engine?.active_result ?? 'unknown')}</p>
          <p><strong>运行状态：</strong>${escapeHtml(manifest.status ?? 'unknown')}</p>
          <p><strong>sample_status：</strong>${escapeHtml(manifest.sample_status ?? 'unknown')}</p>
          <p><strong>persona_status：</strong>${escapeHtml(analysis.personas?.persona_status ?? analysis.personas?.status ?? 'unknown')}</p>
          <p><strong>隐私：</strong>${escapeHtml(analysis.privacy_note ?? '未知')}</p>
        </aside>
      </div>

      <div class="grid-2" style="margin-top:20px">
        <section class="panel">
          <h2 style="margin-top:0">正式机会</h2>
          <div id="formal-opportunities" class="stack">${formalOpportunities.length ? formalOpportunities.map((item) => renderOpportunityCard(item, evidenceById)).join('') : '<div class="empty">当前没有达到正式机会门槛的非邻近机会。</div>'}</div>
        </section>
        <section class="panel">
          <h2 style="margin-top:0">候选信号</h2>
          <div class="stack">${candidateSignals.length ? candidateSignals.map((item) => renderCandidateSignalCard(item, evidenceById)).join('') : '<div class="empty">当前没有待验证候选信号。</div>'}</div>
        </section>
      </div>

      <section class="panel" style="margin-top:20px">
        <h2 style="margin-top:0">研究范围、关键词与失败记录</h2>
        <p><strong>正式词：</strong>${escapeHtml((analysis.research_keywords?.anchors ?? []).join(' · ') || '未知')}</p>
        <p><strong>探索词：</strong>${escapeHtml((analysis.research_keywords?.exploratory_used ?? []).join(' · ') || '暂无')}</p>
        <p><strong>扩展词：</strong>${escapeHtml((analysis.research_keywords?.expanded ?? []).join(' · ') || '暂无')}</p>
        <details class="failures-detail"${analysis.collection_failures?.length ? '' : ' open'}>
          <summary>失败记录（${analysis.collection_failures?.length ?? 0} 条）${analysis.collection_failures?.length ? ' <span class="muted">点击展开</span>' : ' · 无'}</summary>
          ${analysis.collection_failures?.length ? `<ul class="failures-list">${analysis.collection_failures.map((item) => `<li><code>${escapeHtml(item.stage)}</code> · ${escapeHtml(item.query ?? item.post_id ?? '')} · <span class="muted">${escapeHtml(item.error ?? '')}</span></li>`).join('')}</ul>` : '<p class="muted">本次运行无失败记录。</p>'}
        </details>
      </section>

      <section class="panel" style="margin-top:20px">
        <h2 style="margin-top:0">未知项</h2>
        ${list(unknownItems, '暂无未知项')}
      </section>
    </section>

    <section id="map" class="tab-panel">
      <div class="visual-heading"><div><p class="eyebrow">AUDIENCE MAP / COMMUNITY EXPLORER</p><h2>从社区，找到产品机会。</h2><p>每条关系都有 Reddit 证据。选择社区下钻，或从产品反查讨论来源。</p></div></div>
      <div class="map-layout">
        <aside class="map-sidebar">
          <p class="eyebrow">探索市场关系</p>
          <div class="map-controls">
            <input id="map-search" type="search" aria-label="搜索产品、fitment 或社区" placeholder="搜索社区、产品或车型…">
            <div id="category-filters" class="filters"></div>
            <button id="reset-map" class="visual-reset" type="button">← 返回全局社区图</button>
          </div>
          <div class="visual-section-title">社区来源</div><div id="map-community-list"></div>
          <div class="visual-section-title" id="map-product-title">产品机会 · 点击反查</div><div id="map-product-list"></div>
          <div class="visual-section-title">图例 / 研究边界</div>
          <div class="visual-legend"><i class="visual-dot community"></i>社区 · 大小 = 关联产品数</div>
          <div class="visual-legend"><i class="visual-dot"></i>产品 · 大小 = 机会评分</div>
          <p>仅表达产品—社区—证据关系，不代表人口画像、市场占有率或真实用户人数。</p>
        </aside>
        <div class="map-canvas">
          <div class="map-toolbar"><div><button id="map-back" class="filter-btn" type="button" hidden>← 返回上一级</button> <button id="map-view-toggle" class="filter-btn" type="button">社区总览</button></div><span id="map-metrics" class="visual-metric"></span></div>
          <svg id="audience-map" viewBox="0 0 1000 720" role="group" aria-label="Audience Map bipartite graph"></svg>
          <div id="map-help" class="map-help"></div>
        </div>
        <aside id="map-detail" class="visual-drawer" aria-label="节点详情" hidden><button id="map-detail-close" class="visual-close" type="button" aria-label="关闭节点详情">×</button><div id="map-detail-content"></div></aside>
      </div>
    </section>

    <section id="keyword-cloud" class="tab-panel">
      <div class="visual-heading"><div><p class="eyebrow">KEYWORD LANDSCAPE / EVIDENCE WEIGHTED</p><h2>让市场讨论，浮现重点。</h2><p>词越大，展示权重越高。点击词语追溯用户、社区和原始证据。</p></div></div>
      <div class="keyword-layout">
        <aside class="cloud-sidebar">
          <p class="eyebrow">关键词词云</p>
          <input id="keyword-cloud-search" type="search" aria-label="搜索关键词、社区或类别" placeholder="搜索关键词或社区…">
          <div class="visual-section-title">词类别</div><div class="filters" id="keyword-cloud-categories"></div>
          <div class="visual-section-title">探索状态</div><div class="filters" id="keyword-cloud-statuses"></div>
          <label for="keyword-cloud-score">最低发现分 <output id="cloud-score-value">${escapeHtml(keywordCloud?.filters?.minimum_score ?? 0)}</output></label>
          <input id="keyword-cloud-score" type="range" min="0" max="100" value="${escapeHtml(keywordCloud?.filters?.minimum_score ?? 0)}">
          <button id="keyword-cloud-reset" class="visual-reset" type="button">↺ 重置词云</button>
          <div class="visual-section-title">颜色图例</div><div id="cloud-legend"></div>
          <p>字号基于有效用户、证据质量和社区覆盖等综合权重，不表示原始词频或市场规模。同权重词使用相同字号。</p>
          <details class="cloud-list"><summary>查看完整关键词列表</summary><div id="cloud-term-list"></div></details>
        </aside>
        <section class="cloud-stage" id="keyword-cloud-canvas">
          <div id="cloud-count" class="visual-metric" aria-live="polite"></div>
          <canvas id="keyword-wordcloud" width="1000" height="650" role="img" aria-label="按证据权重排布的关键词词云；可使用左侧完整关键词列表查看详情"></canvas>
          <div id="cloud-caption" class="cloud-caption"></div>
        </section>
        <aside class="visual-drawer" id="keyword-cloud-detail" aria-label="关键词详情" hidden><button id="keyword-cloud-detail-close" class="visual-close" type="button" aria-label="关闭关键词详情">×</button><div id="keyword-cloud-detail-content"></div></aside>
      </div>
      <div id="cloud-tooltip" class="cloud-tooltip" role="tooltip" hidden></div>
    </section>

    <section id="pain" class="tab-panel">
      <h2>痛点分布</h2>
      <div class="grid-2">${renderedPainPoints.length ? renderedPainPoints.map((item) => renderPainCard(item, evidenceById)).join('') : '<div class="empty">当前没有痛点记录。</div>'}</div>
    </section>

    <section id="competitors" class="tab-panel">
      <div class="grid-2">
        <section class="panel">
          <h2 style="margin-top:0">竞品</h2>
          <div class="stack">${competitorSignals.length ? competitorSignals.map((item) => renderCompetitorCard(item, evidenceById)).join('') : '<div class="empty">暂无竞品证据。</div>'}</div>
        </section>
        <section class="panel">
          <h2 style="margin-top:0">现有产品</h2>
          <div class="stack">${existingProducts.length ? existingProducts.map((item) => renderCompetitorCard(item, evidenceById, '未命名现有产品')).join('') : '<div class="empty">暂无现有产品证据。</div>'}</div>
        </section>
      </div>
    </section>

    <section id="adjacent" class="tab-panel">
      <h2>邻近配套</h2>
      <div class="stack">${adjacentOpportunities.map((item) => renderOpportunityCard(item, evidenceById, { attributeName: 'data-adjacent-type' })).join('')}${adjacentCandidates.map((item) => renderCandidateSignalCard(item, evidenceById)).join('')}${adjacentOpportunities.length || adjacentCandidates.length ? '' : '<div class="empty">当前没有邻近配套机会或待验证配套信号。</div>'}</div>
    </section>

    <section id="personas" class="tab-panel">
      <h2>用户画像</h2>
      ${renderPersonaPanel(analysis.personas)}
    </section>

    <section id="evidence" class="tab-panel">
      <h2>合格证据库与排除项</h2>
      <div class="panel" style="margin-bottom:16px">
        <div class="evidence-tools"><input id="evidence-search" placeholder="搜索社区或英文原文"><button id="evidence-export" class="filter-btn" type="button">导出爬取结果 CSV</button></div>
        <p><strong>合格证据：</strong>${escapeHtml(qualifiedEvidence.length)} · <strong>排除项：</strong>${escapeHtml(excludedEvidence.length)}</p>
      </div>
      <div id="evidence-list" class="evidence-list">${evidenceGroups || '<div class="empty">暂无证据。</div>'}</div>
    </section>

    <footer>Run ${escapeHtml(analysis.run_id)} · Generated ${escapeHtml(analysis.generated_at)} · JSON is the single source of truth.</footer>
  </main>
  <script id="analysis-data" type="application/json">${safeJson(analysis)}</script>
  <script id="audience-map-data" type="application/json">${safeJson(audienceMap)}</script>
  <script id="keyword-cloud-data" type="application/json">${safeJson(keywordCloud ?? { terms: [], filters: { categories: [], statuses: [], minimum_score: 0 } })}</script>
  <script id="manifest-data" type="application/json">${safeJson(manifest)}</script>
  <script>
    const analysis = JSON.parse(document.getElementById('analysis-data').textContent);
    const audienceMap = JSON.parse(document.getElementById('audience-map-data').textContent);
    const keywordCloud = JSON.parse(document.getElementById('keyword-cloud-data').textContent);
    const evidenceById = new Map((analysis.evidence || []).map(item => [item.id, item]));
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

    document.querySelectorAll('.tabs button').forEach(button => button.addEventListener('click', () => {
      document.querySelectorAll('.tabs button').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.id === button.dataset.tab));
      document.dispatchEvent(new CustomEvent('radar-tab-change', { detail: button.dataset.tab }));
    }));

    ${reportVisualScript()}

    document.getElementById('evidence-search').addEventListener('input', event => {
      const query = event.target.value.trim().toLowerCase();
      document.querySelectorAll('.evidence-card').forEach(card => {
        card.hidden = Boolean(query) && !card.dataset.search.includes(query);
      });
    });

    document.getElementById('evidence-export').addEventListener('click', () => {
      const rows = analysis.evidence || [];
      const columns = ['id','type','post_id','author','subreddit','title','body_original','quote_original','url','score','comment_count','geography','precision','link_precision'];
      const cell = value => { const text = String(value ?? '').replace(/^[=+\\-@]/, "'\\$&"); return '"' + text.replace(/"/g, '""') + '"'; };
      const csv = '\\uFEFF' + [columns, ...rows.map(row => columns.map(column => cell(row[column])))].map(row => row.join(',')).join('\\r\\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = (analysis.run_id || 'radar') + '-crawl-results.csv'; link.click(); URL.revokeObjectURL(link.href);
    });


    const initialTab = location.hash.replace(/^#/, '');
    if (initialTab) {
      const initialButton = document.querySelector('.tabs button[data-tab="' + initialTab + '"]');
      if (initialButton) initialButton.click();
    }
  </script>
</body>
</html>`;
}

function sanitizeAnalysisForReport(value = {}) {
  return {
    ...value,
    opportunities: (value.opportunities ?? []).map((item) => ({
      ...item,
      commercial: {
        pricing_band: item.commercial?.pricing_band?.source === 'product-bound' ? item.commercial.pricing_band : { status: 'unknown', value: null },
        market_potential: item.commercial?.market_potential?.status === 'fact' ? item.commercial.market_potential : { status: 'unknown', value: null },
      },
    })),
    candidate_signals: (value.candidate_signals ?? []).map((item) => ({
      ...item,
      commercial: { pricing_band: { status: 'unknown', value: null }, market_potential: { status: 'unknown', value: null } },
    })),
  };
}

export { renderReportHtml };

export async function writeReportArtifacts({ runDir, analysis, audienceMap, keywordCloud, manifest = {} }) {
  await fs.mkdir(runDir, { recursive: true });
  const opportunitiesArtifact = buildOpportunityArtifact(analysis, manifest);
  const paths = {
    analysis: path.join(runDir, 'analysis.json'),
    audienceMap: path.join(runDir, 'audience_map.json'),
    keywordCloud: path.join(runDir, 'keyword_cloud.json'),
    opportunities: path.join(runDir, 'opportunities.json'),
    personas: path.join(runDir, 'personas.json'),
    qualityEvidence: path.join(runDir, 'quality_evidence.jsonl'),
    excludedEvidence: path.join(runDir, 'excluded_evidence.jsonl'),
    evidence: path.join(runDir, 'evidence.jsonl'),
    html: path.join(runDir, 'report.html'),
  };

  await fs.writeFile(paths.analysis, `${JSON.stringify(analysis, null, 2)}\n`, 'utf8');
  await fs.writeFile(paths.audienceMap, `${JSON.stringify(audienceMap, null, 2)}\n`, 'utf8');
  await fs.writeFile(paths.keywordCloud, `${JSON.stringify(keywordCloud, null, 2)}\n`, 'utf8');
  await fs.writeFile(paths.opportunities, `${JSON.stringify(opportunitiesArtifact, null, 2)}\n`, 'utf8');
  await fs.writeFile(paths.personas, `${JSON.stringify(analysis.personas ?? {}, null, 2)}\n`, 'utf8');
  await writeJsonl(paths.qualityEvidence, (analysis.evidence ?? []).filter((item) => item.quality?.eligible !== false));
  await writeJsonl(paths.excludedEvidence, (analysis.evidence ?? []).filter((item) => item.quality?.eligible === false));
  await writeJsonl(paths.evidence, analysis.evidence ?? []);
  await fs.writeFile(paths.html, renderReportHtml({ analysis, audienceMap, keywordCloud, manifest }), 'utf8');
  return paths;
}

async function writeJsonl(filePath, rows) {
  const text = rows.length ? `${rows.map((row) => JSON.stringify(row)).join('\n')}\n` : '';
  await fs.writeFile(filePath, text, 'utf8');
}

function trim(value, limit) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function uniqueItems(items) {
  const seen = new Set();
  const output = [];
  for (const item of items) {
    if (!item?.id || seen.has(item.id)) continue;
    seen.add(item.id);
    output.push(item);
  }
  return output;
}

function buildOpportunityArtifact(analysis, manifest) {
  const formalOpportunities = (analysis.opportunities ?? []).map((item) => normalizeFormalOpportunity(item));
  const candidateSignals = (analysis.candidate_signals ?? []).map((item) => normalizeCandidateSignal(item));
  return {
    schema_version: analysis.schema_version ?? '1.0.0',
    run_id: analysis.run_id ?? manifest.run_id ?? 'unknown-run',
    generated_at: analysis.generated_at ?? new Date().toISOString(),
    opportunities: formalOpportunities,
    candidate_signals: candidateSignals,
    competitors: normalizeSignalList(analysis.competitors ?? []),
    pain_points: normalizePainPoints(analysis, formalOpportunities, candidateSignals),
  };
}

function normalizeFormalOpportunity(item = {}) {
  return {
    id: String(item.id ?? ''),
    label: String(item.label ?? ''),
    category: String(item.category ?? 'unknown'),
    opportunity_type: String(item.opportunity_type ?? 'validated_entry'),
    opportunity_score: Number(item.opportunity_score ?? 0),
    verdict: String(item.verdict ?? ''),
    evidence_ids: uniqueStrings(item.evidence_ids ?? []),
    qualified_evidence_ids: uniqueStrings(item.qualified_evidence_ids ?? item.evidence_ids ?? []),
    communities: uniqueStrings(item.communities ?? []),
    fitment_tags: uniqueStrings(item.fitment_tags ?? []),
    pain_points: uniqueStrings(item.pain_points ?? []),
    solution_ideas: uniqueStrings(item.solution_ideas ?? []),
    claims: normalizeClaims(item.claims),
    why_not_done: normalizeWhyNotDone(item.why_not_done),
    commercial: normalizeCommercial(item.commercial),
    reference_products: normalizeReferenceProducts(item.reference_products ?? item.existing_product_signals ?? []),
    competitor_signals: normalizeSignalList(item.competitor_signals ?? []),
    existing_product_signals: normalizeSignalList(item.existing_product_signals ?? []),
    entry_gaps: uniqueStrings(item.entry_gaps ?? []),
  };
}

function normalizeCandidateSignal(item = {}) {
  return {
    id: String(item.id ?? ''),
    label: String(item.label ?? ''),
    category: String(item.category ?? 'candidate_signal'),
    opportunity_type: String(item.opportunity_type ?? 'emerging_product'),
    threshold_check: normalizeThresholdCheck(item.threshold_check, item),
    evidence_ids: uniqueStrings(item.evidence_ids ?? []),
    qualified_evidence_ids: uniqueStrings(item.qualified_evidence_ids ?? item.evidence_ids ?? []),
    claims: normalizeClaims(item.claims),
    why_not_done: normalizeWhyNotDone(item.why_not_done),
  };
}

function normalizePainPoints(analysis, formalOpportunities, candidateSignals) {
  return (analysis.pain_points ?? []).map((item) => {
    const label = String(item.label ?? item.id ?? '');
    const relatedOpportunityIds = uniqueStrings([
      ...(item.related_opportunity_ids ?? []),
      ...formalOpportunities.filter((opportunity) => (opportunity.pain_points ?? []).includes(label)).map((opportunity) => opportunity.id),
    ]);
    const relatedSolutionIds = uniqueStrings([
      ...(item.related_solution_ids ?? []),
      ...formalOpportunities.filter((opportunity) => (opportunity.pain_points ?? []).includes(label)).flatMap((opportunity) => opportunity.solution_ideas ?? []),
      ...candidateSignals.filter((signal) => (signal.pain_points ?? []).includes(label)).flatMap((signal) => signal.solution_ideas ?? []),
    ]);
    return {
      id: String(item.id ?? ''),
      label,
      evidence_ids: uniqueStrings(item.evidence_ids ?? []),
      communities: uniqueStrings(item.communities ?? []),
      evidence_count: Number(item.evidence_count ?? item.evidence_ids?.length ?? 0),
      qualified_evidence_count: Number(item.qualified_evidence_count ?? item.evidence_count ?? item.evidence_ids?.length ?? 0),
      unique_users: Number(item.unique_users ?? item.unique_user_count ?? 0),
      fact_status: 'fact',
      related_opportunity_ids: relatedOpportunityIds,
      related_solution_ids: relatedSolutionIds,
    };
  });
}

function normalizeThresholdCheck(value = {}, item = {}) {
  const explicitChecks = isRecord(value?.checks) ? value.checks : {};
  const explicitFailures = new Set(uniqueStrings(value?.failures ?? []).filter((name) => THRESHOLD_CHECK_KEYS.includes(name)));
  const hasExplicitCheckData = Object.keys(explicitChecks).length > 0 || explicitFailures.size > 0;
  const rawPassed = value?.passed === true;
  const fallbackCheckValue = hasExplicitCheckData ? true : rawPassed;
  const checks = Object.fromEntries(THRESHOLD_CHECK_KEYS.map((name) => {
    if (typeof explicitChecks[name] === 'boolean') return [name, explicitChecks[name]];
    if (explicitFailures.has(name)) return [name, false];
    return [name, fallbackCheckValue];
  }));
  const failures = THRESHOLD_CHECK_KEYS.filter((name) => checks[name] === false);
  const requiredDefaults = THRESHOLD_REQUIRED_DEFAULTS[item?.opportunity_type] ?? THRESHOLD_REQUIRED_DEFAULTS.emerging_product;
  const explicitRequired = isRecord(value?.required) ? value.required : {};
  const required = Object.fromEntries(Object.entries(requiredDefaults).map(([name, fallback]) => [
    name,
    normalizeInteger(explicitRequired[name], fallback),
  ]));
  return {
    passed: failures.length === 0 ? (hasExplicitCheckData ? true : rawPassed) : false,
    failures,
    checks,
    required,
  };
}

function normalizeClaims(value = {}) {
  return {
    facts: uniqueStrings(value.facts ?? []),
    inferences: uniqueStrings(value.inferences ?? []),
    unknowns: uniqueStrings(value.unknowns ?? []),
  };
}

function normalizeWhyNotDone(value = {}) {
  const status = ['fact', 'inference', 'unknown'].includes(value?.status) ? value.status : 'unknown';
  return {
    status,
    text: value?.text == null ? null : String(value.text),
  };
}

function normalizeCommercial(value = {}) {
  return {
    pricing_band: normalizeCommercialField(value.pricing_band),
    margin_potential: normalizeCommercialField(value.margin_potential),
    market_potential: normalizeCommercialField(value.market_potential),
    manufacturing_complexity: normalizeCommercialField(value.manufacturing_complexity),
    shipping_complexity: normalizeCommercialField(value.shipping_complexity),
    return_risk: normalizeCommercialField(value.return_risk),
  };
}

function normalizeCommercialField(value = {}) {
  const status = ['fact', 'inference', 'unknown'].includes(value?.status) ? value.status : 'unknown';
  return {
    status,
    value: value?.value ?? null,
    evidence_ids: uniqueStrings(value?.evidence_ids ?? []),
    basis: value?.basis == null ? undefined : String(value.basis),
    source: value?.source == null ? undefined : String(value.source),
  };
}

function normalizeSignalList(items) {
  return (items ?? []).map((item) => {
    if (typeof item === 'string') {
      return { name: item, evidence_ids: [] };
    }
    return {
      name: String(item?.name ?? ''),
      evidence_ids: uniqueStrings(item?.evidence_ids ?? []),
    };
  }).filter((item) => item.name);
}

function normalizeReferenceProducts(items) {
  return (items ?? []).map((item) => typeof item === 'string'
    ? { name: item, evidence_ids: [] }
    : { ...item, name: String(item?.name ?? ''), evidence_ids: uniqueStrings(item?.evidence_ids ?? []) })
    .filter((item) => item.name);
}

function uniqueStrings(values) {
  return [...new Set((values ?? []).filter(Boolean).map((value) => String(value)))];
}

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeInteger(value, fallback = 0) {
  const numeric = Number(value);
  if (Number.isInteger(numeric) && numeric >= 0) return numeric;
  return fallback;
}
