// These functions are also serialized into the offline report. Keep them free
// of imports and captured module state so file:// needs no module loader.
export function selectGraphView(graph, { query = '', category = 'all', focusId = '', mode = 'communities' } = {}) {
  const nodes = graph.nodes ?? [];
  const byId = new Map(nodes.map(node => [node.id, node]));
  const edges = (graph.edges ?? []).filter(edge => byId.get(edge.source)?.type === 'product'
    && byId.get(edge.target)?.type === 'community' && edge.evidence_ids?.length);
  const q = query.trim().toLowerCase();
  const matches = node => [node.label, node.subreddit, node.category, ...(node.fitment_tags ?? [])].join(' ').toLowerCase().includes(q);
  const allowedEdges = edges.filter(edge => {
    const product = byId.get(edge.source);
    return (category === 'all' || product.category === category)
      && (!q || matches(product) || matches(byId.get(edge.target)));
  });
  const relatedIds = new Set(allowedEdges.flatMap(edge => [edge.source, edge.target]));
  const eligibleNodes = nodes.filter(node => relatedIds.has(node.id));
  const focus = eligibleNodes.find(node => node.id === focusId);
  const visibleEdges = focus ? allowedEdges.filter(edge => edge.source === focus.id || edge.target === focus.id) : allowedEdges;
  const visibleIds = new Set(visibleEdges.flatMap(edge => [edge.source, edge.target]));
  return {
    focus: focus ?? null,
    eligibleNodes,
    eligibleEdges: allowedEdges,
    nodes: eligibleNodes.filter(node => visibleIds.has(node.id) && (focus || mode === 'all' || node.type === 'community')),
    edges: focus || mode === 'all' ? visibleEdges : [],
  };
}

export function packCloudWords(terms, { width = 1000, height = 650, cell = 4, scale = 1, makeSprite }) {
  const columns = Math.floor(width / cell);
  const rows = Math.floor(height / cell);
  const occupied = new Uint8Array(columns * rows);
  const placed = [];
  const omitted = [];
  const sorted = terms.map((term, index) => ({ term, index, weight: Math.max(1, Number(term.display_weight ?? term.discovery_score ?? 1)) }))
    .sort((a, b) => b.weight - a.weight || String(a.term.term).localeCompare(String(b.term.term)));
  const maxWeight = Math.max(1, ...sorted.map(item => item.weight));
  for (const { term, index, weight } of sorted) {
    const hash = Array.from(String(term.term)).reduce((value, char) => (value * 31 + char.codePointAt(0)) >>> 0, 17);
    const angle = hash % 5 === 0 ? Math.PI / 2 : hash % 7 === 0 ? -Math.PI / 2 : 0;
    const fontSize = Math.max(9, Math.round((14 + 58 * Math.pow(weight / maxWeight, 1.7)) * scale));
    const sprite = makeSprite(term, fontSize, angle, cell);
    let position = null;
    if (sprite.width <= columns && sprite.height <= rows && sprite.mask.length) {
      for (let step = 0; step < 4200; step++) {
        const theta = step * 0.19;
        const radius = 0.36 * theta;
        const x = Math.round(columns / 2 + Math.cos(theta) * radius * (columns / rows) - sprite.width / 2);
        const y = Math.round(rows / 2 + Math.sin(theta) * radius - sprite.height / 2);
        if (x < 2 || y < 2 || x + sprite.width >= columns - 2 || y + sprite.height >= rows - 2) continue;
        if (sprite.mask.some(([sx, sy]) => occupied[(y + sy) * columns + x + sx])) continue;
        position = { x, y };
        for (const [sx, sy] of sprite.mask) occupied[(y + sy) * columns + x + sx] = 1;
        break;
      }
    }
    if (position) placed.push({ term, index, fontSize, angle, sprite, x: position.x * cell, y: position.y * cell });
    else omitted.push(term);
  }
  return { placed, omitted, width, height, cell };
}

