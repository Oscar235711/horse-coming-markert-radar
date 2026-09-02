import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeSearchRows } from './search-range-core.mjs';

test('mergeSearchRows filters exact dates and merges source queries', () => {
  const rows = [
    { id: 'a', created_utc: Date.parse('2026-06-01T00:00:00Z') / 1000, source_query: 'egr cooler' },
    { id: 'a', created_utc: Date.parse('2026-06-01T00:00:00Z') / 1000, source_query: 'egr failure', selftext: 'longer body' },
    { id: 'old', created_utc: Date.parse('2024-01-01T00:00:00Z') / 1000, source_query: 'egr cooler' },
  ];

  const merged = mergeSearchRows(rows, '2025-09-02', '2026-09-01');

  assert.equal(merged.length, 1);
  assert.deepEqual(merged[0].source_queries, ['egr cooler', 'egr failure']);
  assert.equal(merged[0].selftext, 'longer body');
});
