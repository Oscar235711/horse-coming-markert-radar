import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('GitHub Actions supports manual and scheduled public-JSON runs with artifacts', async () => {
  const workflow = await fs.readFile(path.join(repoRoot, '.github', 'workflows', 'reddit-lighting-radar.yml'), 'utf8');

  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /schedule:/);
  assert.match(workflow, /--transport public-json/);
  assert.match(workflow, /actions\/upload-artifact@/);
  assert.match(workflow, /RADAR_LLM_API_KEY: \$\{\{ secrets\.RADAR_LLM_API_KEY \}\}/);
  assert.match(workflow, /permissions:\s*\n\s*contents: read/);
  assert.doesNotMatch(workflow, /git push/);
});
