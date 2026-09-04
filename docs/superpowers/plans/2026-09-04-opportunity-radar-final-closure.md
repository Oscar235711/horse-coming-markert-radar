# Opportunity Radar 全链路验收与缺陷闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复当前已确认的报告、Excel、词库和 Hot30 缺陷，并以一次真实的 365 天 Reddit 研究与一次真实的近 30 天多平台热点研究证明“选择范围 → 采集 → 深读 → DeepSeek VOC → 聚类 → 中文 HTML/Excel/JSON”的闭环可运行、可恢复且不误报完成。

**Architecture:** 保留 Python 3.12 主流程、OpenCLI + Chrome Reddit 登录态采集、Higress DeepSeek 分析、vendored last30days 多平台引擎和本地网页。四个柴油社区继续作为种子入口；项目级关键词库驱动 Reddit 全站搜索；可信的新社区和关键词自动进入下一轮活动库。`analysis.json` 是范围研究唯一事实源，Hot30 的 `analysis.json.overview` 是热点简报唯一中文事实源。

**Tech Stack:** Python 3.12、PyYAML、pytest、PowerShell、Node.js 原生测试、OpenCLI 插件、Higress OpenAI-compatible DeepSeek、HTML/CSS/JavaScript、OOXML/XLSX。

**Spec:** 当前工作区已通过 157 个 Python 测试和 6 个 OpenCLI Node 测试，但这些测试没有覆盖同事遇到的真实报告点击、手机空白和 Excel 外链问题。旧的 365 天运行 `20260831T-full365` 扫描 4,000 帖、深读 320 帖、分析 88 帖、输出 49 个话题；其中只有 Duramax 完整覆盖请求起点，Cummins、FordDiesels、powerstroke 均为 partial，而且该运行使用 Codex，不是最终要求的 DeepSeek。当前累计库有 39 个社区、33,064 个关键词和 124 个话题，其中存在无关社区被错误标为 approved、通用短语被错误激活的问题。最新 Hot30 运行 `20260904T145458Z-70bda5` 返回 330 条证据和 7 个中文话题，但有效来源主要是 Reddit、Digg、GitHub、Hacker News；TikTok/Instagram 未配置，YouTube 为零结果，且网页当前走 normal-topic 路径，没有把 Skill 的三段式 discovery 结果合并进同一热点总览。

## Global Constraints

- 不修改或删除用户现有的 `.local/runs/` 原始数据；修复后另建验收运行。
- 不把 `.env`、Cookie、API Key、Chrome 配置、绝对用户路径或原始认证日志提交到 GitHub。
- 不使用规则分析替代 DeepSeek。模型不可用时任务进入 `incomplete/degraded`，不得生成模板化正式话题。
- 不把 Reddit 列表上限或搜索结果上限误报成全量。每个来源必须保存请求范围、实际范围、停止原因和 `complete/partial` 状态。
- 地图只展示达到证据门槛的正式话题；零正式话题社区仍可出现在“覆盖说明”中，但不得出现在社区话题图谱中。
- 四个种子社区必须保留；新社区和新关键词只能通过可解释的证据阈值自动激活，无关结果进入 `quarantined`。
- HTML、Excel 和 JSON 的帖子、作者、评论者、参与者、评论、证据、社区和话题数量必须来自同一个规范化对象。
- Hot30 默认排除 X，遵守用户当前选择；其他来源按实际配置运行并如实展示状态。
- 每项修改先补失败测试，再写最小修复；每个任务单独提交，最后从干净检出目录执行发布验收。

## Current completion assessment

