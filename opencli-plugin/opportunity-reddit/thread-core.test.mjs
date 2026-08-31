import test from 'node:test';
import assert from 'node:assert/strict';

import { flattenCommentTree } from './thread-core.mjs';

test('comment tree keeps exact ids, authors, levels, and reddit permalinks', () => {
  const rows = flattenCommentTree([{ kind: 't1', data: {
    id: 'c1', parent_id: 't3_post', author: 'owner', score: 4, body: 'top',
    permalink: '/r/Cummins/comments/post/title/c1/', replies: { data: { children: [
      { kind: 't1', data: { id: 'c2', parent_id: 't1_c1', author: 'reply', score: 2, body: 'nested', permalink: '/r/Cummins/comments/post/title/c1/c2/' } },
    ] } },
  } }], 'post', 3, 20);

  assert.deepEqual(rows.map((row) => [row.id, row.depth, row.author]), [['c1', 1, 'owner'], ['c2', 2, 'reply']]);
  assert.equal(rows[1].url, 'https://www.reddit.com/r/Cummins/comments/post/title/c1/c2/');
});

