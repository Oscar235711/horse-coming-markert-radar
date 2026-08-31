# Offline word cloud and Audience Map implementation

User approved the design on 2026-08-30. Execute in the current isolated lighting worktree; no further design gate, branch merge, push, or new collection is needed.

Goal: render weighted keywords as a densely packed, rotatable Canvas cloud and adapt the community-first interaction from `feature/community-radar` at `e461567` to the existing product/community data.

## Scope and data contract

- Keep `analysis.json`, `audience_map.json`, and `keyword_cloud.json` unchanged. Re-render the existing three-opportunity run from these saved inputs.
- Preserve product/community bipartite semantics, opportunity scores, evidence links, and unknown-market/insufficient-persona warnings.
- Inline all styles and browser code; no network, CDN, model calls, or runtime dependencies.
- Keep the previous report as a backup before regenerating the current report.

## Implementation

- [x] Add `src/report-visuals.mjs`: pure graph filtering/neighborhood selection and deterministic glyph-mask word packing; browser initialization for both views.
- [x] Adapt `src/radar-report.mjs`: wide explorer panels, community list, graph detail drawer, weighted Canvas, filters, accessible keyword list, and evidence drawers. Inline the new module using function serialization.
- [x] Verify graph search preserves evidence-linked neighbors, community drill-down scopes evidence, and reset restores the global view. Verify packing keeps all placed glyphs within bounds without overlapping masks; long labels and empty results remain usable.
- [x] Re-render `.local/runs/formal-us-lighting-20260829-r3/report.html` from saved JSON, leaving the source JSON byte-identical and backing up the old HTML.
- [x] Run `node --test tests/report-visuals.test.mjs tests/radar-report.test.mjs`, then `node --test tests/*.test.mjs`; exercise filters, search, hover, click, close, reset, and back navigation in a local DOM/native-Canvas harness.
- [ ] Actual browser visual acceptance: Browser Use explicitly blocked `file://` navigation. No alternate browser or localhost workaround was attempted. Static Canvas/SVG rendering was inspected instead; full-page layout and responsive behavior still need manual browser review.

## Acceptance

Cloud: real word packing instead of chips, unequal font sizes only when weights differ, restrained category colors, mixed 0/90 degree rotation, hover values and click-to-evidence, no silent omission (show placed/filtered totals and an accessible full list).

Map: global community overview, optional all-relations view, community-to-product drill-down, product-to-community reverse lookup, searchable lists, selected-node detail drawer, back/reset navigation. Hollow communities remain sized by linked concepts, solid products by opportunity score; neither implies population or market size.

Report: the same three formal opportunities and all existing report tabs remain available. Narrow-screen drawers are closable; graph labels fit the viewport; browser execution and offline checks pass before completion is claimed.

## Verification result — 2026-08-30

- 143 Node tests passed; `LIGHTING_INTERFACE_OK`; `git diff --check` passed.
- Local DOM/native Canvas runtime: 34/34 keywords rendered; 6 communities, 3 products, 14 evidence relationships. Product detail reached from a community scopes evidence to that community while retaining the complete related-community list.
- Native Canvas and SVG chart previews inspected. They verify the chart geometry, not a full browser screenshot or responsive CSS layout.
- Four source JSON files remained byte-identical. Prior HTML preserved as `report.before-visual-refresh.html`.
- No new Reddit collection, model calls, scoring/config changes, commits, pushes, or PRs.
- Existing noisy keyword candidates and saturated display weights remain unchanged; this task changes presentation only.

Re-render an existing run without collection:

```powershell
node scripts/render-existing-report.mjs .local/runs/formal-us-lighting-20260829-r3
```

Open `report.html` manually and select the Audience Map or 关键词词云 tab. Check the wide and narrow layouts, drawer closing, and pointer alignment. Run artifacts also include `wordcloud-visual-qa.png`, `map-overview-visual-qa.png`, `map-relations-visual-qa.png`, `map-community-visual-qa.png`, and `visual-qa.json`.
