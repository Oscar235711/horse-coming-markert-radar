import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { selectGraphView, packCloudWords, installReportVisuals } from '../src/report-visuals.mjs';
import { renderReportHtml } from '../src/radar-report.mjs';
import { buildAudienceMap } from '../src/radar-core.mjs';
import { createReportFixture } from './fixtures/task-6-report.fixture.mjs';

const graph = {
  nodes: [
    { id: 'headlight', type: 'product', label: 'LED headlight kit', category: 'headlight', fitment_tags: ['H11'] },
    { id: 'fog', type: 'product', label: 'Fog light kit', category: 'fog' },
    { id: 'trucks', type: 'community', label: 'r/Trucks' },
    { id: 'tacoma', type: 'community', label: 'r/Tacoma' },
  ],
  edges: [
    { source: 'headlight', target: 'trucks', evidence_ids: ['a'] },
    { source: 'headlight', target: 'tacoma', evidence_ids: ['b'] },
    { source: 'fog', target: 'tacoma', evidence_ids: ['c'] },
  ],
};

test('community overview and all-relations view preserve product-community counts without inventing edges', () => {
  const before = structuredClone(graph);
  assert.deepEqual(selectGraphView(graph).nodes.map(node => node.id), ['trucks', 'tacoma']);
  assert.equal(selectGraphView(graph).edges.length, 0);
  const all = selectGraphView(graph, { mode: 'all' });
  assert.equal(all.nodes.length, 4);
  assert.equal(all.edges.length, 3);
  assert.deepEqual(graph, before);
});

test('product search retains matching communities; community search retains its products', () => {
  const byFitment = selectGraphView(graph, { query: 'h11', mode: 'all' });
  assert.deepEqual(byFitment.nodes.map(node => node.id), ['headlight', 'trucks', 'tacoma']);
  const byCommunity = selectGraphView(graph, { query: 'trucks', mode: 'all' });
  assert.deepEqual(byCommunity.nodes.map(node => node.id), ['headlight', 'trucks']);
  assert.equal(byCommunity.edges[0].evidence_ids[0], 'a');
  assert.equal(selectGraphView(graph, { query: 'no match' }).nodes.length, 0);
});

test('community and product drill-down include only direct neighbors and survive category changes', () => {
  const community = selectGraphView(graph, { focusId: 'tacoma' });
  assert.deepEqual(community.nodes.map(node => node.id), ['headlight', 'fog', 'tacoma']);
  assert.deepEqual(community.edges.flatMap(edge => edge.evidence_ids), ['b', 'c']);
  const product = selectGraphView(graph, { focusId: 'headlight' });
  assert.deepEqual(product.nodes.map(node => node.id), ['headlight', 'trucks', 'tacoma']);
  const changed = selectGraphView(graph, { focusId: 'headlight', category: 'fog' });
  assert.equal(changed.focus, null);
  assert.deepEqual(changed.nodes.map(node => node.id), ['tacoma']);
});

test('malformed, orphan, and evidence-free graph edges never become rendered relationships', () => {
  const corrupt = structuredClone(graph);
  corrupt.edges.push({ source: 'trucks', target: 'tacoma', evidence_ids: ['bad'] },
    { source: 'ghost', target: 'trucks', evidence_ids: ['bad'] },
    { source: 'fog', target: 'trucks', evidence_ids: [] });
  assert.equal(selectGraphView(corrupt, { mode: 'all' }).edges.length, 3);
});

