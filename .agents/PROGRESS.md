# PROGRESS / 进度记录模板

Timezone: `Asia/Shanghai`

Record one line per milestone or resume event.

固定格式：

```text
[timestamp] [stage] [status] [details]
```

Example:

```text
[2026-08-28 21:30 CST] [preflight] [started] [branch verified, commit recorded, ENV_PRESENT RADAR_LLM_BASE_URL/RADAR_LLM_API_KEY/RADAR_LLM_MODEL]
[2026-08-28 22:05 CST] [round-one-search] [partial] [429 on one query, resume allowed, waiting for retry policy]
[2026-08-29 06:10 CST] [verification] [complete] [report generated, node --test passed, git diff --check clean]
```

Required fields:

- `[timestamp]`: `YYYY-MM-DD HH:mm CST`
- `[stage]`: `preflight|round-one-search|quality-gate|author-selection|author-deep-dive|keyword-discovery|round-two-search|analysis|personas|report|verification|resume`
- `[status]`: `started|partial|complete|failed|resume`
- `[details]`: concise facts only, include exact branch and exact commit at preflight and every resume

恢复时必须新增一行 `resume` 记录，不得覆盖历史。

[2026-08-29 13:36 CST] [preflight] [complete] [branch=codex/automotive-lighting-reddit-radar, commit=1028f191370db5810f128c87c2bba51f02902b89, worktree clean, remote transport contract verified]
[2026-08-29 13:37 CST] [resume] [started] [branch=codex/automotive-lighting-reddit-radar, commit=1028f191370db5810f128c87c2bba51f02902b89, resumed Task 7-10 release verification]
[2026-08-29 13:39 CST] [round-one-search] [partial] [public-json mini pilot v12-pilot-20260829-continue completed with 8 runtime fetch failures and zero candidates; no unrelated work stopped]
[2026-08-29 13:40 CST] [verification] [complete] [135 node tests and five Windows checks passed; offline report artifact set generated; strict live-secret scan had no matches]
[2026-08-29 16:46 CST] [resume] [complete] [branch=codex/automotive-lighting-reddit-radar, commit=a34b04e, resumed formal run after Windows .cmd argument fix and explicit US threshold configuration]
[2026-08-29 16:47 CST] [report] [complete] [formal-us-lighting-20260829-r3 produced 3 formal opportunities, 4 candidate signals, 231 candidates, 231 details, 2308 comments, 4 unresolved author-activity failures]
