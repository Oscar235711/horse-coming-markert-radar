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
    'codex/automotive-lighting-reddit-radar',
    'git branch --show-current',
    'git rev-parse HEAD',
    'dsv4pro',
    '--profile overnight',
    '--max-runtime-minutes 600',
    '--expand-more false',
    '15 seconds',
    '45 seconds',
    '30 seconds',
    'RADAR_LLM_BASE_URL',
    'RADAR_LLM_API_KEY',
    'RADAR_LLM_MODEL',
    'failure_attempts.jsonl',
    'keyword_cloud.json',
    '禁止 push',
    'PROHIBITED',
  ]) {
    assert.match(text, new RegExp(escapeRegExp(token), 'i'));
  }

  for (const forbidden of ['C:\\Users\\', 'Bearer ', 'sk-', 'token=']) {
    assert.doesNotMatch(text, new RegExp(escapeRegExp(forbidden), 'i'));
  }
});

test('Hermes progress and outbox templates use the fixed reporting fields', async () => {
  const progressText = await fs.readFile(path.join(repoRoot, '.agents', 'PROGRESS.md'), 'utf8');
  const outboxText = await fs.readFile(path.join(repoRoot, '.agents', 'OUTBOX.md'), 'utf8');

  for (const token of ['Asia/Shanghai', '[timestamp]', '[stage]', '[status]', '[details]', 'resume']) {
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
