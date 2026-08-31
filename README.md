# Opportunity Radar｜柴油皮卡 Reddit 社区机会雷达

Opportunity Radar 是 SuncentAuto 的本地市场探索工具。它把 Reddit 的公开讨论整理为：

```text
网页选择社区、日期和采集深度
→ OpenCLI 分页采集帖子、评论和回复
→ 本机 Codex 提取 VOC
→ 社区内聚类
→ analysis.json
→ 社区图谱、右侧预览、完整话题报告和 Excel
```

当前固定四个社区：`r/Cummins`、`r/Duramax`、`r/powerstroke`、`r/FordDiesels`。不做用户主页深挖，也不会自动扩展社区。

报告用于发现和排序信号。任何改款、SKU、组合包或新品方向都是“机会假设”，不是开品结论；没有业务数据时不推断价格、利润、制造工艺或供应链结论。

## 1. 当前已实现

- 网页可选一个或多个社区，以及最近 30、90、180、365 天或自定义日期。
- 快速、标准、深度三档，分别最多深读 30、80、150 篇/社区。
- 项目自带 OpenCLI 插件，按 `new` 分页，并补充 `top`、`controversial`、`hot`。
- 精确日期过滤、帖子 ID 去重、覆盖状态和断点续跑。
- 深读保留评论正文、作者、层级、评论 ID 和 Reddit 永久链接。
- 分层选择高互动、月份均衡、具体问题和争议/弱信号帖。
- 本机 `codex exec --ephemeral --sandbox read-only` 两阶段分析，不依赖 DeepSeek。
- VOC“场景—任务—痛点—后果—当前方案—方案不足—产品判断”报告。
- 点击社区展开话题；点击话题先打开右侧预览；预览底部再进入完整报告。
- URL Hash 保存社区、话题和页面状态，支持关闭、浏览器前进和后退。
- HTML 和 Excel 只读取同一份 `analysis.json` 与 `report_metrics`，数字口径一致。
- 项目级社区、话题和关键词累计库位于 `library/`。

## 2. 环境安装

要求：Windows、Python 3.12+、Node.js、已登录 Codex CLI、Chrome、OpenCLI 扩展，以及 Chrome 中已经登录的 Reddit 小号。

```powershell
git clone -b feature/community-radar https://github.com/Oscar235711/horse-coming-markert-radar.git
cd horse-coming-markert-radar

py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\scripts\radar.ps1 init
```

如 PowerShell 阻止脚本，仅对当前窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

安装/准备 OpenCLI、Node 和 Excel 运行库：

```powershell
.\scripts\install-tools.ps1
.\scripts\setup-local-runtime.ps1
```

OpenCLI 已存在时，可跳过 `install-tools.ps1`。如命令不在 PATH，在本机 `.env` 设置：

```text
RADAR_OPENCLI_EXE=C:\Users\你的用户名\AppData\Roaming\npm\opencli.cmd
RADAR_NODE_EXE=C:\Program Files\nodejs\node.exe
RADAR_CODEX_EXE=C:\你本机的路径\codex.exe
```

安装本项目的 Reddit 分页和证据深读插件：

```powershell
.\scripts\install-opencli-plugin.ps1
```

每位同事使用自己的 Reddit 小号和 Chrome 会话，不复制 Cookie，不把 Cookie 写入项目。

## 3. 环境检查

```powershell
.\scripts\radar.ps1 doctor
```

检查项包括 Python、OpenCLI、项目分页插件、Chrome Reddit 会话、四个社区、Codex、Node 和 Excel 环境。DeepSeek 是可选项，未配置不会阻塞默认流程。

Codex 单篇分析默认最多等待 180 秒；网络较慢时可在本机 `.env` 调大：

```text
RADAR_CODEX_TIMEOUT_SECONDS=300
```

也可单独确认插件：

```powershell
opencli validate opportunity-reddit
opencli opportunity-reddit range Cummins `
  --start-date 2026-08-01 --end-date 2026-08-31 --limit 10 `
  -f json --window foreground --site-session persistent
```

## 4. 推荐使用方式：本地网页

```powershell
.\scripts\radar.ps1 serve
```

默认打开 `http://127.0.0.1:8765`。网页中可以：

- 选择四个社区中的一个或多个；
- 选择预设时间或自定义起止日期（最多 365 天）；
- 选择快速、标准、深度；
- 启动任务、查看阶段进度和失败原因；
- 打开完成的 HTML 报告或下载 Excel。

同一时间只运行一个采集任务，避免 Chrome 会话冲突和 Reddit 限流。

如不希望自动打开浏览器：

```powershell
.\scripts\radar.ps1 serve -NoOpen -Port 8765
```

## 5. 命令行运行

自定义时间、社区和深度：

```powershell
.\scripts\radar.ps1 run `
  -RunConfigPath configs/diesel_90d.yaml `
  -RunId 20260831T-demo `
  -StartDate 2026-01-01 `
  -EndDate 2026-08-31 `
  -Depth standard `
  -AnalysisEngine codex `
  -Communities "Cummins,Duramax,powerstroke,FordDiesels"
