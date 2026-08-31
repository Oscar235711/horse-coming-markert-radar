export function flattenCommentTree(children, postId, maxDepth = 3, repliesPerParent = 20) {
  const result = [];
  function visit(nodes, depth, parentId = '') {
    if (!Array.isArray(nodes) || depth > maxDepth) return;
    const comments = nodes
      .filter((node) => node?.kind === 't1' && node?.data?.id)
      .sort((a, b) => Number(b.data?.score || 0) - Number(a.data?.score || 0))
      .slice(0, repliesPerParent);
    for (const node of comments) {
      const data = node.data;
      result.push({
        id: String(data.id),
        parent_id: String(data.parent_id || parentId),
        depth,
        author: String(data.author || '[deleted]'),
        score: Number(data.score || 0),
        body: String(data.body || ''),
        url: data.permalink
          ? `https://www.reddit.com${data.permalink}`
          : `https://www.reddit.com/r/_/comments/${postId}/_/${data.id}/`,
      });
      const replies = data.replies?.data?.children;
      visit(replies, depth + 1, `t1_${data.id}`);
    }
  }
  visit(children, 1);
  return result;
}

