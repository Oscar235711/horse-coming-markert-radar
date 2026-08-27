import fs from 'node:fs/promises';
import path from 'node:path';

import { analyzeDetails, analyzeWithOptionalLlm } from './radar-analysis.mjs';
import { buildAudienceMap } from './radar-core.mjs';
import { runRadarPipeline } from './radar-pipeline.mjs';
import { writeReportArtifacts } from './radar-report.mjs';

export async function runLightingRadar({ config, adapter, runDir, runId, llmAnalyzer = null }) {
  const collection = await runRadarPipeline({ config, adapter, runDir, runId });
  const rules = analyzeDetails(collection.details, config, { runId: collection.manifest.run_id });
  const analysis = {
    ...(await analyzeWithOptionalLlm(rules, llmAnalyzer)),
    collection_failures: collection.failures,
    research_keywords: {
      anchors: config.keywords?.anchors ?? [],
      expanded: config.keywords?.expanded ?? [],
    },
  };
  const audienceMapSource = analysis.opportunities.length
    ? analysis
    : { ...analysis, opportunities: analysis.candidate_signals ?? [] };
  const audienceMap = buildAudienceMap(audienceMapSource);
  const manifest = {
    ...collection.manifest,
    counts: {
      ...collection.manifest.counts,
      opportunities: analysis.opportunities.length,
      audience_nodes: audienceMap.nodes.length,
      audience_edges: audienceMap.edges.length,
    },
    artifacts: {
      analysis: 'analysis.json',
      evidence: 'evidence.jsonl',
      audience_map: 'audience_map.json',
      report: 'report.html',
      optimization_backlog: 'optimization_backlog.jsonl',
      failures: 'failures.jsonl',
    },
  };
  await writeReportArtifacts({ runDir, analysis, audienceMap, manifest });
  await fs.writeFile(path.join(runDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return { ...collection, analysis, audienceMap, manifest };
}