```

等价 Python 命令：

```powershell
.\.venv\Scripts\python -m opportunity_radar run `
  --config configs/diesel_90d.yaml `
  --start-date 2026-01-01 --end-date 2026-08-31 `
  --depth standard --analysis-engine codex `
  --communities Cummins,Duramax,powerstroke,FordDiesels
```

断点续跑、查看状态和重新导出：

```powershell
.\scripts\radar.ps1 resume -RunId <run_id>
.\scripts\radar.ps1 status -RunId <run_id>
.\scripts\radar.ps1 export -RunId <run_id> -Formats json,xlsx,html
```

查看并批准本轮发现的候选话题关键词（不会自动改动四个正式社区）：

```powershell
.\.venv\Scripts\python -m opportunity_radar keywords suggest --run-id <run_id>
.\.venv\Scripts\python -m opportunity_radar keywords approve --file <keyword_suggestions.json>
```

## 6. 三档采集规模

| 档位 | 每社区列表上限 | 每社区深读上限 |
|---|---:|---:|
| 快速 | 300 | 30 |
| 标准 | 1,000 | 80 |
| 深度 | 1,000 | 150 |

标准档深读按以下思路混合选择：高互动/讨论深度、月份均衡、问题具体、争议/反对观点。不会只按赞数筛选。

如果到达列表上限仍没有覆盖用户选择的开始日期，该社区会标记为 `partial`，报告只显示实际覆盖日期，不声称是 Reddit 全量数据。

## 7. 分析规则

Codex 分两阶段运行：

1. 帖子级提取平台、车型/年份、用户类型、场景、任务、痛点、严重度/后果、需求、当前方案、方案不足、购买/维修意向、关键词和观点。
2. 只在同一社区内，按“用户面对的同类任务或问题”归并话题。

每个判断均区分：

- `fact`：原文直接支持；
- `inference`：基于多条证据的 AI 推断；
- `unknown`：当前证据无法判断。

产品判断只能为：改进现有产品、新增车型/年份 SKU、配件或组合包、新产品开发、内容/工具/服务机会、暂不形成产品机会。没有证据时必须选择最后一项。

正式话题门槛：至少 3 篇不同帖子和 3 名作者，或至少 2 篇帖子和 10 名独立评论者。未达到门槛的内容进入弱信号区，不生成“其他规则主题”。

## 8. 产物位置

```text
.local/runs/<run_id>/
├─ config.snapshot.yaml
├─ raw/
│  ├─ listings/
│  └─ threads/
├─ normalized/
│  ├─ posts.jsonl
│  └─ comments.jsonl
├─ checkpoints/
├─ artifacts/
│  ├─ analysis.json
│  ├─ community_topics.json
│  ├─ community_topics.xlsx
│  ├─ report.html
│  └─ community_topic_map.json
├─ failures.jsonl
└─ run_manifest.json
```

Excel 固定包含：运行概览、社区库、话题关键词库、社区热点排行、话题分析卡、帖子及评论证据、弱信号观察区、排除与失败记录。

统一数字定义写入 `analysis.json.report_metrics`：扫描去重帖、深读帖、进入分析帖、支撑话题帖、发帖作者、评论者、独立参与者、采集评论和被引用证据。

## 9. 项目累计库

```text
library/
├─ communities.json
├─ topics.json
└─ keywords.json
```

每轮运行自动累计社区、稳定话题和候选关键词索引。它不会自动扩展本轮四个社区，也不会把候选词自动升级为正式检索词。Excel 的“社区库”和“话题关键词库”是本轮可阅读投影。

## 10. 测试

```powershell
python -m pytest
node --test opencli-plugin/opportunity-reddit/*.test.mjs
opencli validate opportunity-reddit
```

## 11. 常见问题

### OpenCLI 找不到项目插件

```powershell
.\scripts\install-opencli-plugin.ps1
opencli validate opportunity-reddit
```

### Reddit 不可读或未登录

确认 Chrome 已打开、OpenCLI 扩展已连接，并在该 Chrome 会话中登录 reddit.com。项目不会替用户登录或导出 Cookie。

### 429 或页面失败

停止反复新建任务，稍后用原 `run_id` 执行 `resume`。单个帖子失败会记录在任务和 Excel 中。

### Codex 分析失败

确认 `codex` 命令已登录且可用，或在 `.env` 设置 `RADAR_CODEX_EXE`。失败的帖子分析有检查点，可续跑；Reddit 文本始终作为不可信数据，只读传给 Codex。

### Excel 未生成

运行 `doctor` 检查 Node 和 `@oai/artifact-tool` 运行库，然后对现有 `run_id` 执行 `export`，无需重新采集。

## 12. 安全边界

禁止提交：`.env`、`.local/`、`.venv/`、Cookie、API Key、Codex 认证信息和原始 Reddit 用户数据。报告保留市场讨论，但不生成违规操作教程。