| 最终产物/能力 | 当前证据 | 当前判断 | 本计划验收目标 |
|---|---|---|---|
| 自选时间范围网页 | 已能选择日期、深度和分析引擎并创建任务 | 基本完成 | 365 天 complete 真实运行可创建、取消、续跑、下载 |
| Reddit 社区采集 | 四个种子社区已有真实数据；OpenCLI 分页测试 6/6 | 部分完成 | 四社区均记录真实停止原因；partial 不显示完成 |
| Reddit 关键词全站检索 | 代码和单测已有无上限 complete、同轮扩词 | 尚未真实全年验收 | 真实 365 天运行证明关键词检索、去重、续跑和新增社区来源 |
| 帖子/评论/证据存储 | raw、normalized、checkpoints、evidence gate 已存在 | 基本完成 | 中断后不重爬成功阶段，证据 URL 覆盖 100% |
| DeepSeek VOC | 小规模 `20260902T-smoke-deepseek` 跑通 | 部分完成 | 全年验收运行只用 DeepSeek，正式话题字段完整且有证据 |
| 社区/关键词/话题库 | 三个版本化 JSON 已存在并自动写入 | 不合格 | 清除错误 approved/active，自动延伸和下一轮复用可证明 |
| 社区→话题→帖子结构 | 数据结构存在，稳定 topic_id 有测试 | 部分完成 | 地图无重复社区、无零话题节点、无弱信号冒充正式话题 |
| 中文 HTML 报告 | 页面结构已存在 | 不合格 | 修复社区点击异常、手机空白、预览/完整报告/返回 |
| Excel | 八个工作表已生成 | 不合格 | 外链为真实 OOXML hyperlink，Excel/WPS 可点击 |
| Opportunity Radar Skill | 当前文件可严格 UTF-8 解码 | 待环境验收 | 干净 clone、Windows PowerShell、Skill 包检查全部通过 |
| Hot30 多平台热点 | 已有 330 证据、7 个中文话题样例 | 部分完成 | discovery + topic research 合并；来源状态、中文总览和弱信号完整 |

结论：功能骨架约完成 80%，按最终交付验收口径约完成 55%。当前不能宣称“全年稳定采集分析”或“Hot30 已完善”。

## Task 1: 建立真实发布门禁并固定现有缺陷

**Files:**
- Create: `tests/test_release_contract.py`
- Create: `scripts/check_release.ps1`
- Modify: `tests/test_topic_export.py`
- Modify: `tests/test_web_server.py`

**Step 1: 写报告运行时失败测试**

使用最小 `analysis.json` 生成报告，断言：

- HTML 中调用的每个全局函数都已定义；
- 访问 `#community=Cummins&view=community` 后右侧包含“社区概览”；
- 访问 `#community=Cummins&topic=<topic_id>&view=preview` 后包含中文话题预览；
- 390×844 移动端 hash 路径不出现空白详情页。

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_release_contract.py -q
```

Expected: 当前代码因 `showCommunityDetail is not defined` 失败。

**Step 2: 写零话题社区测试**

输入一个有正式话题社区、一个仅弱信号社区和一个完全无话题社区，断言图谱 JSON 和 HTML 的 `COMMUNITIES` 只包含第一个社区；覆盖表仍保留全部三个社区及原因。

**Step 3: 写 Excel 外链关系测试**

解压生成的 XLSX，断言证据工作表包含 `<hyperlink ref="H4" r:id="...">` 和对应 external relationship；断言不存在 `HYPERLINK is not implemented`、`t="e"` 公式错误或伪链接。

**Step 4: 写 Skill 编码/打包测试**

对 `skills/opportunity-radar/` 下所有文本执行严格 UTF-8 解码，验证 `SKILL.md` front matter、相对链接和引用文件；用 Windows PowerShell 解析两个 `.ps1` 脚本；测试从只含 Git 跟踪文件的临时目录安装 Skill。

**Step 5: 建立统一发布命令**

`scripts/check_release.ps1` 依次运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test .\opencli-plugin\opportunity-reddit\*.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_release_contract.py -q
```

任一命令非零即退出非零，不吞 stderr。

**Step 6: Commit**

```powershell
git add tests/test_release_contract.py tests/test_topic_export.py tests/test_web_server.py scripts/check_release.ps1
git commit -m "test: add end-to-end release contract"
```

## Task 2: 修复零话题节点、社区点击异常和移动端空白

**Files:**
- Modify: `src/opportunity_radar/report.py`
- Modify: `src/opportunity_radar/topics.py`
- Modify: `tests/test_release_contract.py`
- Modify: `tests/test_topic_export.py`

**Step 1: 统一可视图谱投影**

在 `report.py` 中新增纯 Python 投影函数：

```python
def build_visible_topic_map(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Return case-folded communities that own at least one formal topic."""
```

要求：

- 永远只取 `status == "formal"` 的话题，不在“无正式话题”时回退显示弱信号；
- 社区名去掉 `r/` 后按 `casefold()` 去重；
- 社区节点只由正式话题反向产生；
- `topics.py` 删除或改为调用同一个投影函数，避免两个实现再次分叉。

**Step 2: 实现缺失的社区预览**

