import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import vm from 'node:vm';
import { renderReportHtml } from '../src/radar-report.mjs';
import { buildKeywordCloud } from '../src/keyword-cloud.mjs';

const input = process.argv[2];
if (!input) throw new Error('Usage: node scripts/render-existing-report.mjs <run-directory>');
const runDir = path.resolve(input);
const files = ['analysis.json', 'audience_map.json', 'keyword_cloud.json', 'manifest.json'];
const before = await Promise.all(files.map(file => fs.readFile(path.join(runDir, file), 'utf8')));
const [analysis, audienceMap, previousKeywordCloud, manifest] = before.map(text => JSON.parse(text));
const config = JSON.parse(await fs.readFile(path.join(runDir, 'config.snapshot.json'), 'utf8'));
const candidates = JSON.parse(await fs.readFile(path.join(runDir, 'keyword_candidates.json'), 'utf8'));
const keywordCloud = buildKeywordCloud(candidates.candidates ?? [], analysis.evidence ?? [], {
  runId: manifest.run_id,
  scope: config.market,
  displayThresholds: config.keywords?.display_thresholds ?? {
    min_unique_users: 2,
    min_threads: 2,
    min_communities: 1,
    min_thread_share: 0.01,
    total_threads: manifest.counts?.details ?? 0,
  },
});
manifest.counts = { ...(manifest.counts ?? {}), keyword_cloud_terms: keywordCloud.terms.length };
await fs.writeFile(path.join(runDir, 'keyword_cloud.json'), `${JSON.stringify(keywordCloud, null, 2)}\n`, 'utf8');
await fs.writeFile(path.join(runDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
const html = renderReportHtml({ analysis, audienceMap, keywordCloud, manifest });
for (const [, script] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(script);
if (/<script[^>]+src=|<link[^>]+href=|fetch\(/i.test(html)) throw new Error('Report must be self-contained');
const target = path.join(runDir, 'report.html');
const backup = path.join(runDir, 'report.before-visual-refresh.html');
try { await fs.copyFile(target, backup, constants.COPYFILE_EXCL); }
catch (error) { if (!['EEXIST', 'ENOENT'].includes(error.code)) throw error; }
await fs.writeFile(target, html, 'utf8');
const after = await Promise.all(files.map(file => fs.readFile(path.join(runDir, file), 'utf8')));
if (before[0] !== after[0] || before[1] !== after[1]) throw new Error('Analysis or Audience Map changed during render');
console.log(JSON.stringify({ report: target, backup, opportunities: analysis.opportunities?.length ?? 0,
  terms: keywordCloud.terms?.length ?? 0, nodes: audienceMap.nodes?.length ?? 0,
  analysis_and_map_unchanged: true,
  keyword_cloud_regenerated: true,
  source_hashes: Object.fromEntries(files.map((file, index) => [file, createHash('sha256').update(before[index]).digest('hex')])) }, null, 2));
