export function mergeSearchRows(rows, startDate, endDate) {
  const start = Date.parse(`${startDate}T00:00:00Z`) / 1000;
  const end = Date.parse(`${endDate}T23:59:59Z`) / 1000;
  const merged = new Map();
  for (const row of rows || []) {
    const timestamp = Number(row?.created_utc);
    if (!row?.id || !Number.isFinite(timestamp) || timestamp < start || timestamp > end) continue;
    const query = String(row.source_query || '').trim();
    const prior = merged.get(row.id);
    if (!prior) {
      merged.set(row.id, { ...row, source_queries: query ? [query] : [] });
      continue;
    }
    if (query && !prior.source_queries.includes(query)) prior.source_queries.push(query);
    if (String(row.selftext || '').length > String(prior.selftext || '').length) prior.selftext = row.selftext;
    prior.score = Math.max(Number(prior.score || 0), Number(row.score || 0));
    prior.comments = Math.max(Number(prior.comments || 0), Number(row.comments || 0));
  }
  return [...merged.values()].sort((a, b) => Number(b.created_utc) - Number(a.created_utc));
}
