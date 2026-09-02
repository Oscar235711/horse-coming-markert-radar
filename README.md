# Opportunity Radar｜柴油皮卡 Reddit 社区机会雷达

Opportunity Radar 是 SuncentAuto 的本地市场探索工具。它把 Reddit 的公开讨论整理为：

```text
用户输入研究问题、日期和采集深度
→ DeepSeek 生成检索计划并自动扩词
→ OpenCLI 全站/种子社区采集帖子、评论和回复
→ DeepSeek 提取 VOC 并归并话题
→ 社区内聚类
→ analysis.json
→ 社区图谱、右侧预览、完整话题报告和 Excel
```

当前默认使用四个种子社区：`r/Cummins`、`r/Duramax`、`r/powerstroke`、`r/FordDiesels`。它们只作为后台基线；用户不需要选择社区。关键词和社区库会跨运行累计，相关的新社区会根据本轮证据归因。

报告用于发现和排序信号。任何改款、SKU、组合包或新品方向都是“机会假设”，不是开品结论；没有业务数据时不推断价格、利润、制造工艺或供应链结论。

## 1. 当前已实现

- 网页以“你想了解什么？”作为唯一研究入口，自动生成检索词；日期和采集深度仍可自定义。
- 快速、标准、深度和完整四档；完整档按日期/平台边界运行，不设项目数量上限。
- 项目自带 OpenCLI 插件，按 `new` 分页，并补充 `top`、`controversial`、`hot`。
- 精确日期过滤、帖子 ID 去重、覆盖状态和断点续跑。
- 深读保留评论正文、作者、层级、评论 ID 和 Reddit 永久链接。
- 分层选择高互动、月份均衡、具体问题和争议/弱信号帖。
- Higress DeepSeek 两阶段分析：先生成检索计划，再提取帖子 VOC 和社区话题；页面保留 Codex 作为可选后备。
- VOC“场景—任务—痛点—后果—当前方案—方案不足—产品判断”报告。
- 点击社区展开话题；点击话题先打开右侧预览；预览底部再进入完整报告。
- URL Hash 保存社区、话题和页面状态，支持关闭、浏览器前进和后退。
- HTML 和 Excel 只读取同一份 `analysis.json` 与 `report_metrics`，数字口径一致。
- 项目级社区、话题和关键词累计库位于 `library/`，有效概念会自动沉淀，语法碎片进入隔离区。
- 网页可以保存每日、每周或每月滚动时间窗口任务；服务运行时自动创建普通可续跑任务。

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

## 团队成员第一次使用（必读）

仓库代码由队长统一合并，运行环境和登录态由每位成员在自己的电脑上单独配置。不要把 `.env`、Chrome Cookie、Codex 登录信息或 `.local/` 运行数据提交到 GitHub。

### 成员安装步骤

```powershell
git clone -b feature/community-radar https://github.com/Oscar235711/horse-coming-markert-radar.git
cd horse-coming-markert-radar
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\install-tools.ps1
.\scripts\setup-local-runtime.ps1
.\scripts\install-opencli-plugin.ps1
```

然后在本机 `.env` 填写自己的工具路径；DeepSeek 使用公司 Higress 网关时填写 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_API_KEY`，不要把真实值写进 YAML 或提交到仓库。打开 Chrome，登录 Reddit 小号，再检查：

```powershell
.\scripts\radar.ps1 doctor
opencli validate opportunity-reddit
```

### 每次研究的操作步骤

1. 进入项目目录，运行 `.\scripts\radar.ps1 serve`。
2. 在网页输入研究问题，例如“Duramax 拖挂时的高温和排气改装痛点”。
3. 选择日期范围和采集深度，点击“开始采集”。社区是后台种子库，不需要成员手工选择。
4. 在“任务进度”查看采集、深读、分析和导出状态；同一台电脑同一时间只运行一个任务。
5. 完成后点击“打开 HTML 报告”或“下载 Excel”。文件位于 `.local/runs/<run_id>/artifacts/`。
6. 任务卡显示失败时，先使用“续跑任务”；确认不再需要时可点击“删除任务”。删除只清理该任务的本地目录，不影响代码和累计库。

### 团队结果回传方式

- 代码或配置修改：新建分支并提交 Pull Request，说明改动和测试结果。
- 研究结果：把 `run_id`、HTML/Excel 文件路径和一句话结论发到团队群；默认不提交 Reddit 原始数据。
- 词库和社区库：运行时会写入本机 `library/`。需要纳入团队基线时，由队长审核差异后再提交 `library/communities.json`、`library/topics.json` 或 `library/keywords.json`。
- 队长合并后，成员执行 `git pull --rebase origin feature/community-radar`，再继续使用自己的 `.env` 和 Chrome 会话。

### 三人分工建议

| 角色 | 负责内容 | 交付物 |
|---|---|---|
| 队长/业务负责人 | 研究问题、日期范围、结论确认和合并 | 研究任务说明、采纳/不采纳结论 |
| 数据采集负责人 | Reddit 登录态、OpenCLI、采集失败和覆盖日期 | `run_id`、失败记录、覆盖说明 |
| 分析与工程负责人 | DeepSeek/Codex 配置、报告检查、代码修复 | HTML、Excel、PR 和测试结果 |

成员不需要手工复制帖子到 Excel；网页任务完成后，统一从同一个 `analysis.json` 生成 HTML 和 Excel，数字口径保持一致。

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

- 输入自然语言研究问题；
- 选择预设时间或自定义起止日期（最多 365 天）；
- 选择快速、标准、深度；
- 系统自动扩展英文检索词并发现相关社区；
- 启动任务、查看阶段进度和失败原因；
- 对已暂停/失败/完成任务执行“续跑”或“删除任务”（删除只清理该任务本地数据、检查点和报告，不影响代码、社区库和关键词库）；
- 打开完成的 HTML 报告或下载 Excel。

网页的“定时任务”区域可以保存滚动窗口（例如每周扫描最近 90 天）。若需要让 Windows 在服务未启动时也触发任务，可使用：

```powershell
.\skills\opportunity-radar\scripts\register-schedule.ps1 `
  -TaskName "Opportunity Radar weekly" -Frequency WEEKLY -StartTime 09:00 -WindowDays 90
```

