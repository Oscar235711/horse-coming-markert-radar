import { cli, Strategy } from '@jackwener/opencli/registry';

cli({
  site: 'opportunity-reddit',
  name: 'batch-read',
  access: 'read',
  description: 'Read complete comment trees for a small batch of Reddit post IDs',
  domain: 'reddit.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'post-ids', type: 'string', required: true, positional: true },
    { name: 'max-length', type: 'int', default: 5000 },
  ],
  columns: ['post_id', 'comments', 'status', 'error'],
  func: async (page, kwargs) => {
    const postIds = [...new Set(String(kwargs['post-ids'] || '').split(',').map((id) => id.trim().replace(/^t3_/, '')).filter(Boolean))];
    const maxLength = Math.max(100, Math.min(10000, Number(kwargs['max-length'] || 5000)));
    return page.evaluate(async ({ postIds, maxLength }) => {
      const results = [];
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      async function fetchWithBackoff(url) {
        let last = null;
        // Fail fast on rate limiting so a web task can report the checkpoint
        // and remain responsive instead of waiting through six backoffs.
        for (let attempt = 0; attempt < 2; attempt += 1) {
          const response = await fetch(url, { credentials: 'include' });
          last = response;
          if (response.status !== 429) return response;
          const retryAfter = Number(response.headers.get('retry-after') || 0);
          if (attempt === 0) await wait(Math.min(15, retryAfter > 0 ? retryAfter : 5) * 1000);
        }
        return last;
      }
      for (let index = 0; index < postIds.length; index += 1) {
        const postId = postIds[index];
        try {
          const response = await fetchWithBackoff(`/comments/${postId}.json?sort=best&limit=500&depth=20&raw_json=1`);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const document = await response.json();
          const rows = [];
          const moreIds = [];
          const seen = new Set();
          function visit(nodes, depth) {
            if (!Array.isArray(nodes) || depth > 20) return;
            for (const node of nodes) {
              if (node?.kind === 'more') {
                moreIds.push(...(node.data?.children || []));
                continue;
              }
              if (node?.kind !== 't1' || !node?.data?.id || seen.has(node.data.id)) continue;
              const d = node.data; seen.add(d.id);
              rows.push({ id: String(d.id), parent_id: String(d.parent_id || ''), depth, author: String(d.author || '[deleted]'), score: Number(d.score || 0), body: String(d.body || '').slice(0, maxLength), url: d.permalink ? `https://www.reddit.com${d.permalink}` : `https://www.reddit.com/r/_/comments/${postId}/_/${d.id}/` });
              visit(d.replies?.data?.children, depth + 1);
            }
          }
          visit(document?.[1]?.data?.children || [], 1);
          const pending = [...new Set(moreIds)].filter((id) => !seen.has(id));
          while (pending.length) {
            const batch = pending.splice(0, 100);
            const params = new URLSearchParams({ api_type: 'json', link_id: `t3_${postId}`, children: batch.join(','), sort: 'best', raw_json: '1' });
            const moreResponse = await fetchWithBackoff(`/api/morechildren.json?${params}`);
            if (!moreResponse.ok) break;
            const moreDocument = await moreResponse.json();
            for (const thing of moreDocument?.json?.data?.things || []) {
              if (thing?.kind === 'more') {
                pending.push(...(thing.data?.children || []).filter((id) => !seen.has(id)));
                continue;
              }
              if (thing?.kind !== 't1' || !thing?.data?.id || seen.has(thing.data.id)) continue;
              const d = thing.data; seen.add(d.id);
              rows.push({ id: String(d.id), parent_id: String(d.parent_id || ''), depth: 1, author: String(d.author || '[deleted]'), score: Number(d.score || 0), body: String(d.body || '').slice(0, maxLength), url: d.permalink ? `https://www.reddit.com${d.permalink}` : `https://www.reddit.com/r/_/comments/${postId}/_/${d.id}/` });
            }
          }
          results.push({ post_id: postId, comments: rows, status: 'success', error: '' });
        } catch (error) {
          results.push({ post_id: postId, comments: [], status: 'failed', error: String(error?.message || error) });
        }
        if (index + 1 < postIds.length) await wait(1000);
      }
      return results;
    }, { postIds, maxLength });
  },
});
