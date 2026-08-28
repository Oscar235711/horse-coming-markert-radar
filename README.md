# Opportunity Radar Community Radar

北美柴油皮卡 Reddit 社区机会雷达。当前仓库提供一个可版本化、可断点续跑的 Python CLI，加上兼容旧流程的 PowerShell 包装脚本。

## 当前范围

- Reddit 社区扫描固定对比最近 30 天 vs 之前 60 天
- 每社区最多深读 30 个帖子
- 有 DeepSeek/Higress 配置时可用 Flash/Pro；未配置时自动使用可解释的本地规则/VOC分析，不阻塞采集和报告生成
- 所有 JSON 和 XLSX 都从同一份 `analysis.json` 派生
- 社区词表建议必须先人工审批，审批只生成新版本，不自动切换活动版本

## 安装

```powershell
git clone <repo>
cd opportunity-radar-community-radar
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\scripts\radar.ps1 init
.\scripts\install-tools.ps1
.\scripts\setup-local-runtime.ps1
```

`.env.example` 只保留变量名，不包含任何真实凭据。把它复制成 `.env` 后，只在本机填写需要的路径和密钥。
Python 直接调用 `python -m opportunity_radar ...` 只读取当前进程环境变量；如果希望自动读取仓库 `.env`，请通过 `.\scripts\radar.ps1` 入口运行。

## 关键环境变量

```text
RADAR_RUNS_ROOT=.local\runs
RADAR_DATA_ROOT=.local\data
RADAR_OUTPUT_ROOT=.local\outputs
RADAR_TOOLS_ROOT=.tools
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=
DEEPSEEK_FLASH_MODEL=
DEEPSEEK_PRO_MODEL=
RADAR_AGENT_REACH_EXE=
RADAR_OPENCLI_EXE=
RADAR_NODE_EXE=
RADAR_PYTHON_EXE=
```

## Python CLI

```powershell
python -m opportunity_radar doctor
python -m opportunity_radar run --config configs/diesel_90d.yaml
python -m opportunity_radar resume --run-id <run_id>
python -m opportunity_radar status --run-id <run_id>
python -m opportunity_radar export --run-id <run_id> --formats json,xlsx,html
python -m opportunity_radar communities suggest --run-id <run_id>
python -m opportunity_radar communities approve --suggestion .local\runs\<run_id>\suggestions\community_suggestions.json --suggestion-id <id>
```

`doctor` 在缺少 `DEEPSEEK_API_KEY` 时只给出警告，不会阻断 Reddit 侧检查。
默认导出还会生成离线 `report.html`（不依赖服务器，双击即可打开）；`xlsx` 才需要 `RADAR_NODE_EXE` 或系统 `node`。

## 改装领域 Demo

先用不联网的固定样例查看最终呈现：

```powershell
python scripts/build_diesel_demo.py
```

输出在 `outputs/diesel-demo/`：`analysis.json`、`report.html`、`community_topics.xlsx` 和 `community_topic_map.json`。报告按“社区 → 话题 → 帖子/评论证据”下钻，内容是演示样例；接入真实 Reddit 运行后，用同一个渲染器生成真实报告。

## 已采集数据的本地快速分析

如果已有 OpenCLI 深读结果保存在 `.local/runs/<run_id>/raw/`，可以跳过模型接口，直接用本地规则/VOC分析重建报告：

```powershell
python scripts/rebuild_local_analysis.py --run-id <run_id>
```

该命令会重新生成 `artifacts/analysis.json`、`report.html` 和 `community_topics.xlsx`，并保留原始帖子、评论和证据链接。报告会明确标记 `rule_based`；其中的产品方向只是机会假设，不是开品结论。

## PowerShell 兼容入口

旧命令仍可继续使用：

- `.\scripts\radar.ps1 init`
- `.\scripts\radar.ps1 paths`
- `.\scripts\radar.ps1 doctor`
- `.\scripts\radar.ps1 status`
- `.\scripts\radar.ps1 verify-baseline`
- `.\scripts\radar.ps1 fetch-details`
- `.\scripts\radar.ps1 deep-dive`
- `.\scripts\radar.ps1 report`

新增命令通过 Python CLI 转发：

```powershell
.\scripts\radar.ps1 run -RunConfigPath configs/diesel_90d.yaml
.\scripts\radar.ps1 resume -RunId <run_id>
.\scripts\radar.ps1 export -RunId <run_id> -Formats json,xlsx
.\scripts\radar.ps1 communities-suggest -RunId <run_id>
.\scripts\radar.ps1 communities-approve -Suggestion <path> -SuggestionId <id>
```

## 运行目录

每次运行写入 `RADAR_RUNS_ROOT\<run_id>\`：

- `manifest.json`：启动时间、配置摘要、阶段
- `state.json`：状态、计数、失败摘要、产物路径
- `config.snapshot.yaml`：本次不可变配置快照
- `raw\`：原始 listing
- `checkpoints\`：评论深读和 Flash 提取断点
- `artifacts\analysis.json`：规范分析结果
- `artifacts\community_topics.json` / `community_topics.xlsx`：由同一分析结果导出
- `suggestions\community_suggestions.json`：待审批建议

新的 `run --run-id` 不会复用已存在的目录；如果同一个 `run_id` 已存在，必须改用 `resume`。

## 三人协作建议

- 采集负责人：维护 Chrome/OpenCLI 登录态，先跑 `doctor` 和 live smoke
- 分析负责人：执行 `run` / `resume` / `export`，只分享 `run_id` 和产物路径
- 审批负责人：查看 `communities suggest` 结果，运行 `communities approve` 生成新版本配置

这样能把凭据、本地运行和配置治理分开，减少误改活动版本的风险。

## 已批准社区目录

默认配置引用 `configs/community_catalog.v1.yaml`，内含已批准的四个社区：

- `Cummins`
- `Duramax`
- `powerstroke`
- `FordDiesels`

每条目都带 `aliases`、`include`、`exclude`、`category`、`brand`、`slang` 字段，供扫描和建议审批共用。

## Live Reddit Smoke

显式联机冒烟脚本：

```powershell
.\scripts\live-reddit-smoke.ps1
```

它只验证 OpenCLI/Reddit 登录态和四个种子社区的最小读取，不要求 DeepSeek Key。

## 验证

```powershell
pytest
powershell -NoProfile -File .\tests\verify-portable-config.ps1
powershell -NoProfile -File .\tests\verify-portable-runtime.ps1
powershell -NoProfile -File .\tests\verify-project-tools.ps1
powershell -NoProfile -File .\tests\verify-windows-utf8.ps1
```
