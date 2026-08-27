import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { buildAudienceMap } from '../src/radar-core.mjs';
import { renderReportHtml, writeReportArtifacts } from '../src/radar-report.mjs';

const analysis = {
  schema_version: '1.0.0',
  run_id: 'report-run',
  generated_at: '2026-08-27T00:00:00.000Z',
  scope: { country: 'US', seasonality_in_scope: false },
  metrics: { posts_analyzed: 2, comments_analyzed: 1, us_posts: 1, unknown_geography_posts: 1, communities: 1 },
  executive_summary: '识别出一个车灯机会。',
  seller_verdict: '建议先验证适配和退货风险。',
  hotspots: { communities: [{ name: 'MechanicAdvice', count: 1 }], pains: [{ name: '闪烁/故障码', count: 1 }], behavior_segments: [{ name: '升级改装', count: 1 }] },
  opportunities: [{
    id: 'product-led-headlight-upgrade',
    label: 'LED 头灯升级方案',
    category: 'headlight',
    opportunity_score: 78,
    verdict: '高信号，建议验证',
    evidence_ids: ['post-p1'],
    communities: ['MechanicAdvice'],
    fitment_tags: ['H11'],
    pain_points: ['闪烁/故障码'],
    solution_ideas: ['CANbus-safe driver'],
    behavior_segments: ['升级改装'],
    claims: { facts: ['1 篇帖子涉及该方案。'], inferences: ['可能存在适配缺口。'], unknowns: ['制造成本'] },
    commercial: {
      pricing_band: { status: 'fact', value: '$50–$100' },
      manufacturing_complexity: { status: 'unknown', value: null },
      shipping_complexity: { status: 'unknown', value: null },
      return_risk: { status: 'inference', value: '可能偏高' },
    },
    why_not_done: { status: 'inference', text: '车型协议差异大。' },
  }],
  evidence: [{ id: 'post-p1', type: 'post', subreddit: 'MechanicAdvice', url: 'https://www.reddit.com/r/MechanicAdvice/comments/p1/x', score: 30, geography: 'us', quote_original: 'My H11 LED headlights flicker after install.', fact_status: 'fact' }],
  configuration_suggestions: [],
  analysis_engine: { rules: { status: 'complete' }, llm: { status: 'not_requested' }, active_result: 'rules' },
  privacy_note: 'Only public automotive evidence is retained.',
};

test('report HTML is a self-contained seller report with an Audience Map tab', () => {
  const audienceMap = buildAudienceMap(analysis);
  const html = renderReportHtml({ analysis, audienceMap, manifest: { status: 'complete', counts: { failures: 0 } } });

  assert.match(html, /<!doctype html>/i);
  assert.match(html, /Audience Map/);
  assert.match(html, /data-tab="map"/);
  assert.match(html, /<svg[^>]+id="audience-map"/);
  assert.match(html, /LED 头灯升级方案/);
  assert.match(html, /My H11 LED headlights flicker/);
  assert.doesNotMatch(html, /<script[^>]+src=/i);
  assert.doesNotMatch(html, /<link[^>]+href=["']https?:/i);
});

test('report artifacts share one JSON source of truth', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-report-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const audienceMap = buildAudienceMap(analysis);

  const paths = await writeReportArtifacts({ runDir, analysis, audienceMap, manifest: { status: 'complete', counts: { failures: 0 } } });

  const savedAnalysis = JSON.parse(await fs.readFile(paths.analysis, 'utf8'));
  const savedMap = JSON.parse(await fs.readFile(paths.audienceMap, 'utf8'));
  const html = await fs.readFile(paths.html, 'utf8');
  const evidenceLines = (await fs.readFile(paths.evidence, 'utf8')).trim().split('\n');
  assert.equal(savedAnalysis.run_id, 'report-run');
  assert.equal(savedMap.nodes.length, audienceMap.nodes.length);
  assert.equal(evidenceLines.length, analysis.evidence.length);
  assert.match(html, /report-run/);
});
