import test from 'node:test';
import assert from 'node:assert/strict';

import { buildListingUrl, mergeRangeRows, selectBalancedRangeRows } from './range-core.mjs';

test('buildListingUrl carries the reddit after cursor for real pagination', () => {
  assert.equal(
    buildListingUrl('Cummins', 'new', 't3_cursor'),
    '/r/Cummins/new.json?limit=100&raw_json=1&after=t3_cursor',
  );
});

test('balanced selection keeps new coverage plus top, controversial, and hot supplements', () => {
  const rows = [];
  for (let index = 0; index < 20; index += 1) rows.push({ id: `new-${index}`, created_utc: 1000 - index, source_surfaces: ['new'] });
  rows.push({ id: 'top-only', created_utc: 500, source_surfaces: ['top'] });
  rows.push({ id: 'controversial-only', created_utc: 499, source_surfaces: ['controversial'] });
  rows.push({ id: 'hot-only', created_utc: 498, source_surfaces: ['hot'] });

  const selected = selectBalancedRangeRows(rows, 10);

  assert.equal(selected.length, 10);
  assert.ok(selected.some((row) => row.id === 'top-only'));
  assert.ok(selected.some((row) => row.id === 'controversial-only'));
  assert.ok(selected.some((row) => row.id === 'hot-only'));
});

test('balanced selection retains an oldest new row as a date-coverage sentinel', () => {
  const rows = Array.from({ length: 20 }, (_, index) => ({
    id: `new-${index}`,
    created_utc: 1000 - index,
    source_surfaces: ['new'],
  }));
  const selected = selectBalancedRangeRows(rows, 10);
  assert.ok(selected.some((row) => row.id === 'new-19'));
});

test('mergeRangeRows filters exact dates and deduplicates across discovery surfaces', () => {
  const rows = mergeRangeRows([
    { id: 'same', created_utc: Date.parse('2026-03-01T00:00:00Z') / 1000, source_surface: 'new' },
    { id: 'same', created_utc: Date.parse('2026-03-01T00:00:00Z') / 1000, source_surface: 'top' },
    { id: 'old', created_utc: Date.parse('2025-12-31T23:59:59Z') / 1000, source_surface: 'new' },
    { id: 'future', created_utc: Date.parse('2026-04-01T00:00:00Z') / 1000, source_surface: 'new' },
  ], '2026-01-01', '2026-03-31');

  assert.deepEqual(rows.map((row) => row.id), ['same']);
  assert.deepEqual(rows[0].source_surfaces, ['new', 'top']);
});