export const REPORT_VISUAL_STYLES = `
body.explorer-active main{max-width:none;padding:20px 24px 50px}
.visual-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin:0 0 18px}.visual-heading h2{margin:0;font-size:32px}.visual-heading p{margin:3px 0 0;font-size:13px;color:var(--muted)}.visual-heading .eyebrow{font-size:10px}
.map-layout,.keyword-layout{position:relative;display:grid;grid-template-columns:240px minmax(0,1fr);gap:0;height:max(680px,calc(100vh - 220px));min-height:680px;border:1px solid var(--line);border-radius:18px;overflow:hidden;background:#f8f6f1;box-shadow:var(--shadow)}
.map-sidebar,.cloud-sidebar{padding:20px 18px;overflow:auto;background:#f4f1eb;border-right:1px solid var(--line)}.map-sidebar p,.cloud-sidebar p{font-size:12px;color:var(--muted)}
.map-controls input,.cloud-sidebar input[type=search]{width:100%;padding:10px 11px;border:1px solid var(--line);border-radius:7px;background:#fffdf9}.cloud-sidebar input[type=range]{width:100%;accent-color:#0d7c61}.cloud-sidebar label{font-size:12px;color:var(--muted)}
.visual-section-title{margin:20px 0 8px;border-top:1px solid var(--line);padding-top:15px;color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase}
.visual-row{display:flex;align-items:center;gap:9px;width:100%;padding:9px 7px;border:0;border-radius:7px;background:transparent;color:var(--ink);text-align:left;cursor:pointer}.visual-row:hover,.visual-row.active{background:#e6e0d6}.visual-row span{min-width:0}.visual-row strong{display:block;font-size:12px;font-weight:600;overflow-wrap:anywhere}.visual-row small{display:block;font-size:10px;color:var(--muted)}
.visual-dot{display:inline-block;width:11px;height:11px;border-radius:50%;flex:none;background:#c88742}.visual-dot.community{background:transparent;border:1.5px solid #8b8479}.visual-legend{display:flex;align-items:center;gap:7px;margin:7px 0;font-size:11px;color:var(--muted)}
.map-sidebar .filters,.cloud-sidebar .filters{gap:5px}.map-sidebar .filter-btn,.cloud-sidebar .filter-btn{padding:5px 9px;font-size:11px;border-radius:6px}.visual-reset{width:100%;margin:8px 0 0;padding:8px 10px;border:0;border-radius:6px;background:#e5dfd5;color:#625a4e;cursor:pointer;text-align:left}
.map-canvas{position:relative;background:#f8f6f1;overflow:hidden;min-width:0}.map-canvas svg{display:block;width:100%;height:100%;min-width:0}.map-toolbar{position:absolute;top:16px;left:18px;right:18px;display:flex;justify-content:space-between;align-items:center;gap:10px;z-index:2;pointer-events:none}.map-toolbar button{pointer-events:auto}.visual-metric{font:11px ui-monospace,monospace;color:var(--muted);background:#f8f6f1e8;padding:6px 10px;border-radius:8px}.map-help{position:absolute;bottom:17px;left:20px;right:20px;text-align:center;font-size:11px;color:var(--muted);pointer-events:none}
.graph-edge{stroke:#beb6a9;stroke-width:1.4;opacity:.65}.graph-node{outline:none}.graph-node text{font-size:12px;text-anchor:middle;fill:#373129}.graph-node .node-meta{font-size:10px;fill:#8a8174}.graph-node.product circle{fill:#c88742;stroke:#f8f6f1;stroke-width:3}.graph-node.community circle{fill:#f8f6f1;stroke:#8b8479;stroke-width:1.7}.graph-node.selected circle,.graph-node:focus circle,.graph-node:hover circle{stroke:#2d332e;stroke-width:3}.graph-node.product[data-entry=adjacent_bundle] circle{fill:#557c77}
.visual-drawer{position:absolute;right:0;top:0;bottom:0;z-index:5;width:min(385px,calc(100% - 16px));padding:28px 24px;background:#fffdf9;border-left:1px solid var(--line);box-shadow:-12px 0 35px #40372216;overflow:auto}.visual-drawer[hidden]{display:none}.visual-close{position:absolute;right:12px;top:10px;border:0;background:#eee9df;color:#61594d;width:29px;height:29px;border-radius:50%;font-size:21px;cursor:pointer}.visual-drawer h3{font-size:23px;line-height:1.25;overflow-wrap:anywhere;margin:8px 20px 18px 0}.visual-drawer h4{font-size:12px;color:#837047;border-top:1px solid var(--line);padding-top:15px;margin-top:20px}.visual-drawer ul{padding-left:18px;font-size:12px}.visual-drawer p{font-size:13px}.visual-drawer .score-value{font:700 36px ui-monospace,monospace;color:#a5662c}.visual-drawer .score-value small{font-size:13px;color:var(--muted)}.visual-evidence{border-bottom:1px dashed var(--line);padding:12px 0;font-size:12px}.visual-evidence blockquote{margin:7px 0;font:14px/1.55 Georgia,serif;overflow-wrap:anywhere}.visual-evidence a{font-size:11px}.visual-drawer .chips span{font-size:10px}.visual-empty{padding:18px 5px;color:var(--muted);font-size:12px}
.cloud-stage{position:relative;min-width:0;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#fffdf9;padding:42px 12px 35px}.cloud-stage canvas{display:block;width:100%;height:auto;max-height:100%;aspect-ratio:1000/650;object-fit:contain;cursor:default}.cloud-stage .visual-metric{position:absolute;left:18px;top:14px;background:#fffdf9}.cloud-caption{position:absolute;left:20px;right:20px;bottom:13px;text-align:center;font-size:11px;color:var(--muted)}.cloud-tooltip{position:fixed;z-index:60;max-width:280px;padding:8px 12px;border-radius:7px;background:#263c32;color:#fff;box-shadow:0 5px 18px #0002;pointer-events:none;font-size:12px;white-space:pre-line}.cloud-tooltip[hidden]{display:none}.cloud-list{margin-top:15px;font-size:12px}.cloud-list summary{cursor:pointer;color:var(--muted)}.cloud-list button{border:0;border-radius:4px;background:transparent;display:block;width:100%;text-align:left;cursor:pointer;padding:6px;color:var(--ink);overflow-wrap:anywhere}.cloud-list button:hover,.cloud-list button:focus{background:#e6e0d6}
@media(max-width:1100px){.map-layout,.keyword-layout{grid-template-columns:210px minmax(0,1fr)}.map-sidebar{border-right:1px solid var(--line);border-bottom:0}}
@media(max-width:700px){body.explorer-active main{padding:16px 12px 35px}.visual-heading{display:block}.visual-heading h2{font-size:27px}.map-layout,.keyword-layout{display:flex;flex-direction:column;height:auto;min-height:0}.map-sidebar,.cloud-sidebar{max-height:280px;border-right:0;border-bottom:1px solid var(--line);padding:14px}.map-canvas,.cloud-stage{height:540px;min-height:540px}.visual-drawer{position:fixed;top:10vh;bottom:10px;right:8px;width:calc(100vw - 16px);border:1px solid var(--line);border-radius:14px;z-index:50}.map-toolbar{top:12px;left:10px;right:10px;flex-wrap:wrap}.visual-metric{font-size:10px}.cloud-stage{padding:45px 4px}.cloud-stage canvas{width:100%;height:auto}}
`;