test('hover masks direct neighbors in place, restores on leave, and preserves click drill-down and filters', () => {
  // No browser navigation is needed: exercise the installed event handlers on
  // a minimal DOM, including the SVG attributes that determine visibility.
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.style = {}; this.attributes = {}; this.events = {}; this.isConnected = true; this.className = ''; this.classList = { toggle() {} }; }
    setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'class') this.className = value; if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, x) => x.toUpperCase())] = value; }
    appendChild(element) { this.children.push(element); return element; }
    replaceChildren() { this.children.forEach(x => x.isConnected = false); this.children = []; }
    addEventListener(name, handler) { (this.events[name] ??= []).push(handler); }
    emit(name, extra = {}) { for (const handler of this.events[name] ?? []) handler({target:this,stopPropagation(){},preventDefault(){},...extra}); }
    querySelectorAll(selector) { return this.children.flatMap(x => [x, ...x.querySelectorAll('*')]).filter(x => selector === '*' || (selector.startsWith('.') ? x.className.split(' ').includes(selector.slice(1)) : selector === '[data-id]' ? x.dataset.id : x.tagName === selector)); }
    getContext() { return null; }
    focus() { this.emit('focus'); }
  }
  const elements = new Map();
  const document = { getElementById(id) { if (!elements.has(id)) elements.set(id, new Element(id === 'audience-map' ? 'svg' : 'div')); return elements.get(id); },
    createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    addEventListener() {} };
  const scope = vm.createContext({ document, URL });
  scope.analysis = { opportunities: [], evidence: [] };
  scope.audienceMap = { ...graph, filters: { categories: ['headlight','fog'] } };
  scope.keywordCloud = { terms: [], filters: {} };
  vm.runInContext(selectGraphView.toString() + '\n' + packCloudWords.toString() + '\n' + installReportVisuals.toString() + '\ninstallReportVisuals({analysis,audienceMap,keywordCloud});', scope);
  const svg = document.getElementById('audience-map');
  const nodes = () => svg.querySelectorAll('.graph-node');
  const visible = () => nodes().filter(x => x.style.visibility !== 'hidden').map(x => x.dataset.id);
  const lines = () => svg.querySelectorAll('.graph-edge').filter(x => x.style.visibility !== 'hidden');
  const before = nodes().map(x => x.attributes.transform);
  const trucks = nodes().find(x => x.dataset.id === 'trucks');
  trucks.emit('pointerenter', {pointerType:'mouse'});
  assert.deepEqual(visible(), ['headlight','trucks']);
  assert.equal(lines().length, 1);
  assert.deepEqual(nodes().map(x => x.attributes.transform), before);
  trucks.emit('pointerleave');
  assert.equal(visible().length, 4);
  assert.equal(lines().length, 3);
  const headlight = nodes().find(x => x.dataset.id === 'headlight');
  headlight.emit('focus');
  assert.deepEqual(visible(), ['headlight','trucks','tacoma']);
  headlight.emit('blur');
  assert.equal(visible().length, 4);
  trucks.emit('click');
  assert.deepEqual(visible(), ['headlight','trucks']);
  assert.equal(document.getElementById('map-detail').hidden, false);
  document.getElementById('reset-map').emit('click');
  assert.equal(visible().length, 4);
  document.getElementById('category-filters').children.find(x => x.dataset.value === 'fog').emit('click');
  nodes().find(x => x.dataset.id === 'fog').emit('pointerenter', {pointerType:'mouse'});
  assert.deepEqual(visible(), ['fog','tacoma']);
  assert.equal(lines().length, 1);
});

// Rectangular masks intentionally provide a more conservative collision case
// than browser glyph masks; the same geometry must remain valid in both.
function rectangleSprite(term, fontSize, angle, cell) {
  const textWidth = Math.ceil(String(term.term).length * fontSize * 0.5 / cell);
  const textHeight = Math.ceil(fontSize * 1.4 / cell);
  const width = angle ? textHeight : textWidth;
  const height = angle ? textWidth : textHeight;
  return { width, height, mask: Array.from({ length: width * height }, (_, index) => [index % width, Math.floor(index / width)]) };
}
test('cloud packing is deterministic, in-bounds, collision-free, and preserves term identities', () => {
  const terms = Array.from({ length: 34 }, (_, index) => ({ term: 'term ' + index, display_weight: 100 - index * 2 }));
  const options = { width: 1000, height: 650, scale: 0.6, makeSprite: rectangleSprite };
  const packed = packCloudWords(terms, options);
  assert.equal(packed.placed.length, terms.length);
  assert.equal(packed.omitted.length, 0);
  assert.deepEqual(packCloudWords(terms, options), packed);
  const used = new Set();
  for (const item of packed.placed) {
    assert.ok(item.x >= 0 && item.y >= 0);
    assert.ok(item.x + item.sprite.width * packed.cell <= packed.width);
    assert.ok(item.y + item.sprite.height * packed.cell <= packed.height);
    for (const [dx, dy] of item.sprite.mask) {
      const key = [item.x / packed.cell + dx, item.y / packed.cell + dy].join(',');
      assert.equal(used.has(key), false, 'word masks must not overlap');
      used.add(key);
    }
  }
  assert.ok(packed.placed[0].fontSize > packed.placed.at(-1).fontSize);
  assert.ok(packed.placed.some(item => item.angle !== 0));
});

test('cloud packing preserves equal-weight font sizes and reports oversized words instead of losing them', () => {
  const terms = [{ term: 'alpha', display_weight: 50 }, { term: 'beta', display_weight: 50 }];
  const packed = packCloudWords(terms, { makeSprite: rectangleSprite });
  assert.equal(packed.placed[0].fontSize, packed.placed[1].fontSize);
  const huge = { term: 'w'.repeat(2000), display_weight: 100 };
  const failed = packCloudWords([huge], { makeSprite: rectangleSprite });
  assert.equal(failed.placed.length, 0);
  assert.deepEqual(failed.omitted, [huge]);
  assert.deepEqual(packCloudWords([], { makeSprite: rectangleSprite }).placed, []);
});

test('serialized report scripts compile and embedded evidence cannot break out of script tags', () => {
  const { analysis, manifest } = createReportFixture();
  const keywordCloud = { terms: [{ term: '</script><script>alert(1)</script>', display_weight: 20 }], filters: {} };
  const html = renderReportHtml({ analysis, manifest, audienceMap: buildAudienceMap(analysis), keywordCloud });
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new vm.Script(scripts[0][1]));
  assert.doesNotMatch(html, /<script>alert\(1\)<\/script>|<script[^>]+src=|fetch\(/);
});
