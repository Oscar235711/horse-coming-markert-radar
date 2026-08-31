import test from 'node:test';
import assert from 'node:assert/strict';
import { enrichReferenceProducts } from '../src/reference-products.mjs';
import { renderReportHtml } from '../src/radar-report.mjs';

function fixture() {
  const row = (id, text, type, score, eligible = true) => ({
    id, post_id: 'thread-1', author: id, type, body_original: text,
    url: 'https://www.reddit.com/r/Trucks/comments/abc/',
    quality: { quality_score: score, quality_band: 'high', eligible },
  });
  return { evidence: [
    row('p1', 'I installed Acme Orbit with excellent cutoff.', 'post', 90),
    row('c1', 'Acme Orbit cutoff is good. Acme Orbit has a fan.', 'comment', 80),
    row('c2', 'Acme Orbit has a clear cutoff.', 'comment', 40),
    row('spam', 'Acme Orbit cutoff sale sale sale.', 'comment', 100, false),
    row('other', 'Another bulb has a fan.', 'comment', 100),
  ], opportunities: [{ id: 'headlight', label: '头灯', category: 'headlight',
    evidence_ids: ['p1', 'c1', 'c2', 'spam'],
    reference_products: [{ name: 'Acme Orbit', brand: 'Acme', evidence_ids: ['p1'] }],
  }], research_keywords: { anchors: ['cutoff', 'fan', 'Acme Orbit'] } };
}

test('discussion counts unique eligible mentions and weights only the actual mentioning comments', () => {
  const data = fixture();
  data.evidence.push(data.evidence[1], { ...data.evidence[1], id: 'duplicate-copy' });
  data.opportunities[0].evidence_ids.push('duplicate-copy');
  const before = structuredClone(data);
  const out = enrichReferenceProducts(data);
  assert.deepEqual(data, before, 'derivation must not change raw evidence');
  assert.equal(out.opportunities[0].reference_products.length, 1);
  const product = out.opportunities[0].reference_products[0];
  assert.equal(product.name, 'Acme Orbit');
  assert.equal(product.discussion.mention_count, 3);
  assert.equal(product.discussion.post_count, 1);
  assert.equal(product.discussion.comment_count, 2);
  assert.equal(product.discussion.score, 2.2);
  assert.equal(product.discussion.average_comment_quality, 60);
  assert.equal(product.top_keyword.term, 'cutoff');
  assert.equal(product.top_keyword.score, 100);
  assert.deepEqual(product.top_keyword.evidence_ids, ['p1','c1','c2']);
  assert.deepEqual(enrichReferenceProducts(out), out, 'rendering saved enriched data is idempotent');
});

test('legacy post titles do not become product names; explicit variants remain distinct', () => {
  const data = fixture();
  data.evidence[0].title = 'Help with my old truck';
  data.evidence[0].body_original = 'I installed AUXITO 9005/H11 bulbs with good cutoff.';
  data.evidence[1].body_original = 'I bought AUXITO H7 bulbs with good cutoff.';
  data.evidence[2].body_original = 'No specific product was named.';
  data.opportunities[0].reference_products = [{name: 'Help with my old truck',evidence_ids:['p1']}];
  const products = enrichReferenceProducts(data).opportunities[0].reference_products;
  assert.deepEqual(products.map(x => x.name), ['AUXITO 9005/H11', 'AUXITO H7']);
  assert.ok(products.every(x => x.discussion.mention_count === 1));
});

test('brand on an unrelated accessory does not get attached to the lighting reference', () => {
  const data = fixture();
  data.evidence[0].body_original = 'LASFIT floor liners are nice. I also installed headlights.';
  data.opportunities[0].reference_products = [];
  const out = enrichReferenceProducts(data);
  assert.equal(out.opportunities[0].reference_products.length, 0);
});

test('no comments and no keyword cooccurrence remain explicit, not invented', () => {
  const data = fixture();
  data.evidence = [data.evidence[0]];
  data.research_keywords = { anchors: ['unrelated keyword'] };
  const product = enrichReferenceProducts(data).opportunities[0].reference_products[0];
  assert.equal(product.discussion.score, 1);
  assert.equal(product.discussion.average_comment_quality, null);
  assert.equal(product.top_keyword, null);
});

test('fractional comment weights preserve Dice normalization and missing quality adds no association', () => {
  const data = fixture();
  data.evidence = [{ ...data.evidence[1], quality: {eligible:true, quality_score:20} }];
  const product = enrichReferenceProducts(data).opportunities[0].reference_products[0];
  assert.equal(product.discussion.score, 0.2);
  assert.equal(product.top_keyword.score, 100);
  data.evidence[0].quality = {eligible:true};
  assert.equal(enrichReferenceProducts(data).opportunities[0].reference_products[0].top_keyword, null);
});

test('report references start collapsed and show only names, discussion and keyword with auditable evidence', () => {
  const data = fixture();
  const html = renderReportHtml({ analysis:data, audienceMap:{nodes:[],edges:[]}, keywordCloud:{terms:[],filters:{}} });
  assert.match(html, /<details class="reference-products-section"><summary>参考产品/);
  assert.doesNotMatch(html, /<details class="reference-products-section"[^>]*\bopen\b/);
  assert.match(html, /<h5>Acme Orbit<\/h5>/);
  assert.match(html, /2\.2 <small>加权提及/);
  assert.match(html, /最高关联词/);
  assert.match(html, /共现 3 条 · 关联度 100%/);
  assert.doesNotMatch(html, /参考产品与价格/);
});