在内嵌报告脚本中实现 `showCommunityDetail(name)`，只读取规范化社区指标和正式话题，显示社区数据范围、正式话题数、扫描/深读/分析帖子数、覆盖状态和话题排行。任何字段缺失时显示“当前证据不足”，不能抛异常。

**Step 3: 修复移动布局和 hash 状态**

- 移动端社区预览和话题预览占满单列；
- 完整报告保留返回预览按钮；
- 无效社区、无效 topic hash 回到全局图，不留下空白右栏；
- 关闭按钮、浏览器前进/后退和直接打开 hash 均可用；
- 社区图、话题预览、完整报告均使用中文主字段。

**Step 4: 运行报告测试和真实浏览器 smoke**

用本机 Edge headless 对桌面和 390×844 两种尺寸分别打开：全局、社区、话题预览和完整报告 hash。`--dump-dom` 必须包含对应中文标题，进程退出码为 0。

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_release_contract.py tests/test_topic_export.py -q
```

Expected: 全部通过；生成报告脚本经 Node `new Function(...)` 语法检查通过。

**Step 5: Commit**

```powershell
git add src/opportunity_radar/report.py src/opportunity_radar/topics.py tests/test_release_contract.py tests/test_topic_export.py
git commit -m "fix: make report graph and mobile drilldown reliable"
```

## Task 3: 生成真正可点击的 Excel 外链并锁定 Skill 编码

**Files:**
- Modify: `scripts/build_topic_workbook.mjs`
- Create: `src/opportunity_radar/xlsx_links.py`
- Modify: `src/opportunity_radar/topics.py`
- Modify: `tests/test_topic_export.py`
- Create: `tests/test_skill_package.py`
- Create: `.editorconfig`
- Modify: `skills/opportunity-radar/SKILL.md`
- Modify: `skills/opportunity-radar/references/workflow.md`

**Step 1: 移除不受支持的公式链接**

停止向 artifact-tool 写 `=HYPERLINK(...)`。保留 H 列显示文字“打开证据”，I 列保留原始 URL 作为可读备份。

**Step 2: 用标准库写 OOXML external hyperlink**

实现：

```python
def inject_external_hyperlinks(
    workbook_path: Path,
    *,
    sheet_name: str,
    links: Mapping[str, str],
) -> None:
    """Add real external hyperlink relationships to an existing XLSX."""
```

函数用 `zipfile` 和 `xml.etree.ElementTree` 修改目标 sheet 的 `<hyperlinks>` 与 `.rels`，不新增第三方依赖。`topics.export_topic_artifacts()` 在 Node 导出后调用该函数，并再次打开 ZIP 校验关系存在。

**Step 3: 加强 Excel 回归**

测试必须检查：

- 证据 H4 是普通字符串单元格；
- H4 存在 external hyperlink relationship；
- URL 和显示标签正确；
- 中文工作表名称和正文未损坏；
- HTML、JSON、Excel 的核心计数一致。

**Step 4: 锁定 Skill 文本格式**

- `.editorconfig` 对 Markdown/YAML/JSON/Python/JavaScript 使用 UTF-8 和 LF；PowerShell 明确 UTF-8；
- `SKILL.md` 写明 Windows PowerShell 入口和输出文件；
- 所有 Skill 引用路径必须存在；
- `tests/test_skill_package.py` 在临时干净目录验证，不依赖开发机未提交文件。

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_topic_export.py tests/test_skill_package.py -q
```

Expected: 全部通过，XLSX 内不再出现 `HYPERLINK is not implemented`。

**Step 5: Commit**

```powershell
git add scripts/build_topic_workbook.mjs src/opportunity_radar/xlsx_links.py src/opportunity_radar/topics.py tests/test_topic_export.py tests/test_skill_package.py .editorconfig skills/opportunity-radar
git commit -m "fix: export native Excel links and validate skill encoding"
```

## Task 4: 清理并闭合社区、关键词、话题自动延伸库

**Files:**
- Modify: `src/opportunity_radar/library.py`
- Modify: `src/opportunity_radar/keywords.py`
- Modify: `src/opportunity_radar/cli_app.py`
- Create: `scripts/rebuild_project_library.py`
- Modify: `tests/test_project_library.py`
- Modify: `tests/test_complete_expansion.py`
- Modify: `tests/test_topic_keywords.py`
- Regenerate: `library/communities.json`
- Regenerate: `library/keywords.json`
- Regenerate: `library/topics.json`

