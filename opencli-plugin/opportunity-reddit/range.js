import { cli, Strategy } from '@jackwener/opencli/registry';
import { mergeRangeRows, selectBalancedRangeRows } from './range-core.mjs';

cli({
  site: 'opportunity-reddit',
  name: 'range',
  access: 'read',
  description: 'Collect a dated subreddit sample with authenticated pagination',
  domain: 'reddit.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'subreddit', type: 'string', required: true, positional: true },
    { name: 'start-date', type: 'string', required: true },
    { name: 'end-date', type: 'string', required: true },
    { name: 'limit', type: 'int', default: 1000 },
  ],
  columns: ['id', 'title', 'subreddit', 'author', 'upvotes', 'comments', 'url', 'created_utc', 'selftext', 'source_surfaces', 'coverage_status'],
  func: async (page, kwargs) => {
    const subreddit = String(kwargs.subreddit || '').replace(/^r\//i, '');
    const startDate = String(kwargs['start-date']);
    const endDate = String(kwargs['end-date']);
    const limit = Math.max(1, Math.min(1000, Number(kwargs.limit || 1000)));
    const daySpan = Math.max(1, Math.ceil((Date.parse(`${endDate}T23:59:59Z`) - Date.parse(`${startDate}T00:00:00Z`)) / 86400000));
    const time = daySpan <= 1 ? 'day' : daySpan <= 7 ? 'week' : daySpan <= 31 ? 'month' : 'year';
    const result = await page.evaluate(async ({ subreddit, startDate, endDate, limit, time }) => {
      const start = Date.parse(`${startDate}T00:00:00Z`) / 1000;
      function map(child, surface) {
        const d = child.data || {};
        return {
          id: d.id,
          title: d.title || '',
          subreddit: d.subreddit || subreddit,
          author: d.author || '[deleted]',
          upvotes: d.score || 0,
          comments: d.num_comments || 0,
          url: `https://www.reddit.com${d.permalink || ''}`,
          created_utc: d.created_utc,
          selftext: d.selftext || '',
          source_surface: surface,
        };
      }
      async function fetchListing(sort, surface, after = '', timeFilter = '') {
        const params = new URLSearchParams({ limit: '100', raw_json: '1' });
        if (after) params.set('after', after);
        if (timeFilter) params.set('t', timeFilter);
        const response = await fetch(`/r/${subreddit}/${sort}.json?${params}`, { credentials: 'include' });
        if (!response.ok) throw new Error(`Reddit ${sort} returned HTTP ${response.status}`);
        const body = await response.json();
        return {
          rows: (body?.data?.children || []).map((child) => map(child, surface)),
          after: body?.data?.after || '',
        };
      }

      const collected = [];
      let after = '';
      let reachedStart = false;
      let exhausted = false;
      while (collected.length < limit) {
        const pageResult = await fetchListing('new', 'new', after);
        if (!pageResult.rows.length) { exhausted = true; break; }
        collected.push(...pageResult.rows);
        const oldest = Math.min(...pageResult.rows.map((row) => Number(row.created_utc || Infinity)));
        if (oldest <= start) { reachedStart = true; break; }
        if (!pageResult.after) { exhausted = true; break; }
        after = pageResult.after;
      }
      for (const [sort, surface] of [['top', 'top'], ['controversial', 'controversial'], ['hot', 'hot']]) {
        const extra = await fetchListing(sort, surface, '', sort === 'hot' ? '' : time);
        collected.push(...extra.rows);
      }
      return { rows: collected, coverageStatus: reachedStart || exhausted ? 'complete' : 'partial' };
    }, { subreddit, startDate, endDate, limit, time });
    return selectBalancedRangeRows(mergeRangeRows(result.rows, startDate, endDate), limit)
      .map((row) => ({ ...row, coverage_status: result.coverageStatus }));
  },
});
