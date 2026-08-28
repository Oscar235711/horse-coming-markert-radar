import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { buildAudienceMap } from '../src/radar-core.mjs';
import { renderReportHtml, writeReportArtifacts } from '../src/radar-report.mjs';
import { createKeywordCloudInputs, createReportFixture } from './fixtures/task-6-report.fixture.mjs';

const { analysis, manifest } = createReportFixture();

test('report HTML is a self-contained WhatToSell-style report with keyword cloud, Audience Map, and persona tabs', () => {
  const audienceMap = buildAudienceMap(analysis);
  const keywordCloud = { terms: [], filters: { categories: [], statuses: [] } };
  const html = renderReportHtml({
    analysis,
    audienceMap,
    keywordCloud,
    manifest,
  });

  assert.match(html, /<!doctype html>/i);
  assert.match(html, /Audience Map/);
  assert.match(html, /data-tab="map"/);
  assert.match(html, /data-tab="keyword-cloud"/);
  assert.match(html, /data-tab="pain"/);
  assert.match(html, /data-tab="competitors"/);
  assert.match(html, /data-tab="adjacent"/);
  assert.match(html, /data-tab="personas"/);
  assert.match(html, /关键词词云/);
  assert.match(html, /竞品\/现有产品/);
  assert.match(html, /用户画像/);
  assert.match(html, /<svg[^>]+id="audience-map"/);
  assert.match(html, /id="keyword-cloud-data"/);
  assert.match(html, /id="keyword-cloud-search"/);
  assert.match(html, /id="keyword-cloud-score"/);
  assert.match(html, /LED 头灯升级方案/);
  assert.match(html, /头灯透气膜维修套件/);
  assert.match(html, /insufficient_sample/);
  assert.match(html, /研究范围、关键词与失败记录/);
  assert.match(html, /未知项/);
  assert.match(html, /My H11 LED headlights flicker/);
  assert.doesNotMatch(html, /<script[^>]+src=/i);
  assert.doesNotMatch(html, /<link[^>]+href=/i);
  assert.doesNotMatch(html, /fetch\(/i);
});

test('report keeps adjacent opportunities out of the main formal-opportunity panel and preserves candidate-signal labeling', () => {
  const audienceMap = buildAudienceMap(analysis);
  const { candidates, evidence } = createKeywordCloudInputs();
  const html = renderReportHtml({
    analysis,
    audienceMap,
    keywordCloud: { terms: candidates, filters: { categories: ['product'], statuses: ['candidate_review', 'exploratory_used'] } },
    manifest,
  });

  assert.match(html, /正式机会/);
  assert.match(html, /候选信号/);
  assert.match(html, /邻近配套/);
  assert.match(html, /id="formal-opportunities"/);
  assert.doesNotMatch(html, /id="formal-opportunities"[\s\S]*data-opportunity-type="adjacent_bundle"/);
});

test('report artifacts share one JSON source of truth and emit dedicated Task 6 artifacts', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-report-'));
  t.after(() => fs.rm(runDir, { recursive: true, force: true }));
  const audienceMap = buildAudienceMap(analysis);
  const { candidates } = createKeywordCloudInputs();
  const keywordCloud = { terms: candidates, filters: { categories: ['product'], statuses: ['candidate_review', 'exploratory_used'] } };

  const paths = await writeReportArtifacts({
    runDir,
    analysis,
    audienceMap,
    keywordCloud,
    manifest,
  });

  const savedAnalysis = JSON.parse(await fs.readFile(paths.analysis, 'utf8'));
  const savedMap = JSON.parse(await fs.readFile(paths.audienceMap, 'utf8'));
  const savedCloud = JSON.parse(await fs.readFile(paths.keywordCloud, 'utf8'));
  const savedOpportunities = JSON.parse(await fs.readFile(paths.opportunities, 'utf8'));
  const savedPersonas = JSON.parse(await fs.readFile(paths.personas, 'utf8'));
  const html = await fs.readFile(paths.html, 'utf8');
  const qualifiedEvidenceLines = (await fs.readFile(paths.qualityEvidence, 'utf8')).trim().split('\n');
  const excludedEvidenceLines = (await fs.readFile(paths.excludedEvidence, 'utf8')).trim().split('\n');
  assert.equal(savedAnalysis.run_id, 'report-run');
  assert.equal(savedMap.nodes.length, audienceMap.nodes.length);
  assert.equal(savedCloud.terms.length, keywordCloud.terms.length);
  assert.equal(savedOpportunities.opportunities.length, analysis.opportunities.length);
  assert.equal(savedPersonas.persona_status, analysis.personas.persona_status);
  assert.equal(qualifiedEvidenceLines.length, analysis.evidence.filter((item) => item.quality?.eligible).length);
  assert.equal(excludedEvidenceLines.length, analysis.evidence.filter((item) => item.quality?.eligible === false).length);
  assert.match(html, /report-run/);
});
