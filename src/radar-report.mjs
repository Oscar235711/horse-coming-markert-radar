import fs from 'node:fs/promises';
import path from 'node:path';

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
  const status = value?.status ?? 'unknown';
  const display = value?.value ?? '未知';
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
  return (analysis.opportunities ?? []).flatMap((item) => (item.existing_product_signals ?? []).map((signal) => ({
    ...signal,
    from: item.label,
  })));
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
        <div class="commercial-grid">
          ${statusField('价格带', item.commercial?.pricing_band)}
          ${statusField('制造复杂度', item.commercial?.manufacturing_complexity)}
          ${statusField('运输复杂度', item.commercial?.shipping_complexity)}
          ${statusField('退货风险', item.commercial?.return_risk)}
        </div>
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
      ${item.from ? `<p class="muted">来源机会：${escapeHtml(item.from)}</p>` : ''}
      <details open><summary>证据</summary>${linkedEvidenceList(evidenceItems)}</details>
    </article>`;
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

function renderKeywordTerms(keywordCloud) {
  if (!keywordCloud?.terms?.length) return '<div class="empty">当前没有可展示的关键词词云。</div>';
  return keywordCloud.terms.map((term) => `
    <button
      type="button"
      class="cloud-term"
      data-term-id="${escapeHtml(slug(term.term))}"
      data-category="${escapeHtml(term.category ?? 'product')}"
      data-status="${escapeHtml(term.status ?? 'candidate_review')}"
      data-score="${escapeHtml(term.discovery_score ?? 0)}"
      data-label="${escapeHtml(`${term.term} ${(term.categories ?? []).join(' ')} ${(term.communities ?? []).join(' ')}`.toLowerCase())}"
      style="font-size:${Math.max(14, Math.min(42, Number(term.display_weight ?? term.discovery_score ?? 10) / 2 + 12))}px"
    >${escapeHtml(term.term)}</button>`).join('');
}

function renderReportHtml({ analysis, audienceMap, keywordCloud, manifest = {} }) {
  const evidenceById = buildEvidenceMap(analysis.evidence ?? []);
  const formalOpportunities = (analysis.opportunities ?? []).filter((item) => item.opportunity_type !== 'adjacent_bundle');
  const adjacentOpportunities = (analysis.opportunities ?? []).filter((item) => item.opportunity_type === 'adjacent_bundle');
  const candidateSignals = analysis.candidate_signals ?? [];
  const competitorSignals = analysis.competitors ?? [];
  const existingProducts = flattenExistingProducts(analysis);
  const unknownItems = collectUnknowns(analysis);
  const qualifiedEvidence = (analysis.evidence ?? []).filter((item) => item.quality?.eligible !== false);
  const excludedEvidence = (analysis.evidence ?? []).filter((item) => item.quality?.eligible === false);
  const evidenceCards = (analysis.evidence ?? []).map((item) => `
    <article class="evidence-card" data-search="${escapeHtml(`${item.subreddit ?? ''} ${item.quote_original ?? ''}`.toLowerCase())}">
      <div class="evidence-meta">
        <span>r/${escapeHtml(item.subreddit ?? 'unknown')}</span>
        <span>${escapeHtml(item.type ?? 'evidence')}</span>
        <span>${escapeHtml(item.quality?.quality_band ?? 'unknown')}</span>
        <span>${escapeHtml(item.geography ?? 'unknown')}</span>
      </div>
      <blockquote lang="en">${escapeHtml(item.quote_original ?? item.body_original ?? item.title ?? '')}</blockquote>
      <p class="muted">evidence_id: ${escapeHtml(item.id ?? 'unknown')}</p>
      <a href="${escapeHtml(item.url ?? '#')}" target="_blank" rel="noreferrer">查看 Reddit 原文</a>
    </article>`).join('');

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
    .map-layout{display:grid;grid-template-columns:260px minmax(0,1fr) 320px;min-height:700px;overflow:hidden}.map-sidebar,.map-detail{padding:20px;background:#faf7f1}.map-sidebar{border-right:1px solid var(--line)}.map-detail{border-left:1px solid var(--line)}.map-canvas{overflow:auto;background-image:radial-gradient(#dbd4c6 1px,transparent 1px);background-size:24px 24px}.map-canvas svg{width:100%;height:700px;min-width:760px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.graph-node{cursor:pointer}.graph-node text{font-size:11px;pointer-events:none;fill:var(--ink)}.graph-node.product circle{fill:var(--green);stroke:#fff;stroke-width:2}.graph-node.community circle{fill:#fff;stroke:#5f6861;stroke-width:2}.graph-edge{stroke:#b8bbb6;stroke-width:1;opacity:.7}.graph-node.dim,.graph-edge.dim{opacity:.08}.graph-node.selected circle{stroke:var(--gold);stroke-width:5}
    .keyword-layout{display:grid;grid-template-columns:320px minmax(0,1fr) 320px;gap:16px}.keyword-cloud{min-height:360px;padding:20px;display:flex;flex-wrap:wrap;gap:12px;align-content:flex-start}.cloud-term{box-shadow:none}.cloud-term.hidden{display:none}.detail-card{padding:22px}.detail-card h3{margin-bottom:12px}
    .evidence-tools{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px}.evidence-tools input,.evidence-tools select,.map-controls input{width:100%;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#fff}.evidence-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.evidence-card blockquote{margin:12px 0;font-family:Georgia,serif;font-size:17px}
    footer{margin-top:42px;color:var(--muted);font-size:12px}
    @media(max-width:1100px){.hero,.keyword-layout,.map-layout{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.commercial-grid,.grid-2,.evidence-list{grid-template-columns:1fr}.map-sidebar,.map-detail{border:0;border-bottom:1px solid var(--line)}}
    @media(max-width:720px){.header-row{flex-direction:column}.tabs{width:100%}.opportunity-card{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}}
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
      <div class="map-layout">
        <aside class="map-sidebar">
          <p class="eyebrow">Audience Map · 二部图</p>
          <p>正式机会和 Reddit 社区分开显示，便于把“产品机会”和“讨论来源”拆开看。</p>
          <div class="map-controls">
            <input id="map-search" placeholder="搜索产品、fitment 或社区">
            <div id="category-filters" class="filters"></div>
            <button id="reset-map" class="filter-btn">重置</button>
          </div>
        </aside>
        <div class="map-canvas"><svg id="audience-map" viewBox="0 0 1000 700" role="img" aria-label="Audience Map bipartite graph"></svg></div>
        <aside id="map-detail" class="map-detail"><p class="muted">点击产品或社区查看机会、痛点和证据。</p></aside>
      </div>
    </section>

    <section id="keyword-cloud" class="tab-panel">
      <div class="keyword-layout">
        <aside class="panel">
          <p class="eyebrow">关键词词云</p>
          <p>字体大小只表示标准化展示权重，不代表市场规模。</p>
          <input id="keyword-cloud-search" placeholder="搜索关键词、社区或类别">
          <div class="filters" id="keyword-cloud-categories"></div>
          <div class="filters" id="keyword-cloud-statuses"></div>
          <label for="keyword-cloud-score">最低分数</label>
          <input id="keyword-cloud-score" type="range" min="0" max="100" value="${escapeHtml(keywordCloud?.filters?.minimum_score ?? 0)}">
          <button id="keyword-cloud-reset" class="filter-btn">重置词云</button>
        </aside>
        <section class="panel keyword-cloud" id="keyword-cloud-canvas">${renderKeywordTerms(keywordCloud)}</section>
        <aside class="panel detail-card" id="keyword-cloud-detail"><p class="muted">点击词语查看状态、来源用户、社区、父级种子词与代表证据。</p></aside>
      </div>
    </section>

    <section id="pain" class="tab-panel">
      <h2>痛点分布</h2>
      <div class="grid-2">${(analysis.pain_points ?? []).length ? analysis.pain_points.map((item) => renderPainCard(item, evidenceById)).join('') : '<div class="empty">当前没有痛点记录。</div>'}</div>
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
      <div class="stack">${adjacentOpportunities.length ? adjacentOpportunities.map((item) => renderOpportunityCard(item, evidenceById, { attributeName: 'data-adjacent-type' })).join('') : '<div class="empty">当前没有邻近配套机会。</div>'}</div>
    </section>

    <section id="personas" class="tab-panel">
      <h2>用户画像</h2>
      ${renderPersonaPanel(analysis.personas)}
    </section>

    <section id="evidence" class="tab-panel">
      <h2>合格证据库与排除项</h2>
      <div class="panel" style="margin-bottom:16px">
        <div class="evidence-tools">
          <input id="evidence-search" placeholder="搜索社区或英文原文">
        </div>
        <p><strong>合格证据：</strong>${escapeHtml(qualifiedEvidence.length)} · <strong>排除项：</strong>${escapeHtml(excludedEvidence.length)}</p>
      </div>
      <div id="evidence-list" class="evidence-list">${evidenceCards || '<div class="empty">暂无证据。</div>'}</div>
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
      if (button.dataset.tab === 'map') renderMap();
    }));

    const mapSvg = document.getElementById('audience-map');
    const mapDetail = document.getElementById('map-detail');
    const mapSearch = document.getElementById('map-search');
    const mapFilterRoot = document.getElementById('category-filters');
    const mapNs = 'http://www.w3.org/2000/svg';
    let activeMapCategory = 'all';
    const productNodes = (audienceMap.nodes || []).filter(node => node.type === 'product');
    const communityNodes = (audienceMap.nodes || []).filter(node => node.type === 'community');
    const positions = new Map();
    const placeNodes = (nodes, x) => nodes.forEach((node, index) => positions.set(node.id, { x, y: 70 + (index + 1) * (560 / (nodes.length + 1 || 1)) }));
    placeNodes(productNodes, 285);
    placeNodes(communityNodes, 735);

    function renderMapDetail(nodeId) {
      const node = (audienceMap.nodes || []).find(item => item.id === nodeId);
      if (!node) {
        mapDetail.innerHTML = '<p class="muted">点击产品或社区查看机会、痛点和证据。</p>';
        return;
      }
      const linkedEdges = (audienceMap.edges || []).filter(edge => edge.source === nodeId || edge.target === nodeId);
      const linkedIds = linkedEdges.map(edge => edge.source === nodeId ? edge.target : edge.source);
      const linkedNodes = (audienceMap.nodes || []).filter(item => linkedIds.includes(item.id));
      const evidenceItems = unique(linkedEdges.flatMap(edge => edge.evidence_ids || []).map(id => evidenceById.get(id)).filter(Boolean));
      if (node.type === 'product') {
        const productEyebrow = node.entry_type === 'adjacent_bundle' ? '邻近配套' : '正式机会';
        mapDetail.innerHTML = '<p class="eyebrow">' + productEyebrow + '</p><h3>' + escapeHtml(node.label) + '</h3><p>分数 ' + escapeHtml(node.opportunity_score ?? node.size ?? 0) + '</p><h4>痛点</h4><ul>' + (node.pain_points || []).map(item => '<li>' + escapeHtml(item) + '</li>').join('') + '</ul><h4>社区</h4><p>' + linkedNodes.map(item => escapeHtml(item.label)).join(' · ') + '</p><h4>代表证据</h4><ul>' + (evidenceItems.length ? evidenceItems.map(item => '<li><a href="' + escapeHtml(item.url) + '" target="_blank" rel="noreferrer">' + escapeHtml(item.subreddit) + ' · ' + escapeHtml((item.quote_original || '').slice(0, 100)) + '</a></li>').join('') : '<li>暂无可点击证据</li>') + '</ul>';
      } else {
        const formalLinked = linkedNodes.filter(item => item.entry_type === 'formal_opportunity');
        const adjacentLinked = linkedNodes.filter(item => item.entry_type === 'adjacent_bundle');
        mapDetail.innerHTML = '<p class="eyebrow">社区来源</p><h3>' + escapeHtml(node.label) + '</h3><p>正式机会 ' + escapeHtml(node.formal_product_count ?? formalLinked.length) + ' 个 · 邻近配套 ' + escapeHtml(node.adjacent_product_count ?? adjacentLinked.length) + ' 个。</p><h4>正式机会</h4><ul>' + (formalLinked.length ? formalLinked.map(item => '<li>' + escapeHtml(item.label) + '</li>').join('') : '<li>暂无</li>') + '</ul><h4>邻近配套</h4><ul>' + (adjacentLinked.length ? adjacentLinked.map(item => '<li>' + escapeHtml(item.label) + '</li>').join('') : '<li>暂无</li>') + '</ul><h4>代表证据</h4><ul>' + (evidenceItems.length ? evidenceItems.map(item => '<li><a href="' + escapeHtml(item.url) + '" target="_blank" rel="noreferrer">' + escapeHtml((item.quote_original || '').slice(0, 100)) + '</a></li>').join('') : '<li>暂无可点击证据</li>') + '</ul>';
      }
    }

    function visibleMapNode(node) {
      const query = mapSearch.value.trim().toLowerCase();
      const text = [node.label, node.subreddit, node.category, ...(node.fitment_tags || [])].join(' ').toLowerCase();
      const categoryOk = activeMapCategory === 'all' || node.type === 'community' || node.category === activeMapCategory;
      return categoryOk && (!query || text.includes(query));
    }

    function applyMapFilter() {
      const visibleIds = new Set((audienceMap.nodes || []).filter(visibleMapNode).map(item => item.id));
      document.querySelectorAll('.graph-node').forEach(node => node.classList.toggle('dim', !visibleIds.has(node.dataset.id)));
      document.querySelectorAll('.graph-edge').forEach(edge => edge.classList.toggle('dim', !visibleIds.has(edge.dataset.source) || !visibleIds.has(edge.dataset.target)));
    }

    function renderMap() {
      mapSvg.replaceChildren();
      if (!(audienceMap.nodes || []).length) {
        const empty = document.createElementNS(mapNs, 'text');
        empty.setAttribute('x', '500');
        empty.setAttribute('y', '350');
        empty.setAttribute('text-anchor', 'middle');
        empty.setAttribute('fill', '#67746c');
        empty.setAttribute('font-size', '18');
        empty.textContent = '暂无机会或社区数据，无法绘制 Audience Map。';
        mapSvg.appendChild(empty);
        return;
      }
      (audienceMap.edges || []).forEach(edge => {
        const source = positions.get(edge.source);
        const target = positions.get(edge.target);
        if (!source || !target) return;
        const line = document.createElementNS(mapNs, 'line');
        line.setAttribute('x1', source.x);
        line.setAttribute('y1', source.y);
        line.setAttribute('x2', target.x);
        line.setAttribute('y2', target.y);
        line.setAttribute('class', 'graph-edge');
        line.dataset.source = edge.source;
        line.dataset.target = edge.target;
        mapSvg.appendChild(line);
      });
      (audienceMap.nodes || []).forEach(node => {
        const point = positions.get(node.id);
        if (!point) return;
        const group = document.createElementNS(mapNs, 'g');
        group.setAttribute('class', 'graph-node ' + node.type);
        group.setAttribute('transform', 'translate(' + point.x + ' ' + point.y + ')');
        group.dataset.id = node.id;
        const circle = document.createElementNS(mapNs, 'circle');
        const radius = node.type === 'product' ? 10 + Math.min(22, (Number(node.opportunity_score ?? node.size ?? 0)) / 4) : 10 + Math.min(16, Number(node.product_count ?? node.size ?? 1) * 4);
        circle.setAttribute('r', radius);
        group.appendChild(circle);
        const label = document.createElementNS(mapNs, 'text');
        label.setAttribute('x', node.type === 'product' ? -radius - 8 : radius + 8);
        label.setAttribute('y', '4');
        label.setAttribute('text-anchor', node.type === 'product' ? 'end' : 'start');
        label.textContent = node.label;
        group.appendChild(label);
        group.addEventListener('click', () => {
          document.querySelectorAll('.graph-node').forEach(item => item.classList.toggle('selected', item === group));
          renderMapDetail(node.id);
        });
        mapSvg.appendChild(group);
      });
      applyMapFilter();
    }

    const mapCategories = ['all', ...new Set(audienceMap.filters?.categories || [])];
    mapCategories.forEach((category, index) => {
      const button = document.createElement('button');
      button.className = 'filter-btn' + (index === 0 ? ' active' : '');
      button.textContent = category === 'all' ? '全部' : category;
      button.addEventListener('click', () => {
        activeMapCategory = category;
        mapFilterRoot.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button));
        applyMapFilter();
      });
      mapFilterRoot.appendChild(button);
    });
    mapSearch.addEventListener('input', applyMapFilter);
    document.getElementById('reset-map').addEventListener('click', () => {
      activeMapCategory = 'all';
      mapSearch.value = '';
      mapFilterRoot.querySelectorAll('button').forEach((button, index) => button.classList.toggle('active', index === 0));
      renderMapDetail(null);
      applyMapFilter();
    });
    renderMap();

    const cloudCanvas = document.getElementById('keyword-cloud-canvas');
    const cloudDetail = document.getElementById('keyword-cloud-detail');
    const cloudSearch = document.getElementById('keyword-cloud-search');
    const cloudScore = document.getElementById('keyword-cloud-score');
    const cloudCategoryRoot = document.getElementById('keyword-cloud-categories');
    const cloudStatusRoot = document.getElementById('keyword-cloud-statuses');
    let activeCloudCategory = 'all';
    let activeCloudStatus = 'all';

    function showCloudDetail(termId) {
      const term = (keywordCloud.terms || []).find(item => slug(item.term) === termId);
      if (!term) {
        cloudDetail.innerHTML = '<p class="muted">点击词语查看状态、来源用户、社区、父级种子词与代表证据。</p>';
        return;
      }
      const evidenceItems = (term.representative_evidence || []).map(item => '<li><a href="' + escapeHtml(item.url) + '" target="_blank" rel="noreferrer">' + escapeHtml(item.subreddit) + ' · ' + escapeHtml((item.quote_original || '').slice(0, 100)) + '</a></li>').join('');
      cloudDetail.innerHTML = '<p class="eyebrow">关键词详情</p><h3>' + escapeHtml(term.term) + '</h3><p><strong>状态：</strong>' + escapeHtml(term.status) + '</p><p><strong>类别：</strong>' + escapeHtml((term.categories || [term.category]).join(' · ')) + '</p><p><strong>分数：</strong>' + escapeHtml(term.discovery_score ?? 0) + ' · <strong>展示权重：</strong>' + escapeHtml(term.display_weight ?? 0) + '</p><p><strong>来源用户：</strong>' + escapeHtml(term.unique_user_count ?? 0) + ' · <strong>社区：</strong>' + escapeHtml((term.communities || []).join(' · ') || '未知') + '</p><h4>父级种子词</h4><ul>' + (term.parent_formal_terms || []).map(item => '<li>' + escapeHtml(item) + '</li>').join('') + '</ul><h4>相关产品</h4><ul>' + (term.related_product_ids || []).map(item => '<li>' + escapeHtml(item) + '</li>').join('') + '</ul><h4>代表证据</h4><ul>' + (evidenceItems || '<li>暂无可点击证据</li>') + '</ul>';
    }

    function applyCloudFilter() {
      const query = cloudSearch.value.trim().toLowerCase();
      const minimumScore = Number(cloudScore.value || 0);
      cloudCanvas.querySelectorAll('.cloud-term').forEach(node => {
        const categoryOk = activeCloudCategory === 'all' || node.dataset.category === activeCloudCategory;
        const statusOk = activeCloudStatus === 'all' || node.dataset.status === activeCloudStatus;
        const queryOk = !query || node.dataset.label.includes(query);
        const scoreOk = Number(node.dataset.score || 0) >= minimumScore;
        node.classList.toggle('hidden', !(categoryOk && statusOk && queryOk && scoreOk));
      });
    }

    function renderCloudFilterGroup(root, values, labelPrefix, handler) {
      ['all', ...new Set(values || [])].forEach((value, index) => {
        const button = document.createElement('button');
        button.className = 'filter-btn' + (index === 0 ? ' active' : '');
        button.textContent = value === 'all' ? '全部' : labelPrefix ? labelPrefix + value : value;
        button.addEventListener('click', () => {
          root.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button));
          handler(value);
          applyCloudFilter();
        });
        root.appendChild(button);
      });
    }

    renderCloudFilterGroup(cloudCategoryRoot, keywordCloud.filters?.categories || [], '', value => { activeCloudCategory = value; });
    renderCloudFilterGroup(cloudStatusRoot, keywordCloud.filters?.statuses || [], '', value => { activeCloudStatus = value; });
    cloudSearch.addEventListener('input', applyCloudFilter);
    cloudScore.addEventListener('input', applyCloudFilter);
    cloudCanvas.querySelectorAll('.cloud-term').forEach(button => button.addEventListener('click', () => showCloudDetail(button.dataset.termId)));
    document.getElementById('keyword-cloud-reset').addEventListener('click', () => {
      activeCloudCategory = 'all';
      activeCloudStatus = 'all';
      cloudSearch.value = '';
      cloudScore.value = '0';
      cloudCategoryRoot.querySelectorAll('button').forEach((button, index) => button.classList.toggle('active', index === 0));
      cloudStatusRoot.querySelectorAll('button').forEach((button, index) => button.classList.toggle('active', index === 0));
      showCloudDetail(null);
      applyCloudFilter();
    });
    applyCloudFilter();

    document.getElementById('evidence-search').addEventListener('input', event => {
      const query = event.target.value.trim().toLowerCase();
      document.querySelectorAll('.evidence-card').forEach(card => {
        card.hidden = Boolean(query) && !card.dataset.search.includes(query);
      });
    });

    function unique(values) {
      return [...new Set(values)];
    }

    function slug(value) {
      return String(value || 'item').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'item';
    }

    const initialTab = location.hash.replace(/^#/, '');
    if (initialTab) {
      const initialButton = document.querySelector('.tabs button[data-tab="' + initialTab + '"]');
      if (initialButton) initialButton.click();
    }
  </script>
</body>
</html>`;
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
      ...formalOpportunities.filter((opportunity) => opportunity.pain_points.includes(label)).map((opportunity) => opportunity.id),
    ]);
    const relatedSolutionIds = uniqueStrings([
      ...(item.related_solution_ids ?? []),
      ...formalOpportunities.filter((opportunity) => opportunity.pain_points.includes(label)).map((opportunity) => opportunity.id),
      ...candidateSignals.filter((signal) => (analysis.candidate_signals ?? []).find((raw) => raw.id === signal.id)?.pain_points?.includes?.(label)).map((signal) => signal.id),
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