**Step 1: 定义社区生命周期**

社区状态固定为：

```text
seed -> observed -> active
                  -> quarantined
```

- 四个种子社区永远为 `seed`；
- 新社区必须来自相关全站搜索结果或正文中的 `r/<name>` 引用；
- 自动 `active` 要求至少 3 个不同帖子、3 名不同作者，且每条来源通过柴油皮卡相关性门禁；
- 无关社区、机器人社区、比赛/职位/游戏等污染项进入 `quarantined`；
- 社区 key 统一为去掉 `r/` 后的 `casefold()`，保留首个规范显示名；
- 活动新社区从下一次运行起加入 listing 入口，本轮仍通过全站关键词搜索进入网络。

**Step 2: 定义关键词生命周期**

关键词状态固定为：

```text
seed/configured -> observed -> active
                            -> quarantined
```

自动 `active` 必须满足：

- 至少 2 个不同帖子和 2 名不同作者；
- 词本身包含平台、发动机、部件、故障或改装锚点，或在同一证据中与明确柴油锚点共现；
- 不能是停用词、残句、URL/UI 文本或 `better off`、`lot of work`、`down the road` 这类泛短语；
- 英文规范词、中文翻译、来源帖子、来源社区和父级话题齐全；
- 同义词合并到 variants，不生成重复活动词。

**Step 3: 话题库只登记证据合格话题**

- 正式与弱信号分开存储；
- 稳定 `topic_id` 按社区 + 语义规范 key 匹配；
- 话题合并不能跨社区；
- 无证据、无中文摘要或模型失败产生的空话题不写入正式库。

**Step 4: 从现有运行重建干净库**

`scripts/rebuild_project_library.py` 只读取已保存的 `analysis.json`、normalized 和 evidence gate，不联网。先把当前库备份到 `.local/library-backups/<timestamp>/`，再幂等重建三张库；不直接手工编辑 33,064 行 JSON。

**Step 5: 两轮复用测试**

