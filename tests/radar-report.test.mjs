import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildAudienceMap } from '../src/radar-core.mjs';
import { renderReportHtml, writeReportArtifacts } from '../src/radar-report.mjs';
import { createKeywordCloudInputs, createReportFixture } from './fixtures/task-6-report.fixture.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
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
  assert.match(html, /为什么还没有被很好解决/);
  assert.match(html, /车型协议差异大/);
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
  assert.deepEqual(Object.keys(savedOpportunities).sort(), [
    'candidate_signals',
    'competitors',
    'generated_at',
    'opportunities',
    'pain_points',
    'run_id',
    'schema_version',
  ]);
  assert.equal(savedOpportunities.run_id, 'report-run');
  assert.equal(savedOpportunities.opportunities.length, analysis.opportunities.length);
  assert.equal(savedOpportunities.opportunities[0].why_not_done.text, analysis.opportunities[0].why_not_done.text);
  assert.equal(savedPersonas.persona_status, analysis.personas.persona_status);
  assert.equal(qualifiedEvidenceLines.length, analysis.evidence.filter((item) => item.quality?.eligible).length);
  assert.equal(excludedEvidenceLines.length, analysis.evidence.filter((item) => item.quality?.eligible === false).length);
  assert.match(html, /report-run/);
});

test('generated opportunities artifact normalizes sparse threshold checks and still satisfies the artifact schema', async (t) => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'radar-threshold-artifact-'));
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

  const savedOpportunities = JSON.parse(await fs.readFile(paths.opportunities, 'utf8'));
  const candidate = savedOpportunities.candidate_signals[0];
  assert.deepEqual(candidate.threshold_check, {
    passed: false,
    failures: ['unique_users'],
    checks: {
      qualified_evidence: true,
      unique_users: false,
      communities: true,
      direct_experience: true,
      contexts: true,
      core_contexts: true,
      score: true,
      concrete_product: true,
      existing_market: true,
      entry_gap: true,
      solution_validation: true,
    },
    required: {
      unique_users: 5,
      communities: 0,
      direct_experience: 0,
      contexts: 2,
      core_contexts: 0,
      score: 50,
    },
  });

  const errors = await validateAgainstSchemaFile('opportunity-artifact.schema.json', savedOpportunities);
  assert.deepEqual(errors, []);
});

async function validateAgainstSchemaFile(name, value) {
  const schemaCache = new Map();
  const schemaNames = ['opportunity-artifact.schema.json', 'opportunities.schema.json'];
  for (const schemaName of schemaNames) {
    schemaCache.set(schemaName, JSON.parse(await fs.readFile(path.join(repoRoot, 'schemas', schemaName), 'utf8')));
  }
  return validateWithSchema(value, schemaCache.get(name), {
    path: '$',
    baseName: name,
    schemaCache,
  });
}

function validateWithSchema(value, schemaNode, state) {
  if (!schemaNode) return [`${state.path}: missing schema node`];
  if (schemaNode.$ref) {
    const resolved = resolveSchemaRef(schemaNode.$ref, state.baseName, state.schemaCache);
    return validateWithSchema(value, resolved.schema, {
      ...state,
      baseName: resolved.baseName,
    });
  }

  const errors = [];
  if (schemaNode.enum && !schemaNode.enum.some((item) => Object.is(item, value))) {
    errors.push(`${state.path}: expected one of ${schemaNode.enum.join(', ')}`);
    return errors;
  }

  if (schemaNode.type && !matchesType(value, schemaNode.type)) {
    const expected = Array.isArray(schemaNode.type) ? schemaNode.type.join('|') : schemaNode.type;
    errors.push(`${state.path}: expected ${expected}`);
    return errors;
  }

  if (schemaNode.type === 'object') {
    const required = schemaNode.required ?? [];
    for (const key of required) {
      if (!(key in value)) errors.push(`${state.path}.${key}: missing required property`);
    }

    if (schemaNode.additionalProperties === false) {
      const knownKeys = new Set(Object.keys(schemaNode.properties ?? {}));
      for (const key of Object.keys(value)) {
        if (!knownKeys.has(key)) errors.push(`${state.path}.${key}: unexpected property`);
      }
    }

    for (const [key, propertySchema] of Object.entries(schemaNode.properties ?? {})) {
      if (key in value) {
        errors.push(...validateWithSchema(value[key], propertySchema, {
          ...state,
          path: `${state.path}.${key}`,
        }));
      }
    }
  }

  if (schemaNode.type === 'array') {
    for (const [index, item] of value.entries()) {
      errors.push(...validateWithSchema(item, schemaNode.items ?? {}, {
        ...state,
        path: `${state.path}[${index}]`,
      }));
    }
  }

  if (schemaNode.type === 'string') {
    if (schemaNode.minLength != null && value.length < schemaNode.minLength) {
      errors.push(`${state.path}: expected minLength ${schemaNode.minLength}`);
    }
    if (schemaNode.format === 'date-time' && Number.isNaN(Date.parse(value))) {
      errors.push(`${state.path}: expected RFC3339 date-time`);
    }
  }

  if (schemaNode.type === 'integer') {
    if (schemaNode.minimum != null && value < schemaNode.minimum) {
      errors.push(`${state.path}: expected minimum ${schemaNode.minimum}`);
    }
    if (schemaNode.maximum != null && value > schemaNode.maximum) {
      errors.push(`${state.path}: expected maximum ${schemaNode.maximum}`);
    }
  }

  return errors;
}

function resolveSchemaRef(ref, baseName, schemaCache) {
  const [targetNameRaw, fragment = ''] = ref.split('#');
  const targetName = targetNameRaw ? path.basename(targetNameRaw) : baseName;
  const targetSchema = schemaCache.get(targetName);
  let schema = targetSchema;
  if (fragment) {
    const segments = fragment.replace(/^\//, '').split('/').filter(Boolean).map(unescapeJsonPointer);
    for (const segment of segments) {
      schema = schema?.[segment];
    }
  }
  return { schema, baseName: targetName };
}

function unescapeJsonPointer(segment) {
  return segment.replaceAll('~1', '/').replaceAll('~0', '~');
}

function matchesType(value, expected) {
  const expectedTypes = Array.isArray(expected) ? expected : [expected];
  return expectedTypes.some((type) => {
    if (type === 'array') return Array.isArray(value);
    if (type === 'integer') return Number.isInteger(value);
    if (type === 'null') return value === null;
    if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value);
    return typeof value === type;
  });
}