同一时间只运行一个采集任务，避免 Chrome 会话冲突和 Reddit 限流。

任务完成或暂停后，页面显示请求日期与实际覆盖日期。若 Reddit 分页、登录态或限流导致未到达开始日期，会标记为 `partial`；这不代表已获取 Reddit 全量数据。

为避免单次 Reddit 请求长时间无响应，OpenCLI 子进程默认 60 秒超时；需要更长时间时可在启动服务前设置 `RADAR_OPENCLI_TIMEOUT_SECONDS`。

如不希望自动打开浏览器：

```powershell
.\scripts\radar.ps1 serve -NoOpen -Port 8765
```

## 5. 命令行运行

用自然语言问题、时间和深度运行：

```powershell
.\scripts\radar.ps1 run `
  -RunConfigPath configs/diesel_90d.yaml `
  -RunId 20260831T-demo `
  -StartDate 2026-01-01 `
  -EndDate 2026-08-31 `
  -Depth complete `
  -AnalysisEngine deepseek `
  -ResearchQuestion "我想了解 Duramax 拖挂时的高温和排气改装痛点"
```

等价 Python 命令：

```powershell
.\.venv\Scripts\python -m opportunity_radar run `
  --config configs/diesel_90d.yaml `
  --start-date 2026-01-01 --end-date 2026-08-31 `
  --depth complete --analysis-engine deepseek `
  --research-question "我想了解 Duramax 拖挂时的高温和排气改装痛点"
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

## 6. 采集规模

| 档位 | 每社区列表上限 | 每社区深读上限 |
|---|---:|---:|
| 快速 | 300 | 30 |
| 标准 | 1,000 | 80 |
| 深度 | 1,000 | 150 |
| 完整（默认） | 按日期边界或 Reddit 耗尽 | 按日期边界或 Reddit 耗尽 |

完整档不设置项目侧的帖子、关键词或深读数量上限；系统会保留日期范围内采集到的全部原始证据。为适配模型上下文，分析请求会自动分块并在本地合并，分块不是对原始数据的删减。快速、标准、深度仅作为需要更快反馈时的可选加速档。

标准档深读按以下思路混合选择：高互动/讨论深度、月份均衡、问题具体、争议/反对观点。不会只按赞数筛选。

如果到达列表上限仍没有覆盖用户选择的开始日期，该社区会标记为 `partial`，报告只显示实际覆盖日期，不声称是 Reddit 全量数据。

## 7. 分析规则

默认使用 Higress DeepSeek（也可切换本机 Codex）分两阶段运行：

1. 帖子级提取平台、车型/年份、用户类型、场景、任务、痛点、严重度/后果、需求、当前方案、方案不足、购买/维修意向、关键词和观点。
2. 只在同一社区内，按“用户面对的同类任务或问题”归并话题。

完整档会把一个超长帖子拆成多个模型请求再合并；如需调整单次请求的安全大小，可设置 `DEEPSEEK_CHUNK_CHARS`。这只控制模型上下文，不会删除或覆盖 `.local/runs/<run_id>/` 中的原始帖子和评论。

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

每轮运行自动累计社区、稳定话题和候选关键词索引。网页只要求输入研究问题和日期；四个种子社区作为后台基线，系统同时按问题扩展词进行全站检索。候选社区和关键词先保留来源、作者数和证据，再由清洗规则决定是否进入下一轮检索。Excel 的“社区库”和“话题关键词库”是本轮可阅读投影。

## 10. 可复用 Skill

完整 Codex Skill 位于 `skills/opportunity-radar/`，包含流程说明、报告契约和可执行 PowerShell 入口。它适合在新的 Codex 任务中复用“选日期 → 读库 → 采集 → Codex VOC → 导出”的完整链路；Skill 不会自行注册操作系统定时任务，注册需要用户明确执行脚本。

## 11. 测试

```powershell
python -m pytest
node --test opencli-plugin/opportunity-reddit/*.test.mjs
opencli validate opportunity-reddit
```

## 12. 常见问题

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

## 13. 安全边界

禁止提交：`.env`、`.local/`、`.venv/`、Cookie、API Key、Codex 认证信息和原始 Reddit 用户数据。报告保留市场讨论，但不生成违规操作教程。
