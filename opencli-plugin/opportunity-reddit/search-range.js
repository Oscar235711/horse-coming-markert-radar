import { cli, Strategy } from '@jackwener/opencli/registry';
import { mergeSearchRows } from './search-range-core.mjs';

cli({
  site: 'opportunity-reddit',
  name: 'search-range',
  access: 'read',
  description: 'Search Reddit globally through a selected date window with authenticated pagination',
  domain: 'reddit.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'query', type: 'string', required: true, positional: true },
    { name: 'start-date', type: 'string', required: true },
    { name: 'end-date', type: 'string', required: true },
    { name: 'max-pages', type: 'int', default: 0 },
  ],
  columns: ['id', 'title', 'subreddit', 'author', 'score', 'comments', 'url', 'created_utc', 'selftext', 'source_queries', 'coverage_status'],
  func: async (page, kwargs) => {
    const query = String(kwargs.query || '').trim();
    const startDate = String(kwargs['start-date']);
    const endDate = String(kwargs['end-date']);
    const maxPages = Math.max(0, Number(kwargs['max-pages'] || 0));
    const result = await page.evaluate(async ({ query, startDate, maxPages }) => {
      const start = Date.parse(`${startDate}T00:00:00Z`) / 1000;
      const rows = [];
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      async function fetchWithBackoff(url) {
        let last = null;
        // A 429 is a provider-level pause, not a reason to hold the browser
        // lease for several minutes.  Return a retryable error quickly; the
        // Python run checkpoint lets the next resume try again later.
        for (let attempt = 0; attempt < 2; attempt += 1) {
          const response = await fetch(url, { credentials: 'include' });
          last = response;
          if (response.status !== 429) return response;
          const retryAfter = Number(response.headers.get('retry-after') || 0);
          if (attempt === 0) await wait(Math.min(15, retryAfter > 0 ? retryAfter : 5) * 1000);
        }
        return last;
      }
      const seenAfter = new Set();
      let after = '';
      let reachedStart = false;
      let exhausted = false;
      let pages = 0;
      while (!maxPages || pages < maxPages) {
        const params = new URLSearchParams({ q: query, sort: 'new', t: 'year', type: 'link', limit: '100', raw_json: '1' });
        if (after) params.set('after', after);
        const response = await fetchWithBackoff(`/search.json?${params}`);
        if (!response.ok) throw new Error(`Reddit search returned HTTP ${response.status}`);
        const body = await response.json();
        const children = body?.data?.children || [];
        if (!children.length) { exhausted = true; break; }
        for (const child of children) {
          const d = child?.data || {};
          rows.push({
            id: d.id,
            title: d.title || '',
            subreddit: d.subreddit || '',
            author: d.author || '[deleted]',
            score: d.score || 0,
            comments: d.num_comments || 0,
            url: `https://www.reddit.com${d.permalink || ''}`,
            created_utc: d.created_utc,
            selftext: d.selftext || '',
            source_query: query,
          });
        }
        pages += 1;
        const oldest = Math.min(...children.map((child) => Number(child?.data?.created_utc || Infinity)));
        if (oldest <= start) { reachedStart = true; break; }
        const next = body?.data?.after || '';
        if (!next) { exhausted = true; break; }
        if (seenAfter.has(next)) { exhausted = true; break; }
        seenAfter.add(next);
        after = next;
      }
      return { rows, coverageStatus: reachedStart || exhausted ? 'complete' : 'partial', pages };
    }, { query, startDate, maxPages });
    return mergeSearchRows(result.rows, startDate, endDate).map((row) => ({
      ...row,
      coverage_status: result.coverageStatus,
      pages_scanned: result.pages,
    }));
  },
});