第一轮输入新词/新社区证据，验证状态从 observed 到 active；第二轮创建任务时验证活动关键词进入全站搜索、活动社区进入 listing，且大小写不同不会重复。

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_project_library.py tests/test_complete_expansion.py tests/test_topic_keywords.py -q
```

Expected: 无关社区不再 approved/active，活动关键词不包含已知泛短语。

**Step 6: Commit**

```powershell
git add src/opportunity_radar/library.py src/opportunity_radar/keywords.py src/opportunity_radar/cli_app.py scripts/rebuild_project_library.py tests/test_project_library.py tests/test_complete_expansion.py tests/test_topic_keywords.py library
git commit -m "fix: make discovery libraries self-cleaning and reusable"
```

## Task 5: 使 365 天 Reddit 采集与 DeepSeek 分析可证明、可续跑

**Files:**
- Modify: `src/opportunity_radar/models.py`
- Modify: `src/opportunity_radar/collector.py`
- Modify: `src/opportunity_radar/cli_app.py`
- Modify: `src/opportunity_radar/server.py`
- Modify: `opencli-plugin/opportunity-reddit/range-core.mjs`
- Modify: `opencli-plugin/opportunity-reddit/search-range-core.mjs`
- Modify: `opencli-plugin/opportunity-reddit/range-core.test.mjs`
- Modify: `opencli-plugin/opportunity-reddit/search-range-core.test.mjs`
- Modify: `tests/test_dynamic_collection.py`
- Modify: `tests/test_collection_and_deepseek.py`
- Modify: `tests/test_complete_expansion.py`

**Step 1: 固定 complete 的停止语义**

`complete` 不设置项目侧帖子数、关键词数和深读数上限，只在以下情况停止单个来源：达到开始日期、分页耗尽、用户取消、明确不可恢复错误。429/403 保存 cursor 和 query checkpoint，任务为 `incomplete` 且可续跑；不能写 `completed`。

**Step 2: 为关键词搜索保存独立覆盖**

每个活动关键词保存：请求日期、实际最早/最晚日期、页数、命中数、去重新增数、停止原因和状态。社区 listing 与 keyword search 的 coverage 分开，报告总覆盖不得只看四个社区。

**Step 3: 统一去重与新社区归属**

所有 listing/search 结果按 Reddit post ID 去重；帖子保留多个 `source_surfaces` 和 `source_queries`。全站搜索命中的社区允许进入本轮分析与图谱，不要求属于四个种子社区。

**Step 4: DeepSeek 失败隔离和批次恢复**

- 每篇帖子分析独立 checkpoint；
- 401 立即失败并给中文配置提示；
- 404 区分 endpoint 与 model；
- 429/超时按指数退避，保存批次；
- 无效 JSON 只重试当前帖子；
- 全部模型调用失败时不导出正式话题报告；
- 部分帖子成功时可继续聚类，但报告显示失败数和覆盖限制。

**Step 5: 运行自动化测试**

```powershell
node --test .\opencli-plugin\opportunity-reddit\*.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_dynamic_collection.py tests/test_collection_and_deepseek.py tests/test_complete_expansion.py -q
```

Expected: 分页、日期边界、无上限、断点、429 和同轮扩词全部通过。

**Step 6: Commit**

```powershell
git add src/opportunity_radar/models.py src/opportunity_radar/collector.py src/opportunity_radar/cli_app.py src/opportunity_radar/server.py opencli-plugin/opportunity-reddit tests/test_dynamic_collection.py tests/test_collection_and_deepseek.py tests/test_complete_expansion.py
git commit -m "fix: make annual Reddit research resumable and coverage-aware"
```

## Task 6: 将 Hot30 的 discovery 与多平台主题检索合并成一个完整功能

**Files:**
- Modify: `src/opportunity_radar/last30days_adapter.py`
- Modify: `src/opportunity_radar/hot30_overview.py`
- Modify: `src/opportunity_radar/dashboard.py`
- Modify: `src/opportunity_radar/server.py`
- Modify: `schemas/hot30_overview.schema.json`
- Modify: `tests/test_last30days_adapter.py`
- Modify: `tests/test_hot30_overview.py`
- Modify: `tests/test_web_server.py`

**Step 1: 一个按钮运行两个互补检索面**

同一个 Hot30 任务执行：

1. last30days 三段式 domain discovery：nominate → host/DeepSeek judgment → research → angles → finalize；
2. normal topic 多平台深度检索：Reddit、YouTube、TikTok、Instagram、Hacker News、GitHub、Polymarket、Digg 和可用 Web；
3. 按 canonical URL 和平台 item ID 合并去重；
4. DeepSeek 生成一份中文热点总览。

X 不进入默认 sources，也不显示“未配置 X”。

**Step 2: 明确平台状态与完成状态**

- `ok`、`no-results` 是已完成来源；
- `skipped-unconfigured`、`rate-limited`、`auth-failed`、`unreachable`、`timeout`、`schema-drift` 是未完整覆盖；
- 只要请求来源存在未完整覆盖，任务状态为 `degraded`，不能显示绿色“已完成”；
- 报告只列实际返回结果的平台，来源状态页列全部请求平台和修复提示；
- TikTok/Instagram 未配置时明确提示 `SCRAPECREATORS_API_KEY`，不误写成“没有讨论”。

**Step 3: 中文总览契约**

每个正式热点包含：中文标题、一句话摘要、讨论内容、用户/使用背景、痛点与需求、当前应对、为什么值得关注、机会假设、反向信号、证据数量、来源数量、参与度和可点击原始链接。英文原文默认折叠。至少 3 条独立证据，或至少 2 个独立平台，才能进入正式热点；其余进入观察区。

**Step 4: 相关性和污染控制**

柴油价格、泛宏观、通用汽车和无关技术内容只有在能解释柴油改装需求时才能进入观察区，不能挤占正式热点。每条证据先做实体/领域相关性判断，再做聚类，不能仅凭单个 `diesel` 单词通过。

**Step 5: Hot30 自动化测试**

测试 discovery 与 normal-topic 合并去重、中文字段、来源降级、无 X、无配置平台提示、弱信号门槛、重分析复用 raw source、不重复联网和取消/删除。

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_last30days_adapter.py tests/test_hot30_overview.py tests/test_web_server.py -q
```

Expected: 全部通过；0 证据不能得到正式热点；部分平台失败显示 degraded。

**Step 6: Commit**

```powershell
git add src/opportunity_radar/last30days_adapter.py src/opportunity_radar/hot30_overview.py src/opportunity_radar/dashboard.py src/opportunity_radar/server.py schemas/hot30_overview.schema.json tests/test_last30days_adapter.py tests/test_hot30_overview.py tests/test_web_server.py
git commit -m "feat: unify Hot30 discovery and multi-platform research"
```

