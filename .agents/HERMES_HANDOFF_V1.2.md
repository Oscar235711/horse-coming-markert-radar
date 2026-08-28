# Hermes Handoff V1.2 / Hermes 夜间交接 V1.2

## Goal / 目标

Run the V1.2 US automotive-lighting overnight research from the checked-out repository state. Do not develop features, do not rewrite history, and do not change repository ownership state.

运行 V1.2 美国汽车照明夜间研究。只执行采集、分析、续跑和报告生成；不要开发功能，不要改写 Git 历史，不要改变仓库所有权状态。

## Repository Identity / 仓库身份校验

- Repository URL: `https://github.com/Oscar235711/horse-coming-markert-radar.git`
- Required branch: `codex/automotive-lighting-reddit-radar`
- Expected run commit: the operator must record the exact `git rev-parse HEAD` value in `.agents/PROGRESS.md` before starting the run and must stop if the checked-out commit changes later.

```bash
git remote get-url origin
git branch --show-current
git rev-parse HEAD
git status --short
```

Stop if:

- `origin` is not the repository URL above;
- `git branch --show-current` is not `codex/automotive-lighting-reddit-radar`;
- `git status --short` shows unexpected tracked edits outside `.local/`;
- the exact `git rev-parse HEAD` value is not the commit intentionally chosen for this overnight run.

如果 `origin`、分支名、工作树状态或当前 commit 与预期不一致，立即停止，不要猜测。

## Secrets and Runtime Preflight / 密钥与运行时预检

Required runtime:

- Node.js available on `PATH` or via `scripts/radar.ps1`
- OpenCLI available for the local transport path
- Reddit logged-in browser session already prepared outside the repository

Required environment variables for DSV4Pro:

- `RADAR_LLM_BASE_URL`
- `RADAR_LLM_API_KEY`
- `RADAR_LLM_MODEL`

Presence-only preflight. Never print secret values:

```powershell
$requiredEnv = @('RADAR_LLM_BASE_URL', 'RADAR_LLM_API_KEY', 'RADAR_LLM_MODEL')
foreach ($name in $requiredEnv) {
  if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
    throw "MISSING_ENV $name"
  }
  Write-Host "ENV_PRESENT $name"
}
```

禁止输出 Bearer、API Key、cookie、token、`.env` 内容或任何 secret 值。

## Transport Rules / 通道规则

- Preferred transport: `opencli`
- Fallback transport: `public-json` only if local OpenCLI is unavailable before the run starts
- OpenCLI detail reads must keep `--expand-more false`
- Do not change the transport implementation during the overnight run unless the current transport is unavailable before collection begins

## Exact Commands / 精确命令

Primary overnight command:

```powershell
.\scripts\radar.ps1 run `
  -Profile overnight `
  -Transport opencli `
  -MaxRuntimeMinutes 600 `
  -LlmModel dsv4pro `
  -RunId "overnight-YYYYMMDD-HHMM"
```

Equivalent direct Node command:

```powershell
node .\scripts\run-radar.mjs `
  --profile overnight `
  --transport opencli `
  --max-runtime-minutes 600 `
  --llm-model dsv4pro `
  --run-id "overnight-YYYYMMDD-HHMM"
```

Resume command: reuse the same `--run-id` or `-RunId` exactly. Successful stages must not be repeated. Retry only unresolved items.

输出目录固定为 `.local/runs/<run_id>/`。不要写个人绝对路径，不要把结果搬到仓库外的个人目录。

## Stage Order / 固定阶段顺序

1. Preflight
2. Round-one search
3. Quality gate
4. Author selection
5. Public author deep dive
6. Keyword discovery
7. Round-two search
8. Analysis
9. Personas
10. Audience map, keyword cloud, report generation
11. Verification

## Runtime and Retry Policy / 运行时与重试策略

- Max wall-clock runtime: `600` minutes
- Reddit query/post/author attempts: at most `3` total attempts, with waits of `15 seconds` and `45 seconds`
- DSV4Pro attempts: at most `2` total attempts, with a wait of `30 seconds`
- Honor `Retry-After` when present, capped at `120` seconds
- One exhausted item becomes an unresolved failure and must not stop unrelated work

If Task 7 resume history is available, preserve `failure_attempts.jsonl`. Always preserve `failures.jsonl`.

## Stop Conditions / 必须停止条件

- Missing repository or wrong repository URL
- Wrong branch or wrong exact commit for the intended overnight run
- Missing required runtime or missing required environment variables
- Schema corruption
- Privacy-rule failure
- Repeated fatal failure after the configured retry ceiling

## Non-stop Conditions / 不停机条件

- One unavailable post
- Deleted author
- Private or suspended profile
- Individual `403` or `429`
- DSV4Pro timeout
- `persona_status: insufficient_sample`
- Exploratory term rejected by the quality gate

## Safety Boundaries / 安全边界

Public Reddit read-only only.

PROHIBITED:

- git push
- git tag
- git merge
- pull request creation
- secret output
- account messages, votes, follows, or settings changes
- formal keyword mutation
- deleting partial run artifacts

Hermes 禁止 push、禁止打 tag、禁止 merge、禁止改正式关键词、禁止删除 partial 产物。

## Expected Artifacts / 预期产物

The run directory should contain:

- `config.snapshot.json`
- `candidates.json`
- `quality_evidence.jsonl`
- `excluded_evidence.jsonl`
- `raw/details/*.json`
- `raw/authors/*.json`
- `keyword_candidates.json`
- `keyword_cloud.json`
- `opportunities.json`
- `personas.json`
- `analysis.json`
- `audience_map.json`
- `manifest.json`
- `report.html`
- `failures.jsonl`
- `failure_attempts.jsonl` if available in the current resume implementation
- `optimization_backlog.jsonl`

## Acceptance Checks / 验收检查

```powershell
node --test "tests/*.test.mjs"
.\tests\verify-lighting-interface.ps1
git diff --check
```

Also verify:

- `report.html` opens offline
- JSON counts match the HTML summary
- there are zero unsupported evidence links
- `.agents/PROGRESS.md` and `.agents/OUTBOX.md` are updated for the run

## Progress and Outbox Rules / PROGRESS 与 OUTBOX 规则

- Append progress entries to `.agents/PROGRESS.md`
- Write the final structured summary to `.agents/OUTBOX.md`
- Use `Asia/Shanghai` timestamps
- Record the exact branch and exact commit before the run and after any resume

## Clean Shutdown / 安全退出

On stop, timeout, or partial completion:

- preserve checkpoints;
- preserve partial artifacts;
- record unresolved failures;
- update `.agents/PROGRESS.md`;
- update `.agents/OUTBOX.md`;
- exit without deleting data.