export function installReportVisuals({ analysis, audienceMap, keywordCloud }) {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const categoryNames = { all: '全部', product: '产品', adjacent_product: '邻近产品', solution: '解决方案', pain: '痛点', fitment: '车型适配', competitor_brand: '品牌', use_case: '使用场景', headlight: '头灯', 'fog-light': '雾灯', 'tail-brake': '尾灯 / 刹车灯' };
  const statusNames = { candidate_review: '待审核', exploratory_used: '已探索', approved: '已批准', rejected: '已排除' };
  const colors = { product: '#126a58', adjacent_product: '#bc7537', solution: '#327d8c', pain: '#b05343', fitment: '#736093', competitor_brand: '#9b7726', use_case: '#427963' };
  const evidenceById = new Map((analysis.evidence ?? []).map(item => [item.id, item]));
  const graph = audienceMap ?? { nodes: [], edges: [] };
  const byId = new Map((graph.nodes ?? []).map(node => [node.id, node]));
  const mapState = { query: '', category: 'all', focusId: '', mode: 'all' };
  const svg = $('audience-map');
  const mapDrawer = $('map-detail');
  const mapContent = $('map-detail-content');
  const ns = 'http://www.w3.org/2000/svg';
  let graphView;
  let lastMapTrigger = null;
  let hoveredNodeId = '';
  const mapHistory = [];
  // Apply a temporary mask without rebuilding SVG or moving the hovered node.
  // Only direct edges count; neighbors' other connections remain hidden.
  function previewNeighbors(nodeId = '') {
    hoveredNodeId = nodeId;
    const edges = graphView.edges.filter(edge => edge.source === nodeId || edge.target === nodeId);
    const visible = new Set([nodeId, ...edges.flatMap(edge => [edge.source, edge.target])]);
    svg.querySelectorAll('.graph-node').forEach(element => {
      const hidden = Boolean(nodeId) && !visible.has(element.dataset.id);
      element.style.visibility = hidden ? 'hidden' : '';
      element.setAttribute('aria-hidden', String(hidden));
    });
    svg.querySelectorAll('.graph-edge').forEach(element => {
      element.style.visibility = nodeId && element.dataset.source !== nodeId && element.dataset.target !== nodeId ? 'hidden' : '';
    });
  }
  function svgNode(tag, attributes = {}, text) {
    const element = document.createElementNS(ns, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function lines(items, fallback = '未知 / 待验证') {
    return '<ul>' + (items?.length ? items.map(item => '<li>' + esc(item) + '</li>').join('') : '<li>' + fallback + '</li>') + '</ul>';
  }
  function safeLink(url) {
    try { const parsed = new URL(url); return parsed.protocol === 'https:' && /(^|\.)reddit\.com$/.test(parsed.hostname) ? esc(parsed.href) : ''; } catch { return ''; }
  }
  function renderEvidence(items) {
    return items.length ? items.map(item => {
      const url = safeLink(item.url);
      return '<div class="visual-evidence"><div class="muted">r/' + esc(item.subreddit ?? 'unknown') + ' · ' + esc(item.quality?.quality_band ?? item.quality_band ?? 'unknown') + '</div><blockquote lang="en">' + esc((item.quote_original ?? item.body_original ?? item.title ?? '').slice(0, 650)) + '</blockquote>' + (url ? '<a href="' + url + '" target="_blank" rel="noreferrer">查看 Reddit 原文 ↗</a>' : '<span>原文链接不可用</span>') + '</div>';
    }).join('') : '<p class="muted">暂无可点击证据</p>';
  }
  function makeRow(node, count) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'visual-row' + (mapState.focusId === node.id ? ' active' : '');
    button.dataset.nodeId = node.id;
    button.innerHTML = '<i class="visual-dot ' + esc(node.type) + '"></i><span><strong>' + esc(node.label) + '</strong><small>' + (node.type === 'community' ? count + ' 个关联产品概念' : '机会评分 ' + esc(node.opportunity_score ?? node.size ?? 0)) + '</small></span>';
    button.addEventListener('click', () => selectNode(node.id, button));
    return button;
  }
  function showMapDetail(nodeId, sourceCommunity = '') {
    const node = byId.get(nodeId);
    if (!node) return;
    const edges = graphView.eligibleEdges.filter(edge => edge.source === nodeId || edge.target === nodeId);
    const evidenceEdges = sourceCommunity ? edges.filter(edge => edge.target === sourceCommunity) : edges;
    const ids = [...new Set(evidenceEdges.flatMap(edge => edge.evidence_ids))];
    const evidence = ids.map(id => evidenceById.get(id)).filter(Boolean);
    const related = [...new Set(edges.map(edge => edge.source === nodeId ? edge.target : edge.source))].map(id => byId.get(id)).filter(Boolean);
    const product = (analysis.opportunities ?? []).find(item => item.id === nodeId) ?? node;
    mapContent.innerHTML = '<p class="eyebrow">' + (node.type === 'community' ? 'Reddit Community' : node.entry_type === 'adjacent_bundle' ? '邻近配套' : '产品机会') + '</p><h3>' + esc(node.label) + '</h3>'
      + (node.type === 'product' ? '<div class="score-value">' + esc(node.opportunity_score ?? node.size ?? 0) + '<small> / 100 · 机会评分</small></div><div class="chips">' + (node.fitment_tags ?? []).map(tag => '<span>' + esc(tag) + '</span>').join('') + '</div><h4>痛点</h4>' + lines(node.pain_points) + '<h4>产品机会 / 切入方式</h4>' + lines(product.solution_ideas ?? product.entry_gaps ?? node.solution_ideas) + '<h4>价格线索</h4><p>' + (product.commercial?.pricing_band?.source === 'product-bound' ? esc(product.commercial.pricing_band.value) + ' · fact' : '未核实的官网 / Amazon 产品价格') + '</p>' : '<p>' + related.length + ' 个关联产品概念 · ' + evidence.length + ' 条关联证据</p><p class="muted">节点大小表示关联产品数量，不代表社区人数。</p>')
      + '<h4>' + (node.type === 'community' ? '关联产品 · 点击反查' : '关联社区 · 点击下钻') + '</h4><div id="map-related-nodes"></div>'
      + '<h4>代表证据 · ' + evidence.length + ' 条</h4>'
      + (sourceCommunity ? '<p class="muted">仅展示 ' + esc(byId.get(sourceCommunity)?.label ?? '') + ' 与该产品的关联证据。</p>' : '')
      + renderEvidence(evidence);
    related.forEach(item => $('map-related-nodes').appendChild(makeRow(item, graphView.eligibleEdges.filter(edge => edge.target === item.id).length)));
    mapDrawer.hidden = false;
  }
  function selectNode(nodeId, trigger) {
    lastMapTrigger = trigger ?? null;
    const sourceCommunity = byId.get(mapState.focusId)?.type === 'community' && byId.get(nodeId)?.type === 'product' ? mapState.focusId : '';
    if (nodeId !== mapState.focusId) mapHistory.push(mapState.focusId);
    mapState.focusId = nodeId;
    renderMap();
    showMapDetail(nodeId, sourceCommunity);
  }
  function closeMapDetail() {
    mapDrawer.hidden = true;
    const target = lastMapTrigger?.isConnected ? lastMapTrigger
      : [...svg.querySelectorAll('[data-id]')].find(element => element.dataset.id === mapState.focusId);
    target?.focus?.();
  }
  function resetMap() {
    mapHistory.length = 0;
    mapState.focusId = '';
    mapState.query = '';
    mapState.category = 'all';
    mapState.mode = 'all';
    $('map-search').value = '';
    $('category-filters').querySelectorAll('button').forEach(button => button.classList.toggle('active', button.dataset.value === 'all'));
    closeMapDetail();
    renderMap();
  }
  function labelLines(label, max = 17) {
    const chunks = [];
    let line = '';
    for (const character of Array.from(label)) {
      line += character;
      if (line.length >= max) { chunks.push(line); line = ''; }
    }
    if (line) chunks.push(line);
    return chunks;
  }
  function renderMap() {
    hoveredNodeId = '';
    graphView = selectGraphView(graph, mapState);
    if (!graphView.focus) mapState.focusId = '';
    const communityList = $('map-community-list');
    const productList = $('map-product-list');
    communityList.replaceChildren(); productList.replaceChildren();
    const communities = graphView.eligibleNodes.filter(node => node.type === 'community');
    const products = graphView.eligibleNodes.filter(node => node.type === 'product');
    communities.forEach(node => communityList.appendChild(makeRow(node, graphView.eligibleEdges.filter(edge => edge.target === node.id).length)));
    const focusProducts = graphView.focus?.type === 'community' ? graphView.nodes.filter(node => node.type === 'product') : products;
    focusProducts.forEach(node => productList.appendChild(makeRow(node)));
    if (!communities.length) communityList.innerHTML = '<p class="visual-empty">没有匹配的社区</p>';
    if (!focusProducts.length) productList.innerHTML = '<p class="visual-empty">没有匹配的产品</p>';
    $('map-product-title').textContent = graphView.focus?.type === 'community' ? graphView.focus.label + ' · 关联产品' : '产品机会 · 点击反查';
    $('map-metrics').textContent = communities.length + ' 社区 · ' + products.length + ' 产品 · ' + graphView.eligibleEdges.length + ' 证据关系';
    $('map-view-toggle').textContent = mapState.mode === 'all' && !graphView.focus ? '社区总览' : '显示全部关系';
    $('map-back').hidden = mapHistory.length === 0;
    $('map-help').textContent = graphView.focus ? '当前聚焦：' + graphView.focus.label + ' · 悬停查看直接关联，点击继续探索' : mapState.mode === 'all' ? '实心：产品机会 · 空心：社区 · 悬停只显示直接关联，移开恢复全图' : '点击社区展开相关产品，也可从左侧产品列表反查社区';
    svg.replaceChildren();
    if (!graphView.nodes.length) { svg.appendChild(svgNode('text', { x: 500, y: 350, 'text-anchor': 'middle', fill: '#817b72', 'font-size': 18 }, '没有匹配数据，请调整搜索或筛选')); return; }
    const positions = new Map();
    const ring = (nodes, rx, ry) => nodes.forEach((node, index) => {
      const theta = -Math.PI / 2 + 2 * Math.PI * index / nodes.length;
      positions.set(node.id, { x: 500 + rx * Math.cos(theta), y: 345 + ry * Math.sin(theta) });
    });
    if (graphView.focus) {
      positions.set(graphView.focus.id, { x: 500, y: 345 });
      ring(graphView.nodes.filter(node => node.id !== graphView.focus.id), 310, 235);
    } else if (mapState.mode === 'all') {
      ring(products, 155, 125); ring(communities, 340, 260);
    } else ring(communities, 305, 230);
    graphView.edges.forEach(edge => {
      const a = positions.get(edge.source), b = positions.get(edge.target);
      if (a && b) svg.appendChild(svgNode('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: 'graph-edge', 'data-source': edge.source, 'data-target': edge.target }));
    });
    graphView.nodes.forEach(node => {
      const point = positions.get(node.id);
      const count = graphView.eligibleEdges.filter(edge => edge.target === node.id).length;
      const radius = node.type === 'product' ? 13 + Math.sqrt(Math.max(0, Number(node.opportunity_score ?? node.size ?? 0)) / 100) * 20 : 16 + Math.sqrt(count) * 8;
      const group = svgNode('g', { class: 'graph-node ' + node.type + (node.id === mapState.focusId ? ' selected' : ''), transform: 'translate(' + point.x + ' ' + point.y + ')', tabindex: 0, role: 'button', 'aria-label': node.label, 'data-id': node.id, 'data-entry': node.entry_type });
      group.appendChild(svgNode('circle', { r: radius }));
      if (node.type === 'product') group.appendChild(svgNode('text', { y: 4, style: 'fill:#fff;font-size:12px;font-weight:700' }, node.opportunity_score ?? node.size ?? 0));
      const label = svgNode('text', { y: radius + 20 });
      const chunks = labelLines(node.label);
      chunks.forEach((chunk, index) => label.appendChild(svgNode('tspan', { x: 0, dy: index ? 16 : 0 }, chunk)));
      group.appendChild(label);
      group.appendChild(svgNode('text', { y: radius + 22 + chunks.length * 16, class: 'node-meta' }, node.type === 'community' ? count + ' 个产品概念' : node.entry_type === 'adjacent_bundle' ? '邻近配套' : '产品机会'));
      group.addEventListener('click', event => { event.stopPropagation(); selectNode(node.id, group); });
      group.addEventListener('pointerenter', event => { if (event.pointerType !== 'touch') previewNeighbors(node.id); });
      group.addEventListener('pointerleave', () => { if (hoveredNodeId === node.id) previewNeighbors(); });
      group.addEventListener('focus', () => previewNeighbors(node.id));
      group.addEventListener('blur', () => previewNeighbors());
      group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectNode(node.id, group); } });
      svg.appendChild(group);
    });
  }
  function filterButtons(root, values, labels, handler) {
    ['all', ...new Set(values ?? [])].forEach((value, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'filter-btn' + (index === 0 ? ' active' : '');
      button.dataset.value = value; button.textContent = value === 'all' ? '全部' : labels[value] ?? value;
      button.addEventListener('click', () => { root.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button)); handler(value); });
      root.appendChild(button);
    });
  }
  filterButtons($('category-filters'), graph.filters?.categories, categoryNames, value => { mapState.category = value; closeMapDetail(); renderMap(); });
  $('map-search').addEventListener('input', event => { mapState.query = event.target.value; closeMapDetail(); renderMap(); });
  $('reset-map').addEventListener('click', resetMap);
  $('map-view-toggle').addEventListener('click', () => { mapHistory.length = 0; mapState.mode = mapState.mode === 'all' && !mapState.focusId ? 'communities' : 'all'; mapState.focusId = ''; closeMapDetail(); renderMap(); });
  $('map-back').addEventListener('click', () => { mapState.focusId = mapHistory.pop() ?? ''; closeMapDetail(); renderMap(); if (mapState.focusId) showMapDetail(mapState.focusId); });
  $('map-detail-close').addEventListener('click', closeMapDetail);
  svg.addEventListener('click', event => { if (event.target === svg) closeMapDetail(); });
  svg.addEventListener('pointerleave', () => previewNeighbors());
  renderMap();

  const canvas = $('keyword-wordcloud');
  const ctx = canvas.getContext('2d');
  const cloudState = { query: '', category: 'all', status: 'all', minimum: Number(keywordCloud.filters?.minimum_score ?? 0) };
  const terms = keywordCloud.terms ?? [];
  let layout = { placed: [], omitted: [] };
  let selectedTerm = null;
  let hovered = null;
  const tooltip = $('cloud-tooltip');
  const spriteCache = new Map();
  const fontFamily = '"Segoe UI", "Microsoft YaHei", sans-serif';
  function makeSprite(term, fontSize, angle, cell) {
    const key = JSON.stringify([term.term, fontSize, angle]);
    if (spriteCache.has(key)) return spriteCache.get(key);
    const stamp = document.createElement('canvas');
    const stampCtx = stamp.getContext('2d', { willReadFrequently: true });
    stampCtx.font = '600 ' + fontSize + 'px ' + fontFamily;
    const textWidth = Math.ceil(stampCtx.measureText(term.term).width + 16);
    const textHeight = Math.ceil(fontSize * 1.65 + 16);
    const width = Math.ceil((angle ? textHeight : textWidth) / cell);
    const height = Math.ceil((angle ? textWidth : textHeight) / cell);
    stamp.width = width * cell; stamp.height = height * cell;
    stampCtx.font = '600 ' + fontSize + 'px ' + fontFamily;
    stampCtx.translate(stamp.width / 2, stamp.height / 2); stampCtx.rotate(angle);
    stampCtx.textAlign = 'center'; stampCtx.textBaseline = 'middle';
    stampCtx.fillStyle = colors[term.category] ?? colors.product;
    stampCtx.fillText(term.term, 0, 0);
    const pixels = stampCtx.getImageData(0, 0, stamp.width, stamp.height).data;
    const maskSet = new Set();
    for (let y = 0; y < stamp.height; y++) for (let x = 0; x < stamp.width; x++) {
      if (pixels[(y * stamp.width + x) * 4 + 3] <= 32) continue;
      const cx = Math.floor(x / cell), cy = Math.floor(y / cell);
      // A one-cell halo keeps adjacent glyphs from visually touching.
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (cx + dx >= 0 && cx + dx < width && cy + dy >= 0 && cy + dy < height) maskSet.add((cy + dy) * width + cx + dx);
      }
    }
    const result = { width, height, mask: [...maskSet].map(index => [index % width, Math.floor(index / width)]), stamp, maskSet };
    spriteCache.set(key, result);
    return result;
  }
  function paintCloud() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const item of layout.placed) {
      ctx.globalAlpha = hovered && hovered !== item ? 0.5 : 1;
      ctx.drawImage(item.sprite.stamp, item.x, item.y);
    }
    ctx.globalAlpha = 1;
    if (!layout.placed.length) { ctx.font = '18px ' + fontFamily; ctx.fillStyle = '#817b72'; ctx.textAlign = 'center'; ctx.fillText('没有匹配的关键词，请调整筛选', 500, 325); }
  }
  function showCloudDetail(term) {
    selectedTerm = term;
    $('keyword-cloud-detail').hidden = !term;
    if (!term) return;
    $('keyword-cloud-detail-content').innerHTML = '<p class="eyebrow">Keyword Evidence</p><h3>' + esc(term.term) + '</h3><div class="score-value">' + esc(term.display_weight ?? term.discovery_score ?? 0) + '<small> 展示权重</small></div><p>' + esc(categoryNames[term.category] ?? term.category) + ' · ' + esc(statusNames[term.status] ?? term.status) + '</p><p class="muted">展示权重由有效用户、证据质量、社区覆盖等信号计算，不等于原始词频或市场规模。</p><h4>数据来源</h4><p>' + esc(term.unique_user_count ?? 0) + ' 位用户 · ' + esc(term.community_count ?? term.communities?.length ?? 0) + ' 个社区 · 发现分 ' + esc(term.discovery_score ?? 0) + '</p>' + lines(term.communities) + '<h4>父级种子词</h4>' + lines(term.parent_formal_terms) + '<h4>相关产品</h4>' + lines((term.related_product_ids ?? []).map(id => byId.get(id)?.label ?? id)) + '<h4>代表证据</h4>' + renderEvidence(term.representative_evidence ?? []);
  }
  function renderCloud() {
    const filtered = terms.filter(term => (cloudState.category === 'all' || term.category === cloudState.category || term.categories?.includes(cloudState.category))
      && (cloudState.status === 'all' || term.status === cloudState.status)
      && Number(term.discovery_score ?? 0) >= cloudState.minimum
      && (!cloudState.query || [term.term, term.category, ...(term.categories ?? []), ...(term.communities ?? [])].join(' ').toLowerCase().includes(cloudState.query)));
    const list = $('cloud-term-list');
    list.replaceChildren();
    filtered.forEach(term => {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = term.term + ' · ' + (term.display_weight ?? term.discovery_score ?? 0);
      button.addEventListener('click', () => showCloudDetail(term)); list.appendChild(button);
    });
    if (!filtered.length) list.innerHTML = '<p class="visual-empty">没有匹配关键词</p>';
    if (selectedTerm && !filtered.includes(selectedTerm)) showCloudDetail(null);
    hovered = null; tooltip.hidden = true;
    if (!ctx) { $('cloud-count').textContent = '浏览器不支持 Canvas，请使用左侧关键词列表'; return; }
    for (const scale of [1, 0.88, 0.76, 0.64, 0.52, 0.42]) {
      layout = packCloudWords(filtered, { width: 1000, height: 650, cell: 4, scale, makeSprite });
      if (!layout.omitted.length) break;
    }
    $('cloud-count').textContent = '已绘制 ' + layout.placed.length + ' / ' + filtered.length + ' 个匹配词 · 词库共 ' + terms.length + ' 个';
    $('cloud-caption').textContent = layout.omitted.length ? layout.omitted.length + ' 个词未放入画布，可在左侧完整列表中查看' : '字号 = 展示权重 · 颜色 = 词类别 · 悬停查看数值，点击追溯证据';
    // Expose rendered geometry as DOM metadata for offline visual QA, not as a
    // second analysis source. All values still originate in keyword_cloud.json.
    canvas.dataset.placedCount = String(layout.placed.length);
    canvas.dataset.filteredCount = String(filtered.length);
    paintCloud();
  }
  function hitWord(event) {
    const bounds = canvas.getBoundingClientRect();
    // object-fit:contain may letterbox a canvas constrained by panel height.
    const scale = Math.min(bounds.width / 1000, bounds.height / 650);
    const x = (event.clientX - bounds.left - (bounds.width - 1000 * scale) / 2) / scale;
    const y = (event.clientY - bounds.top - (bounds.height - 650 * scale) / 2) / scale;
    return layout.placed.find(item => {
      const sx = Math.floor((x - item.x) / layout.cell), sy = Math.floor((y - item.y) / layout.cell);
      return sx >= 0 && sy >= 0 && sx < item.sprite.width && sy < item.sprite.height && item.sprite.maskSet.has(sy * item.sprite.width + sx);
    });
  }
  canvas.addEventListener('pointermove', event => {
    const hit = hitWord(event);
    if (hit !== hovered) { hovered = hit; paintCloud(); }
    canvas.style.cursor = hit ? 'pointer' : 'default';
    tooltip.hidden = !hit;
    if (hit) {
      tooltip.textContent = hit.term.term + '\n展示权重 ' + (hit.term.display_weight ?? hit.term.discovery_score ?? 0) + ' · ' + (categoryNames[hit.term.category] ?? hit.term.category);
      tooltip.style.left = Math.max(8, Math.min(event.clientX + 14, window.innerWidth - 288)) + 'px';
      tooltip.style.top = Math.max(8, Math.min(event.clientY + 14, window.innerHeight - 90)) + 'px';
    }
  });
  canvas.addEventListener('pointerleave', () => { hovered = null; tooltip.hidden = true; paintCloud(); });
  canvas.addEventListener('click', event => { const hit = hitWord(event); if (hit) { tooltip.hidden = true; showCloudDetail(hit.term); } });
  filterButtons($('keyword-cloud-categories'), keywordCloud.filters?.categories, categoryNames, value => { cloudState.category = value; renderCloud(); });
  filterButtons($('keyword-cloud-statuses'), keywordCloud.filters?.statuses, statusNames, value => { cloudState.status = value; renderCloud(); });
  $('keyword-cloud-search').addEventListener('input', event => { cloudState.query = event.target.value.trim().toLowerCase(); renderCloud(); });
  $('keyword-cloud-score').addEventListener('input', event => { cloudState.minimum = Number(event.target.value); $('cloud-score-value').textContent = event.target.value; renderCloud(); });
  $('keyword-cloud-reset').addEventListener('click', () => {
    Object.assign(cloudState, { query: '', category: 'all', status: 'all', minimum: 0 });
    $('keyword-cloud-search').value = ''; $('keyword-cloud-score').value = '0'; $('cloud-score-value').textContent = '0';
    ['keyword-cloud-categories', 'keyword-cloud-statuses'].forEach(id => $(id).querySelectorAll('button').forEach(button => button.classList.toggle('active', button.dataset.value === 'all')));
    showCloudDetail(null); renderCloud();
  });
  $('keyword-cloud-detail-close').addEventListener('click', () => showCloudDetail(null));
  $('cloud-legend').innerHTML = [...new Set(terms.map(term => term.category))].map(category => '<div class="visual-legend"><i class="visual-dot" style="background:' + (colors[category] ?? colors.product) + '"></i>' + esc(categoryNames[category] ?? category) + '</div>').join('');
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMapDetail(); previewNeighbors(); showCloudDetail(null); tooltip.hidden = true; } });
  let cloudInitialized = false;
  document.addEventListener('radar-tab-change', event => {
    document.body.classList.toggle('explorer-active', ['map', 'keyword-cloud'].includes(event.detail));
    tooltip.hidden = true;
    previewNeighbors();
    if (event.detail === 'keyword-cloud' && !cloudInitialized) { renderCloud(); cloudInitialized = true; }
  });
}

export function reportVisualScript() {
  return [selectGraphView, packCloudWords, installReportVisuals].map(fn => fn.toString()).join('\n')
    + '\ninstallReportVisuals({ analysis, audienceMap, keywordCloud });';
}
