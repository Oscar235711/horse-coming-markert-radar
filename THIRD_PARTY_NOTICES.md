# Third-party notices

## last30days

This repository vendors an unmodified runtime snapshot of **last30days** version
3.23.0 in `vendor/last30days`.

- Upstream project: <https://github.com/mvanhorn/last30days-skill>
- Upstream author: mvanhorn
- Upstream license: MIT (as declared in the upstream `SKILL.md` metadata)
- Snapshot source: the locally installed `last30days` skill, captured on
  2026-09-02.

The snapshot contains the upstream `SKILL.md`, `agents`, `references`, and
`scripts` trees, including upstream script dependencies. It intentionally omits
runtime caches and generated Python bytecode. Project code in
`src/opportunity_radar/last30days_adapter.py` is an independent integration
layer and does not modify the vendored upstream sources.
