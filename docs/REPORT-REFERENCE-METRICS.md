# Report references and hover behavior

Accepted scope (2026-08-31): hover shows direct neighbors; seller reference
products start collapsed and show product name, discussion, and top keyword.
No official/Amazon lookup, price enrichment, persona-threshold change, or new
keyword-discovery feature is included in this change.

## Audience Map

Hover (or keyboard focus) masks unrelated nodes and edges in the current view.
The hovered node and its direct neighbors keep their original positions.
Pointer leave restores the view; click still drills down. Search and category
filters remain in effect. Touch users retain click-to-drill-down behavior.

## Product identity

References derive from eligible evidence already linked to each opportunity.
Legacy post-title placeholders are discarded. Literal product names supplied
by an upstream extractor are retained; brand aliases and explicitly mentioned
series/socket variants can also be recognized. Unknown series are labelled
`型号未识别`, not assigned a guessed SKU. The built-in brand/series recognizer is
bounded and may miss other names. Records with no identified product are
reported as unresolved instead of becoming named product cards.

Within one record, repeated mentions count once for a product. Records with
duplicate IDs or identical normalized text from the same author and thread are
deduplicated. Different models remain separate; generic brand references are
not distributed across every model. Clauses explicitly discussing a different
lighting category or floor mats/seat covers are excluded from that reference.

## Discussion metric

`discussion.score = post_count + sum(comment_weight)`

For a comment with a numeric evidence quality score, weight is the score / 100,
clamped to [0, 1]. If the numeric score is absent, high/medium/low quality bands
use 1/0.6/0.25; otherwise 0. Only eligible, non-hard-excluded product mentions
count. Votes and total thread comment counts do not become quality scores.
The displayed raw frequency is the number of distinct mentioning records,
with a post/comment breakdown. Discussion is not sentiment, sales, popularity
outside the collected sample, or market size.

## Highest associated keyword

The pool is the report's cloud terms plus its configured/explored research
keywords, without modifying those keywords. Product names themselves are
excluded. For each keyword:

`weighted Dice = 2 * shared_weight / (product_weight + keyword_weight)`

Product weight uses its eligible mentions within the opportunity; keyword
weight uses eligible corpus records. Shared weight uses the same weights, but
requires the keyword in the product's identified clause (or record for supplied
explicit names). Ranking prefers repeated cooccurrences when any exist, then
the highest Dice, cooccurrence count, and a deterministic lexical tie-break.
Single-observation results are labelled; absent cooccurrence is `缺失数据`.
The percentage is an association index, not confidence or a probability.

The report shows the formula and representative evidence links. New runs save
derived fields to analysis and opportunity artifacts; existing reports can be
refreshed with `node scripts/render-existing-report.mjs <run-directory>` while
preserving their original analysis and map files.
