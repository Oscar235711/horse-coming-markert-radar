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