## Task 7: 真实双闭环验收、文档和最终提交

**Files:**
- Modify: `README.md`
- Modify: `skills/opportunity-radar/references/report-contract.md`
- Create: `docs/acceptance/2026-09-04-release-acceptance.md`
- Create: `configs/acceptance_hot30.json`

**Step 1: 从干净检出目录安装和启动**

使用 Git 跟踪内容创建临时干净工作目录，按 README 执行安装、OpenCLI 插件安装、`radar doctor` 和 `radar serve`。不复用开发工作区的未跟踪代码，允许复用本机认证配置但不复制凭据。

**Step 2: 真实 Hot30 验收**

从网页以“北美柴油皮卡改装”为主题启动 Hot30。验收：

- 产生 `analysis.json`、`brief.html`、`brief.md`、`source_status.json`；
- 正式热点全中文且每项可回源；
- discovery 与 normal-topic 证据已合并去重；
- 未配置/失败来源显示 degraded 和明确原因；
- 页面可打开、删除和重新分析。

**Step 3: 真实 365 天 complete 验收**

从网页选择最近 365 天、`complete`、DeepSeek，使用四个种子社区和活动关键词库。允许按 checkpoint 多次 resume，直到所有社区 listing 和所有已启动 keyword query 均到达日期边界或明确分页耗尽。

最终只接受两种结果：

- `complete`：所有来源覆盖状态完整，生成中文 JSON/HTML/Excel；
- `partial`：因 Reddit 可观测边界或持续限流无法到达起点，仍生成带限制说明的研究产物，但发布验收明确记为“部分覆盖”，不得称为全年全量。

无论哪种结果，必须证明：关键词全站检索确实执行、四社区以外相关帖子能进入分析、库自动增加可信词/社区、下一轮能复用、DeepSeek 不使用规则替代。

**Step 4: 产物一致性验收**

检查：

- 图谱无重复/零话题社区；
- 社区点击、话题预览、完整报告和手机视图可用；
- Excel 外链实际可点击且存在原始 URL 备份；
- 正式话题具有中文摘要、Seller Insight、场景、JTBD、需求、痛点、后果、现有方案、方案不足、产品判断、反向观点、验证问题和证据；
- HTML/Excel/JSON 核心数字逐项一致；
- 产物和 Git diff 中无 Cookie/API Key。

**Step 5: 运行完整门禁**

```powershell
.\scripts\check_release.ps1
```

Expected: Python 157+ tests、Node 6+ tests、发布契约和真实产物检查全部通过。

**Step 6: 写验收记录**

`docs/acceptance/2026-09-04-release-acceptance.md` 记录两个 run ID、请求/实际日期、来源状态、帖子/评论/作者/话题/证据数量、失败与恢复过程、文件路径和未覆盖限制。不写凭据。

**Step 7: 最终提交并推送**

```powershell
git add README.md skills/opportunity-radar/references/report-contract.md docs/acceptance/2026-09-04-release-acceptance.md configs/acceptance_hot30.json
git commit -m "docs: record Opportunity Radar release acceptance"
git status --short
git push origin main
```

Expected: 推送前工作区只剩明确不提交的 `.local/` 和本地测试缓存；向用户返回 commit hash、全年 run ID、Hot30 run ID、报告/Excel 路径和真实覆盖状态。

## Final acceptance checklist

- [ ] 网页可选择 30/90/180/365 天和自定义日期。
- [ ] 全年 complete 使用四个种子社区 + 活动关键词 Reddit 全站搜索。
- [ ] 新社区/关键词经过证据门禁后自动进入下一轮，大小写不重复。
- [ ] partial、429、403、取消和失败均可续跑且不会伪装完成。
- [ ] DeepSeek 完成帖子 VOC 和话题聚类，不使用规则正式话题。
- [ ] 图谱只包含至少一个正式话题的社区。
- [ ] 点击社区不报错，移动端不空白。
- [ ] Excel 证据外链在 Excel/WPS 可点击。
- [ ] Skill 从干净 clone 安装，UTF-8 和 PowerShell 检查通过。
- [ ] Hot30 合并 discovery 和多平台主题研究，中文总览可回源。
- [ ] HTML、Excel、JSON 的核心数字完全一致。
- [ ] GitHub 不包含任何 API Key、Cookie 或本机绝对认证路径。
