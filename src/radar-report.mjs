import fs from 'node:fs/promises';
import path from 'node:path';

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

function list(items, empty = '暂无') {
  if (!items?.length) return `<p class="muted">${empty}</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
}

function statusField(label, value) {
  const status = value?.status ?? 'unknown';
  const display = value?.value ?? '未知';
  return `<div class="commercial-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(display)}</strong><em class="status ${escapeHtml(status)}">${escapeHtml(status)}</em></div>`;
}

export function renderReportHtml({ analysis, audienceMap, manifest = {} }) {
  const opportunities = analysis.opportunities ?? [];
  const evidence = analysis.evidence ?? [];
  const failures = analysis.collection_failures ?? [];
  const keywords = analysis.research_keywords ?? {};
  const opportunityCards = opportunities.length
    ? opportunities.map((item) => `
      <article class="opportunity-card" data-category="${escapeHtml(item.category)}">
        <div class="score-ring">${escapeHtml(item.opportunity_score)}</div>
        <div class="opportunity-main">
          <p class="eyebrow">${escapeHtml(item.category)} · ${escapeHtml(item.verdict)}</p>
          <h3>${escapeHtml(item.label)}</h3>
          <div class="chips">${(item.fitment_tags ?? []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join('')}</div>
          <h4>主要痛点</h4>${list(item.pain_points)}
          <h4>可验证的解决方向</h4>${list(item.solution_ideas)}
          <h4>为什么还没有被很好解决</h4><p><span class="status inference">${escapeHtml(item.why_not_done?.status)}</span> ${escapeHtml(item.why_not_done?.text)}</p>
          <div class="commercial-grid">
            ${statusField('价格带', item.commercial?.pricing_band)}
            ${statusField('制造复杂度', item.commercial?.manufacturing_complexity)}
            ${statusField('运输复杂度', item.commercial?.shipping_complexity)}
            ${statusField('退货风险', item.commercial?.return_risk)}
          </div>
          <details><summary>事实 / 推断 / 未知边界</summary>
            <div class="claims"><section><h5>事实</h5>${list(item.claims?.facts)}</section><section><h5>推断</h5>${list(item.claims?.inferences)}</section><section><h5>未知</h5>${list(item.claims?.unknowns)}</section></div>
          </details>
        </div>
      </article>`).join('')
    : '<div class="empty">当前样本尚未形成有美国证据信号的产品机会。</div>';

  const evidenceCards = evidence.map((item) => `
    <article class="evidence-card" data-search="${escapeHtml(`${item.subreddit} ${item.quote_original}`.toLowerCase())}">
      <div class="evidence-meta"><span>r/${escapeHtml(item.subreddit)}</span><span>score ${escapeHtml(item.score ?? 0)}</span><span class="status fact">${escapeHtml(item.geography)}</span></div>
      <blockquote lang="en">${escapeHtml(item.quote_original)}</blockquote>
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">查看 Reddit 原文 ↗</a>
    </article>`).join('');

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>美国车灯 Reddit 产品机会雷达 · ${escapeHtml(analysis.run_id)}</title>
  <style>
    :root{--ink:#17211b;--muted:#647067;--paper:#f5f2e9;--panel:#fffdf8;--line:#d8d4c8;--green:#0e7c62;--amber:#d79519;--red:#b24a3b;--blue:#365d87;--shadow:0 12px 36px rgba(33,46,37,.08)}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 Inter,"Segoe UI","Microsoft YaHei",sans-serif}button,input{font:inherit}a{color:var(--green)}
    header{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;padding:14px 4vw;background:rgba(245,242,233,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}
    .brand{font-weight:800;letter-spacing:-.02em}.brand b{color:var(--amber)}.tabs{display:flex;gap:6px}.tabs button,.filter-btn{border:1px solid var(--line);background:transparent;border-radius:999px;padding:7px 13px;cursor:pointer}.tabs button.active,.filter-btn.active{background:var(--ink);color:white;border-color:var(--ink)}
    main{max-width:1440px;margin:auto;padding:30px 4vw 70px}.tab-panel{display:none}.tab-panel.active{display:block}.hero{display:grid;grid-template-columns:1.35fr .65fr;gap:24px;align-items:stretch}.hero-main,.hero-side,.panel,.opportunity-card,.evidence-card{background:var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow)}
    .hero-main{padding:38px}.hero-main h1{font-size:clamp(30px,5vw,64px);line-height:1.05;letter-spacing:-.05em;margin:8px 0 20px;max-width:900px}.hero-side{padding:24px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.14em;color:var(--green);font-weight:800}.verdict{font-size:18px;border-left:4px solid var(--amber);padding-left:16px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:22px 0}.stat{padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:14px}.stat strong{display:block;font-size:28px}.stat span{color:var(--muted)}
    h2{font-size:30px;letter-spacing:-.03em;margin-top:44px}.opportunities{display:grid;gap:16px}.opportunity-card{display:grid;grid-template-columns:90px 1fr;padding:22px}.score-ring{width:70px;height:70px;border:7px solid var(--green);border-radius:50%;display:grid;place-items:center;font-size:24px;font-weight:800}.opportunity-main h3{font-size:25px;margin:0 0 8px}.opportunity-main h4{margin:18px 0 4px}.chips{display:flex;gap:6px;flex-wrap:wrap}.chips span{background:#e9efe9;border-radius:999px;padding:3px 9px;font-size:12px}.commercial-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:18px 0}.commercial-item{border:1px solid var(--line);padding:10px;border-radius:10px}.commercial-item span,.commercial-item strong{display:block}.commercial-item span{color:var(--muted);font-size:12px}.status{display:inline-block;font-style:normal;font-size:11px;padding:2px 7px;border-radius:999px;background:#eceae2}.status.fact{background:#d9efe7;color:#075b46}.status.inference{background:#fff0c9;color:#7c5300}.status.unknown{background:#eee;color:#555}.status.failed{background:#f4d7d3;color:#842d22}.claims{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.claims section{background:#f7f5ef;padding:12px;border-radius:10px}.claims h5{margin:0}
    .map-layout{display:grid;grid-template-columns:270px minmax(500px,1fr) 320px;min-height:680px;border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--panel);box-shadow:var(--shadow)}.map-sidebar,.map-detail{padding:20px;background:#faf8f1}.map-sidebar{border-right:1px solid var(--line)}.map-detail{border-left:1px solid var(--line)}.map-canvas{position:relative;overflow:auto;background-image:radial-gradient(#d8d4c8 1px,transparent 1px);background-size:24px 24px}.map-canvas svg{width:100%;height:680px;min-width:720px}.map-controls input,.evidence-search{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:white}.filters{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.filter-btn{font-size:12px;padding:5px 9px}.legend{margin-top:24px;color:var(--muted);font-size:13px}.legend i{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px}.legend .solid{background:var(--green)}.legend .hollow{background:white;border:2px solid #6c746e}.graph-node{cursor:pointer}.graph-node text{font-size:11px;pointer-events:none;fill:var(--ink)}.graph-node.product circle{fill:var(--green);stroke:white;stroke-width:2}.graph-node.community circle{fill:var(--panel);stroke:#59625b;stroke-width:2}.graph-edge{stroke:#b9bdb7;stroke-width:1;opacity:.65}.graph-node.dim,.graph-edge.dim{opacity:.08}.graph-node.selected circle{stroke:var(--amber);stroke-width:5}.detail-empty{color:var(--muted);margin-top:40%}.detail-list{padding-left:18px}.detail-score{font-size:34px;font-weight:800;color:var(--green)}
    .evidence-tools{display:flex;gap:12px;margin-bottom:16px}.evidence-list{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.evidence-card{padding:18px}.evidence-meta{display:flex;gap:8px;color:var(--muted);font-size:12px}.evidence-card blockquote{margin:12px 0;font-family:Georgia,serif;font-size:17px}.empty{padding:30px;border:1px dashed var(--line);border-radius:14px;color:var(--muted)}footer{margin-top:50px;color:var(--muted);font-size:12px}
    @media(max-width:1000px){.hero{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.map-layout{grid-template-columns:1fr}.map-sidebar,.map-detail{border:0;border-bottom:1px solid var(--line)}.commercial-grid,.claims{grid-template-columns:1fr 1fr}.evidence-list{grid-template-columns:1fr}}@media(max-width:650px){header{align-items:flex-start;gap:10px;flex-direction:column}.opportunity-card{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.commercial-grid,.claims{grid-template-columns:1fr}.hero-main{padding:24px}}
  </style>
</head>
<body>
  <header><div class="brand">🐴 Opportunity Radar <b>· US Lighting</b></div><nav class="tabs"><button class="active" data-tab="overview">卖家报告</button><button data-tab="map">Audience Map</button><button data-tab="evidence">证据库</button></nav></header>
  <main>
    <section id="overview" class="tab-panel active">
      <div class="hero"><div class="hero-main"><p class="eyebrow">US automotive lighting · Reddit evidence</p><h1>从真实抱怨里找下一款车灯产品</h1><p>${escapeHtml(analysis.executive_summary)}</p><p class="verdict"><strong>Seller Verdict：</strong>${escapeHtml(analysis.seller_verdict)}</p></div>
      <aside class="hero-side"><p class="eyebrow">研究边界</p><h3>仅美国 · 不做季节性</h3><p>无法确认地域的证据保留在证据库，但不进入美国市场结论。</p><p><strong>分析引擎：</strong>${escapeHtml(analysis.analysis_engine?.active_result)}</p><p><strong>运行状态：</strong>${escapeHtml(manifest.status ?? 'unknown')}</p><p><strong>隐私：</strong>${escapeHtml(analysis.privacy_note)}</p></aside></div>
      <div class="stats"><div class="stat"><strong>${escapeHtml(analysis.metrics?.posts_analyzed ?? 0)}</strong><span>帖子</span></div><div class="stat"><strong>${escapeHtml(analysis.metrics?.comments_analyzed ?? 0)}</strong><span>评论</span></div><div class="stat"><strong>${escapeHtml(analysis.metrics?.us_posts ?? 0)}</strong><span>美国证据帖子</span></div><div class="stat"><strong>${escapeHtml(analysis.metrics?.communities ?? 0)}</strong><span>美国社区</span></div><div class="stat"><strong>${escapeHtml(manifest.counts?.failures ?? 0)}</strong><span>采集失败</span></div></div>
      <h2>产品机会与优化方向</h2><div class="opportunities">${opportunityCards}</div>
      <section class="panel" style="padding:22px;margin-top:22px"><h2 style="margin-top:0">研究范围、关键词与失败记录</h2>
        <p><strong>锚点词：</strong>${escapeHtml((keywords.anchors ?? []).join(' · ') || '未知')}</p>
        <p><strong>受控扩展：</strong>${escapeHtml((keywords.expanded ?? []).join(' · ') || '未知')}</p>
        <p><strong>失败条目：</strong>${failures.length ? failures.map((item) => `${escapeHtml(item.stage)} · ${escapeHtml(item.query ?? item.post_id ?? '')} · ${escapeHtml(item.error)}`).join('<br>') : '无'}</p>
      </section>
    </section>
    <section id="map" class="tab-panel">
      <div class="map-layout">
        <aside class="map-sidebar"><p class="eyebrow">Audience Map · 二部图</p><p>实心圆是产品/解决方案，空心圈是 Reddit 社区。点击节点查看证据关系。</p><div class="map-controls"><input id="map-search" placeholder="搜索产品、fitment 或社区"><div id="category-filters" class="filters"></div><button id="reset-map" class="filter-btn">← 回到全局图</button></div><div class="legend"><p><i class="solid"></i>实心圆：产品，大小=机会分</p><p><i class="hollow"></i>空心圈：社区，大小=关联产品数</p></div></aside>
        <div class="map-canvas"><svg id="audience-map" viewBox="0 0 1000 680" role="img" aria-label="产品与 Reddit 社区二部图"></svg></div>
        <aside id="map-detail" class="map-detail"><p class="detail-empty">点击产品或社区查看痛点、机会与证据。</p></aside>
      </div>
    </section>
    <section id="evidence" class="tab-panel"><h2>英文原文证据</h2><div class="evidence-tools"><input id="evidence-search" class="evidence-search" placeholder="搜索社区或原文"></div><div id="evidence-list" class="evidence-list">${evidenceCards}</div></section>
    <footer>Run ${escapeHtml(analysis.run_id)} · Generated ${escapeHtml(analysis.generated_at)} · JSON is the single source of truth.</footer>
  </main>
  <script id="analysis-data" type="application/json">${safeJson(analysis)}</script>
  <script id="audience-map-data" type="application/json">${safeJson(audienceMap)}</script>
  <script id="manifest-data" type="application/json">${safeJson(manifest)}</script>
  <script>
    const analysis = JSON.parse(document.getElementById('analysis-data').textContent);
    const graph = JSON.parse(document.getElementById('audience-map-data').textContent);
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    document.querySelectorAll('.tabs button').forEach(button => button.addEventListener('click', () => {
      document.querySelectorAll('.tabs button').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.id === button.dataset.tab));
      if (button.dataset.tab === 'map') renderGraph();
    }));
    const svg = document.getElementById('audience-map');
    const detail = document.getElementById('map-detail');
    const search = document.getElementById('map-search');
    let activeCategory = 'all';
    let selectedId = null;
    const ns = 'http://www.w3.org/2000/svg';
    const productNodes = graph.nodes.filter(node => node.type === 'product');
    const communityNodes = graph.nodes.filter(node => node.type === 'community');
    const position = new Map();
    const place = (nodes, x) => nodes.forEach((node, index) => position.set(node.id, {x, y: 70 + (index + 1) * (540 / (nodes.length + 1))}));
    place(productNodes, 285); place(communityNodes, 735);
    function visibleNode(node) {
      const query = search.value.trim().toLowerCase();
      const categoryOk = activeCategory === 'all' || node.type === 'community' || node.category === activeCategory;
      const text = [node.label,node.subreddit,node.category,...(node.fitment_tags||[])].join(' ').toLowerCase();
      return categoryOk && (!query || text.includes(query));
    }
    function renderGraph() {
      svg.replaceChildren();
      graph.edges.forEach(edge => {
        const source = position.get(edge.source), target = position.get(edge.target);
        if (!source || !target) return;
        const line = document.createElementNS(ns,'line'); line.setAttribute('x1',source.x); line.setAttribute('y1',source.y); line.setAttribute('x2',target.x); line.setAttribute('y2',target.y); line.setAttribute('class','graph-edge'); line.dataset.source=edge.source; line.dataset.target=edge.target; svg.appendChild(line);
      });
      graph.nodes.forEach(node => {
        const point = position.get(node.id); if (!point) return;
        const group = document.createElementNS(ns,'g'); group.setAttribute('class','graph-node '+node.type); group.setAttribute('transform','translate('+point.x+' '+point.y+')'); group.dataset.id=node.id;
        const circle = document.createElementNS(ns,'circle'); const radius=node.type==='product'?10+Math.min(22,(node.opportunity_score||0)/4):9+Math.min(16,(node.product_count||1)*4); circle.setAttribute('r',radius); group.appendChild(circle);
        const label = document.createElementNS(ns,'text'); label.setAttribute('x',node.type==='product'?-radius-8:radius+8); label.setAttribute('y','4'); label.setAttribute('text-anchor',node.type==='product'?'end':'start'); label.textContent=node.label; group.appendChild(label);
        group.addEventListener('click',()=>selectNode(node.id)); svg.appendChild(group);
      });
      applyGraphFilter();
    }
    function applyGraphFilter() {
      const visible = new Set(graph.nodes.filter(visibleNode).map(node=>node.id));
      document.querySelectorAll('.graph-node').forEach(el=>el.classList.toggle('dim',!visible.has(el.dataset.id)));
      document.querySelectorAll('.graph-edge').forEach(el=>el.classList.toggle('dim',!visible.has(el.dataset.source)||!visible.has(el.dataset.target)));
    }
    function selectNode(id) {
      selectedId=id; document.querySelectorAll('.graph-node').forEach(el=>el.classList.toggle('selected',el.dataset.id===id));
      const node=graph.nodes.find(item=>item.id===id); if(!node)return;
      const linked=graph.edges.filter(edge=>edge.source===id||edge.target===id); const linkedIds=linked.map(edge=>edge.source===id?edge.target:edge.source); const linkedNodes=graph.nodes.filter(item=>linkedIds.includes(item.id));
      if(node.type==='product'){
        const opportunity=analysis.opportunities.find(item=>item.id===id)||node;
        const evidenceLinks=(opportunity.evidence_ids||[]).map(eid=>analysis.evidence.find(item=>item.id===eid)).filter(Boolean).map(item=>'<li><a href="'+escapeHtml(item.url)+'" target="_blank" rel="noreferrer">'+escapeHtml(item.subreddit)+' · '+escapeHtml(item.quote_original.slice(0,120))+'</a></li>').join('');
        detail.innerHTML='<p class="eyebrow">产品 / 解决方案</p><div class="detail-score">'+escapeHtml(opportunity.opportunity_score)+'</div><h3>'+escapeHtml(opportunity.label)+'</h3><p>'+escapeHtml(opportunity.verdict)+'</p><h4>痛点</h4><ul class="detail-list">'+(opportunity.pain_points||[]).map(item=>'<li>'+escapeHtml(item)+'</li>').join('')+'</ul><h4>解决方向</h4><ul class="detail-list">'+(opportunity.solution_ideas||[]).map(item=>'<li>'+escapeHtml(item)+'</li>').join('')+'</ul><h4>来源社区</h4><p>'+linkedNodes.map(item=>escapeHtml(item.label)).join(' · ')+'</p><h4>Fitment</h4><p>'+escapeHtml((opportunity.fitment_tags||[]).join(' · ')||'未知')+'</p>';
        detail.innerHTML='<p class="eyebrow">产品 / 解决方案</p><div class="detail-score">'+escapeHtml(opportunity.opportunity_score)+'</div><h3>'+escapeHtml(opportunity.label)+'</h3><p>'+escapeHtml(opportunity.verdict)+'</p><h4>痛点</h4><ul class="detail-list">'+(opportunity.pain_points||[]).map(item=>'<li>'+escapeHtml(item)+'</li>').join('')+'</ul><h4>解决方向</h4><ul class="detail-list">'+(opportunity.solution_ideas||[]).map(item=>'<li>'+escapeHtml(item)+'</li>').join('')+'</ul><h4>来源社区</h4><p>'+linkedNodes.map(item=>escapeHtml(item.label)).join(' · ')+'</p><h4>Fitment</h4><p>'+escapeHtml((opportunity.fitment_tags||[]).join(' · ')||'未知')+'</p><h4>价格线索</h4><p>'+escapeHtml(opportunity.commercial?.pricing_band?.value ?? '未知')+'</p><h4>证据</h4><ul class="detail-list">'+(evidenceLinks||'<li>暂无可点击证据</li>')+'</ul>';
      } else {
        const communityEvidence=(node.evidence_ids||[]).map(eid=>analysis.evidence.find(item=>item.id===eid)).filter(Boolean).map(item=>'<li><a href="'+escapeHtml(item.url)+'" target="_blank" rel="noreferrer">'+escapeHtml(item.quote_original.slice(0,120))+'</a></li>').join('');
        detail.innerHTML='<p class="eyebrow">REDDIT 社区 · 人群来源</p><h3>'+escapeHtml(node.label)+'</h3><p>关联 '+linkedNodes.length+' 个产品/解决方案概念。社区节点表示讨论来源，不代表人口统计画像。</p><h4>相邻机会</h4><ul class="detail-list">'+linkedNodes.map(item=>'<li><button class="filter-btn" data-open="'+escapeHtml(item.id)+'">'+escapeHtml(item.label)+'</button></li>').join('')+'</ul><h4>代表证据</h4><ul class="detail-list">'+(communityEvidence||'<li>暂无可点击证据</li>')+'</ul>';
        detail.querySelectorAll('[data-open]').forEach(button=>button.addEventListener('click',()=>selectNode(button.dataset.open)));
      }
    }
    const categories=['all',...(graph.filters?.categories||[])]; const filterRoot=document.getElementById('category-filters'); categories.forEach(category=>{const button=document.createElement('button');button.className='filter-btn'+(category==='all'?' active':'');button.textContent=category==='all'?'全部':category;button.addEventListener('click',()=>{activeCategory=category;filterRoot.querySelectorAll('button').forEach(item=>item.classList.toggle('active',item===button));applyGraphFilter()});filterRoot.appendChild(button)});
    search.addEventListener('input',applyGraphFilter); document.getElementById('reset-map').addEventListener('click',()=>{activeCategory='all';search.value='';selectedId=null;filterRoot.querySelectorAll('button').forEach((item,index)=>item.classList.toggle('active',index===0));detail.innerHTML='<p class="detail-empty">点击产品或社区查看痛点、机会与证据。</p>';renderGraph()});
    document.getElementById('evidence-search').addEventListener('input',event=>{const query=event.target.value.trim().toLowerCase();document.querySelectorAll('.evidence-card').forEach(card=>card.hidden=query&&!card.dataset.search.includes(query))});
    renderGraph();
  </script>
</body>
</html>`;
}

export async function writeReportArtifacts({ runDir, analysis, audienceMap, manifest = {} }) {
  await fs.mkdir(runDir, { recursive: true });
  const paths = {
    analysis: path.join(runDir, 'analysis.json'),
    evidence: path.join(runDir, 'evidence.jsonl'),
    audienceMap: path.join(runDir, 'audience_map.json'),
    html: path.join(runDir, 'report.html'),
  };
  await fs.writeFile(paths.analysis, `${JSON.stringify(analysis, null, 2)}\n`, 'utf8');
  await fs.writeFile(paths.audienceMap, `${JSON.stringify(audienceMap, null, 2)}\n`, 'utf8');
  await fs.writeFile(paths.evidence, analysis.evidence?.length ? `${analysis.evidence.map((item) => JSON.stringify(item)).join('\n')}\n` : '', 'utf8');
  await fs.writeFile(paths.html, renderReportHtml({ analysis, audienceMap, manifest }), 'utf8');
  return paths;
}
