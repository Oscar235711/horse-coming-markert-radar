import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('Hermes handoff is executable, bilingual, and forbids repository mutation', async () => {
  const handoffPath = path.join(repoRoot, '.agents', 'HERMES_HANDOFF_V1.2.md');
  const text = await fs.readFile(handoffPath, 'utf8');

  for (const token of [
    'https://github.com/Oscar235711/horse-coming-markert-radar.git',
    'codex/automotive-lighting-reddit-radar',
    'git remote get-url origin',
    'git branch --show-current',
    'git rev-parse HEAD',
    'git status --short',
    '.\\scripts\\radar.ps1 run',
    'node .\\scripts\\run-radar.mjs',
    'dsv4pro',
    '--profile overnight',
    '--transport opencli',
    '--max-runtime-minutes 600',
    '--expand-more false',
    'at most `3` total attempts',
    'at most `2` total attempts',
    '15 seconds',
    '45 seconds',
    '30 seconds',
    'Retry-After',
    '120 seconds',
    'RADAR_LLM_BASE_URL',
    'RADAR_LLM_API_KEY',
    'RADAR_LLM_MODEL',
    'config.snapshot.json',
    'manifest.json',
    'report.html',
    'runtime-status.json',
    'run_id` 必须是单层目录名',
    'runtime-status.status',
    'failure_attempts.jsonl',
    'keyword_cloud.json',
    'node --test \"tests/*.test.mjs\"',
    '.\\tests\\verify-lighting-interface.ps1',
    'git diff --check',
    'Wrong branch or wrong exact commit',
    'One unavailable post',
    'DSV4Pro timeout',
    '禁止 push',
    'PROHIBITED',
  ]) {
    assert.match(text, new RegExp(escapeRegExp(token), 'i'));
  }

  for (const forbidden of ['C:\\Users\\', 'Bearer ', 'sk-', 'token=', 'git push', 'git tag', 'git merge']) {
    if (forbidden.startsWith('git ')) continue;
    assert.doesNotMatch(text, new RegExp(escapeRegExp(forbidden), 'i'));
  }

  assert.match(text, /PROHIBITED:[\s\S]*git push[\s\S]*git tag[\s\S]*git merge/i);
  assert.match(text, /`?timed_out`? only when the wall-clock ceiling aborts the run/i);
});

test('Task 9 script contracts keep OpenCLI detail expansion disabled and pass the runtime ceiling through', async () => {
  const fetchDetailsText = await fs.readFile(path.join(repoRoot, 'scripts', 'fetch-details.ps1'), 'utf8');
  const radarScriptText = await fs.readFile(path.join(repoRoot, 'scripts', 'radar.ps1'), 'utf8');
  const runRadarText = await fs.readFile(path.join(repoRoot, 'scripts', 'run-radar.mjs'), 'utf8');

  assert.match(fetchDetailsText, /--expand-more false/i);
  assert.doesNotMatch(fetchDetailsText, /--expand-more true/i);
  assert.match(radarScriptText, /--max-runtime-minutes", "\$MaxRuntimeMinutes"/i);
  assert.match(radarScriptText, /RADAR_MAX_RUNTIME_MINUTES = "\$MaxRuntimeMinutes"/i);
  assert.match(radarScriptText, /ValidatePattern\('\^\(\?!\.\*\(\?:\[\\\\\/\]\|\\\\\.\\\\\.\)\)\[A-Za-z0-9\._-\]\+\$'\)/i);
  assert.match(runRadarText, /no path separators or '\.\.'/i);
  assert.match(runRadarText, /Successful runs mirror manifest\.status; only the wall-clock ceiling writes timed_out/i);
});

test('Hermes progress and outbox templates use the fixed reporting fields', async () => {
  const progressText = await fs.readFile(path.join(repoRoot, '.agents', 'PROGRESS.md'), 'utf8');
  const outboxText = await fs.readFile(path.join(repoRoot, '.agents', 'OUTBOX.md'), 'utf8');

  for (const token of ['Asia/Shanghai', '[timestamp]', '[stage]', '[status]', '[details]', 'resume', 'YYYY-MM-DD HH:mm CST', 'exact branch and exact commit']) {
    assert.match(progressText, new RegExp(escapeRegExp(token), 'i'));
  }

  for (const token of [
    'run status',
    'counts by stage',
    'evidence-quality distribution',
    'excluded reasons',
    'author-deep-dive counts',
    'keyword candidates',
    'second-round additions',
    'opportunities by type',
    'persona eligibility',
    'artifact paths',
    'unresolved failures',
    'recommended human decisions',
    '运行状态',
    '各阶段数量',
    '证据质量分布',
    '未解决失败',
  ]) {
    assert.match(outboxText, new RegExp(escapeRegExp(token), 'i'));
  }
});

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
