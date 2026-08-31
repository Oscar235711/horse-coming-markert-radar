export function buildListingUrl(subreddit, sort, after = '', time = '') {
  const clean = String(subreddit).replace(/^r\//i, '');
  const params = new URLSearchParams({ limit: '100', raw_json: '1' });
  if (after) params.set('after', after);
  if (time && (sort === 'top' || sort === 'controversial')) params.set('t', time);
  return `/r/${clean}/${sort}.json?${params.toString()}`;
}

export function mergeRangeRows(rows, startDate, endDate) {
  const start = Date.parse(`${startDate}T00:00:00Z`) / 1000;
  const end = Date.parse(`${endDate}T23:59:59Z`) / 1000;
  const merged = new Map();
  for (const row of rows) {
    const timestamp = Number(row?.created_utc);
    if (!row?.id || !Number.isFinite(timestamp) || timestamp < start || timestamp > end) continue;
    const source = String(row.source_surface || 'range');
    const prior = merged.get(row.id);
    if (!prior) {
      merged.set(row.id, { ...row, source_surfaces: [source] });
      continue;
    }
    if (!prior.source_surfaces.includes(source)) prior.source_surfaces.push(source);
    if (String(row.selftext || '').length > String(prior.selftext || '').length) {
      prior.selftext = row.selftext;
    }
    prior.upvotes = Math.max(Number(prior.upvotes || 0), Number(row.upvotes || 0));
    prior.comments = Math.max(Number(prior.comments || 0), Number(row.comments || 0));
  }
  return [...merged.values()].sort((a, b) => Number(b.created_utc) - Number(a.created_utc));
}

export function selectBalancedRangeRows(rows, limit) {
  const maximum = Math.max(1, Number(limit || 1));
  const chosen = new Map();
  const add = (row) => {
    if (row?.id && chosen.size < maximum) chosen.set(row.id, row);
  };
  // Reserve one slot for the oldest-row sentinel (and leave room for the
  // three supplement surfaces) before filling any remaining tail rows.
  const newQuota = maximum > 1 ? Math.max(1, Math.floor(maximum * 0.7) - 1) : 1;
  const newRows = rows.filter((row) => row.source_surfaces?.includes('new'));
  newRows.slice(0, newQuota).forEach(add);
  // Keep an oldest ``new`` row as a coverage sentinel.  Without this, the
  // balanced quota could retain only recent posts even though pagination
  // reached the requested start date, making the report look complete while
  // the normalized sample was not date-complete.
  if (newRows.length > 1) add(newRows[newRows.length - 1]);
  const surfaces = ['top', 'controversial', 'hot'];
  const buckets = surfaces.map((surface) => rows.filter((row) => row.source_surfaces?.includes(surface)));
  const indexes = buckets.map(() => 0);
  while (chosen.size < maximum) {
    let progressed = false;
    for (let index = 0; index < buckets.length && chosen.size < maximum; index += 1) {
      while (indexes[index] < buckets[index].length && chosen.has(buckets[index][indexes[index]].id)) indexes[index] += 1;
      if (indexes[index] < buckets[index].length) {
        add(buckets[index][indexes[index]]);
        indexes[index] += 1;
        progressed = true;
      }
    }
    if (!progressed) break;
  }
  rows.forEach(add);
  return [...chosen.values()];
}
