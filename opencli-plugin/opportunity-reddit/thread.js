import { cli, Strategy } from '@jackwener/opencli/registry';

cli({
  site: 'opportunity-reddit',
  name: 'read',
  access: 'read',
  description: 'Read a Reddit thread while preserving comment IDs, nesting, and permalinks',
  domain: 'reddit.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'post-id', type: 'string', required: true, positional: true },
    { name: 'sort', type: 'string', default: 'best' },
    { name: 'limit', type: 'int', default: 100 },
    { name: 'depth', type: 'int', default: 3 },
    { name: 'replies', type: 'int', default: 20 },
    { name: 'expand-rounds', type: 'int', default: 5 },
    { name: 'max-length', type: 'int', default: 5000 },
  ],
  columns: ['id', 'parent_id', 'depth', 'author', 'score', 'body', 'url'],
  func: async (page, kwargs) => {
    const postId = String(kwargs['post-id'] || '').replace(/^t3_/, '');
    const sort = String(kwargs.sort || 'best');
    const limit = Math.max(1, Math.min(100, Number(kwargs.limit || 100)));
    const maxDepth = Math.max(1, Math.min(3, Number(kwargs.depth || 3)));
    const repliesPerParent = Math.max(1, Math.min(20, Number(kwargs.replies || 20)));
    const expandRounds = Math.max(0, Math.min(5, Number(kwargs['expand-rounds'] || 5)));
    const maxLength = Math.max(100, Math.min(10000, Number(kwargs['max-length'] || 5000)));
    return page.evaluate(async ({ postId, sort, limit, maxDepth, repliesPerParent, expandRounds, maxLength }) => {
      const response = await fetch(`/comments/${postId}.json?sort=${encodeURIComponent(sort)}&limit=${limit}&depth=${maxDepth}&raw_json=1`, { credentials: 'include' });
      if (!response.ok) throw new Error(`Reddit thread returned HTTP ${response.status}`);
      const document = await response.json();
      const children = document?.[1]?.data?.children || [];
      const rows = [];
      const moreIds = [];
      function visit(nodes, depth, parentId = '') {
        if (!Array.isArray(nodes) || depth > maxDepth) return;
        const comments = nodes.filter((node) => {
          if (node?.kind === 'more') moreIds.push(...(node.data?.children || []));
          return node?.kind === 't1' && node?.data?.id;
        }).sort((a, b) => Number(b.data?.score || 0) - Number(a.data?.score || 0)).slice(0, depth === 1 ? limit : repliesPerParent);
        for (const node of comments) {
          const d = node.data;
          rows.push({ id: String(d.id), parent_id: String(d.parent_id || parentId), depth, author: String(d.author || '[deleted]'), score: Number(d.score || 0), body: String(d.body || '').slice(0, maxLength), url: d.permalink ? `https://www.reddit.com${d.permalink}` : `https://www.reddit.com/r/_/comments/${postId}/_/${d.id}/` });
          visit(d.replies?.data?.children, depth + 1, `t1_${d.id}`);
        }
      }
      visit(children, 1);
      const seen = new Set(rows.map((row) => row.id));
      let pending = [...new Set(moreIds)].filter((id) => !seen.has(id));
      for (let round = 0; round < expandRounds && pending.length && rows.length < limit * repliesPerParent; round += 1) {
        const batch = pending.splice(0, 100);
        const params = new URLSearchParams({ api_type: 'json', link_id: `t3_${postId}`, children: batch.join(','), sort, raw_json: '1' });
        const moreResponse = await fetch(`/api/morechildren.json?${params}`, { credentials: 'include' });
        if (!moreResponse.ok) break;
        const moreDocument = await moreResponse.json();
        const things = moreDocument?.json?.data?.things || [];
        for (const thing of things) {
          if (thing?.kind !== 't1' || !thing?.data?.id || seen.has(thing.data.id)) continue;
          const d = thing.data; seen.add(d.id);
          rows.push({ id: String(d.id), parent_id: String(d.parent_id || ''), depth: 1, author: String(d.author || '[deleted]'), score: Number(d.score || 0), body: String(d.body || '').slice(0, maxLength), url: d.permalink ? `https://www.reddit.com${d.permalink}` : `https://www.reddit.com/r/_/comments/${postId}/_/${d.id}/` });
        }
      }
      return rows;
    }, { postId, sort, limit, maxDepth, repliesPerParent, expandRounds, maxLength });
  },
});
