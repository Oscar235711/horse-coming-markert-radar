# 0831 对话交接：Reddit 产品机会雷达 V1.2 与报告可视化

交接日期：**2026-08-31，Asia/Shanghai**。本文件用于切换到下一个对话，避免长上下文把计划、历史状态、测试结果和真实采集结果混为一谈。

本次交接已重新核对本地 Git、远程分支/标签、正式运行 JSON、现有源码及测试。除本文件外，本次交接没有修改业务代码、重新采集、调用模型、提交或推送。

## 1. 接手后先记住这 8 件事

1. 已有真实报告：`formal-us-lighting-20260829-r3`，包含 **3 个正式机会**。不要再把旧的零数据 pilot 当作最新结果。
2. 正式机会通过的是当前规则和本市场配置门槛，不等于完成商业可行性验证。该 run 仍然是 `partial`，样本与画像仍不充分。
3. 2026-08-30 已完成词云和 Audience Map 展示层改造，并用同一份正式运行数据重生成 HTML。**这些代码改动仍在本地，未提交、未推送。**
4. 最新全量 Node 测试：**143/143 通过**，2026-08-31 本次交接重新运行确认；Windows 照明入口检查通过。
5. 实际浏览器页面的视觉验收未完成。自动浏览器访问 `file://` 被安全策略明确阻止；已完成的是本地 DOM/Canvas 交互验证与静态图形检查，不能改写成“浏览器已验收”。
6. “匹配证据数”“合格证据数”“画像有效样本数”不是同一口径，详见第 4 节。
7. 当前分支是 `codex/automotive-lighting-reddit-radar`，不是 `main`，也不是用于视觉参考的 `feature/community-radar`。
8. **不要执行旧文档中的 `git restore .`、重置或清理建议。** 当前工作树里有本轮真实功能改动，必须保留。

## 2. 仓库和版本位置

- GitHub：<https://github.com/Oscar235711/horse-coming-markert-radar>
- 当前本地工作树文件夹：`horse-coming-markert-radar-codex-automotive-lighting`。
- 本文件位于该工作树的 `docs/HANDOFF-0831.md`；后续所有相对路径、命令均以该工作树根目录为基准。
- HEAD：`dca96068972a7eab32b1424f3545af46476d159a`。
- 当前分支：`codex/automotive-lighting-reddit-radar`。

2026-08-31 通过 `git ls-remote --heads --tags origin` 核验：

| 对象 | 对应提交 | 状态 |
| --- | --- | --- |
| 本地 HEAD / 远程照明分支 | `dca9606` | 两者相同；不包含未提交的新版可视化 |
| `main` | `6b648d6` | 保留原基线 |
| `v1.0.0` | `6b648d6` | 远程存在 |
| `v1.1.0` | `5ed1de6` | 远程存在，未覆盖 |
| `v1.2.0` | `f8c8a57` | 远程存在；这是 annotated tag 解引用后的提交 |
| `v1.2.1` | `dca9606` | **仅本地存在，远程标签列表没有它** |
| `feature/community-radar` | `e461567` | 远程存在，用户称“改装分支”；仅借鉴其交互 |

注意：annotated tag 自身的对象 SHA 与对应 commit SHA 不同。例如本地 `v1.2.1` 标签对象是 `eca5e59`，目标提交是 `dca9606`。不要把二者混淆。

因此，仅重新 clone GitHub 照明分支，拿不到本地最新可视化改动，也拿不到 `.local/` 下的报告与原始数据。

## 3. 本对话已完成的工作

### 3.1 V1.2 数据与分析链路

下面是已落在源码中的能力，不是待执行的设计清单；但“有实现/通过测试”不代表每条外部通道都已完成真实运行验收。

| 能力 | 主要文件 | 当前实现边界 |
| --- | --- | --- |
| Reddit 标准化、去重、分阶段采集 | `src/radar-core.mjs`、`src/radar-pipeline.mjs` | 支持本地 OpenCLI 和 public JSON，标准 JSON/JSONL 输出 |
| 通用证据筛选与质量评分 | `src/evidence-quality.mjs`、`configs/rules/universal_evidence_rules.json` | 区分直接体验、专业意见、需求与低质内容；保留排除审计；可配置市场规则 |
| 产品机会和痛点分离 | `src/opportunity-engine.mjs` | `validated_entry`、`emerging_product`、`adjacent_bundle`；正式机会与候选信号分开 |
| 高质量作者公开活动深挖 | `src/author-deep-dive.mjs` | 作者资格、相关性过滤、数量/时间限制、失败记录、公开自述上下文 |
| 关键词发现与第二轮探索 | `src/keyword-discovery.mjs`、`src/keyword-cloud.mjs` | 保留来源证据、用户、社区、种子词、评分；探索词不自动升级为正式配置 |
| 用户画像门槛和聚合 | `src/persona-engine.mjs` | 样本不足返回 `insufficient_sample`，不凭少量作者发布人群结论 |
| 断点和失败历史 | `src/checkpoint-store.mjs`、`src/radar-pipeline.mjs` | 输入哈希复用、配置漂移判断、失败重试；当前失败与累计失败尝试分开 |
| 可选模型增补 | `src/llm-client.mjs`、`schemas/dsv4pro-enrichment.schema.json` | Schema/引用校验；错误、未知证据 ID、超时等回退规则，不允许模型绕过门槛 |
| CLI、夜间配置与运行边界 | `src/radar-cli.mjs`、`src/radar-runner.mjs`、`scripts/run-radar.mjs` | overnight profile、运行时上限、子进程终止边界、模型参数 |
| Hermes 双语交接 | `.agents/HERMES_HANDOFF_V1.2.md`、`.agents/PROGRESS.md`、`.agents/OUTBOX.md` | 有运行前检查、恢复流程、固定输出格式及禁止擅自发布的约束 |
| Actions 入口 | `.github/workflows/reddit-lighting-radar.yml` | 手动与定时触发定义、public-json mini 默认配置、只读权限、Secrets 和 artifacts |

历史 Task 7–10 的主要完成点：

- Task 7：checkpoint / 失败尝试审计、OpenCLI 合成评论精度信息传播、作者失败字段统一。
- Task 8：DSV4Pro 引用与 Schema 校验、规则回退、无效顶层输出拒绝。仓库没有单独的 `task-8-report.md`，不要虚构该文件。
- Task 9：overnight 配置、CLI/PowerShell 入口、运行时限制、Hermes 双语交接和进程树终止问题处理。
- Task 10：runner/manifest/artifacts 集成、输出口径测试、Actions 默认配置和文档收口。

可追溯提交包括：`334ec2d`、`95dd246`、`4f30318`、`57c4e9e`、`675c513`、`1028f19`。当前 143 项测试已通过，旧 Task 9 文档中“其他模块测试仍失败”的描述是当时状态，不是现在的阻塞项。

### 3.2 从失败 pilot 到三机会正式报告

用户明确否定了旧试跑产物，要求先产出至少 3 个正式机会。

- 旧 pilot：`.local/runs/v12-pilot-20260829-continue/`。public-json 搜索组全部 fetch 失败，0 候选；它只能说明当时通道失败，不能说明市场没有需求。
- 后续切到本地 OpenCLI，修复 Windows `.cmd` 查询参数保留、扩大搜索覆盖、优化续跑及 US 证据排序，并补充尾灯搜索。
- 使用公开配置中的美国车灯专属门槛，最终生成 `formal-us-lighting-20260829-r3`。
- 对应提交：`5e8e8f2`、`5139b99`、`4d5a9ea`、`a34b04e`、`dca9606`。

不要把旧 run 覆盖掉，也不要把旧文档里的“所有运行都是零机会”当成当前事实。

### 3.3 2026-08-30 可视化改造

用户已确认的参考：

- 词云：<https://cosx.org/2016/08/wordcloud2/>。
- Audience Map：`feature/community-radar` 分支 `e461567` 的 `src/opportunity_radar/report.py`。

本轮做的是展示层迁移，没有合并改装分支的 Python 数据处理架构。

**词云：**

- 将标签按钮堆叠改为 Canvas 文字掩码避让与螺旋排布。
- 字号由现有展示权重决定；同权重同字号；混合 0 / ±90 度旋转；类别决定颜色。
- 支持悬停数值、点击证据详情、搜索、类别/状态/最低分筛选、重置。
- 有完整关键词列表作为可访问替代入口；若有词未放入画布，显式显示数量，不静默丢词。
- 正式数据中 **34/34 个词已放入画布**。
- 这是自包含的 WordCloud2 风格实现，不是安装了 R 的 wordcloud2 包，也没有依赖外部 CDN。

**Audience Map：**

- 默认社区空心节点总览；可切换全部产品—社区关系。
- 点击社区查看直接关联产品；点击产品反查社区。
- 左侧社区/产品列表、搜索、类别筛选，右侧可关闭详情，支持返回上一级和全局重置。
- 社区下钻进入产品时，代表证据限定在所选社区；相关社区列表仍保留该产品全部匹配关联。
- 产品节点大小按机会评分，社区节点大小按关联产品数；没有人口节点，没有把节点大小解释为人数。
- 当前正式 run 是 **6 社区 + 3 产品 = 9 节点，14 条证据关系**。

**保持不变：** 采集配置、规则评分、机会结论和四份源 JSON；3 个正式机会及所有其他报告 tab 继续保留。

## 4. 正式 run 的真实状态与统计口径

运行目录：`.local/runs/formal-us-lighting-20260829-r3/`。

### 4.1 状态

```text
run_id             formal-us-lighting-20260829-r3
transport          opencli
status             partial
sample_status      insufficient
persona_status     insufficient_sample
unresolved_failures 4
analysis active_result rules
LLM status         not_requested
```

**这份正式报告是规则分析结果，不是 DSV4Pro 生成结果。** 仓库支持模型调用与模型回退，不等于本 run 调用了模型。

### 4.2 采集与探索

| 指标 | 数值 | 来源 |
| --- | ---: | --- |
| 候选帖子 / 详情帖子 | 231 / 231 | `manifest.counts` |
| 评论 | 2,308 | `manifest.counts.comments` |
| 作者候选 / 成功采集作者 | 11 / 7 | `manifest.counts` |
| 保留作者活动 | 54 | `manifest.counts.author_activities` |
| 关键词候选 / 词云词项 | 38 / 34 | `manifest.counts` |
| 第二轮词 / 新增帖子 / 第二轮失败 | 9 / 0 / 0 | `manifest.counts` |
| 正式机会 / 候选信号 | 3 / 4 | `manifest.counts` |
| 当前未解决失败 | 4 | `manifest.unresolved_failures` |

4 条未解决失败属于公开作者活动查询无返回。保持失败记录，不补造数据。累计尝试数和当前未解决数不同，分别查看 `failure_attempts.jsonl` 与 `failures.jsonl`。

### 4.3 三个正式产品机会

来自 `analysis.json` 的实际字段：

| 产品 / ID | 分数 | 合格用户 | 合格证据 | 全部匹配证据 | 关联社区 |
| --- | ---: | ---: | ---: | ---: | ---: |
| LED 头灯灯泡套装 / `led-headlight-bulb-kit` | 90 | 19 | 19 | 54 | 4 |
| 雾灯套装 / `fog-light-kit` | 84 | 10 | 11 | 20 | 5 |
| 尾灯与刹车灯套装 / `tail-brake-light-kit` | 68 | 7 | 7 | 14 | 5 |

三者都是 `validated_entry`，`threshold_check.passed=true`。

**必须保留的门槛说明：**

- `src/opportunity-engine.mjs` 的通用 `validated_entry.unique_users` 默认是 **8**。
- `configs/automotive_lighting_us_full.json` 明确覆盖为 **7**；另有社区 ≥2、直接体验 ≥3、评分 ≥55 等检查。
- 本 run 三个机会记录的 `threshold_check.required.unique_users` 都是 7；尾灯机会依赖该市场覆盖项才能过此项门槛。
- 不要把该覆盖项复制成所有市场的通用规则，不要为了凑机会数继续静默降低门槛，也不要声称本 run 使用了完全未调整的通用门槛。

### 4.4 证据口径：不能只用 high + medium 作为合格数

2026-08-31 直接汇总 `analysis.evidence`：

| 口径 | 数量 |
| --- | ---: |
| 总证据 | 2,539 |
| high / medium / weak / noise | 15 / 124 / 311 / 2,089 |
| `quality.eligible=true` | **120** |
| `quality.eligible=false` | **2,419** |

因此 15 + 124 = 139 不是 `eligible=true` 的 120；质量档位与最终资格不可混为一谈。

**2026-08-31 交接核验补充发现，尚未修复：** 正式机会记录同时有 `evidence_ids`（全部匹配）和 `qualified_evidence_ids`（合格子集）。目前报告机会卡和 Audience Map 的证据投影会使用 `evidence_ids`，不能因此宣称“所有展示证据均合格”。后续若处理证据库质量，应检查 `src/radar-core.mjs::buildAudienceMap`、`src/radar-report.mjs` 和 `src/report-visuals.mjs` 的展示口径；本次只记录事实，没有修改筛选逻辑。

### 4.5 画像仍不能发布

`personas.json` 的实际计数：

- 画像专用合格证据 70 / 门槛 200。
- 画像专用合格用户 67 / 门槛 60。
- 画像可用深挖作者 0 / 门槛 30。
- 已发布群组 0，`clusters=[]`。

这些计数还经过画像引擎的角色、资格、来源和作者归一化处理，不能拿全局 120 条合格证据或成功采集的 7 个作者替代。也不能仅凭 `deep_dive_authors=0` 就说“完全没有抓过作者”。若后续需要诊断 7 → 0 的具体原因，应追踪 `normalizeAuthorArtifacts` 和来源资格，本次没有做该项根因验收。

## 5. 当前未提交改动：下个对话必须保护

0831 交接写入前的 `git status --short`：

```text
 M src/radar-report.mjs
?? docs/superpowers/plans/2026-08-30-report-visuals.md
?? scripts/render-existing-report.mjs
?? src/report-visuals.mjs
?? tests/report-visuals.test.mjs
```

本次又新增本文件 `docs/HANDOFF-0831.md`。以上文件均属于待保留的本轮工作，不是可以清掉的临时噪音。

| 文件 | 职责 |
| --- | --- |
| `src/report-visuals.mjs` | `selectGraphView`、`packCloudWords`、内嵌样式、`installReportVisuals`、`reportVisualScript` |
| `src/radar-report.mjs` | 报告模板；接入新图谱/词云布局和序列化脚本 |
| `scripts/render-existing-report.mjs` | 仅读保存的 JSON 重生成 HTML；备份旧 HTML，检查源 JSON 不变 |
| `tests/report-visuals.test.mjs` | 7 项针对关系筛选、邻居范围、排布碰撞/边界、字号、脚本安全的测试 |
| `docs/superpowers/plans/2026-08-30-report-visuals.md` | 已批准设计、执行记录和未完成的浏览器验收 |

`.local/` 被 Git 忽略，以下内容只在本机：

- 原始采集、checkpoints、运行 JSON 和 report。
- `.local/visual-qa/check.mjs`：本地 DOM + native Canvas 验证脚本。
- `.local/visual-qa/node_modules/`：此次验证用的 `linkedom` 等依赖；不是生产报告依赖。
- native Canvas / SVG 渲染使用本机工作区依赖包。不要把个人机器路径写入生产配置或提交依赖目录。

## 6. 产物与验证情况

### 6.1 可交付文件

以下都在正式 run 目录：

| 文件 | 含义 |
| --- | --- |
| `report.html` | 最新可视化版，最后修改于 2026-08-30 13:52:18（本机时间） |
| `report.before-visual-refresh.html` | 2026-08-29 16:46:07 的旧版备份 |
| `analysis.json` | 分析、证据、机会、引擎状态等 |
| `audience_map.json` | 产品—社区图数据 |
| `keyword_cloud.json` | 词、权重、类别、状态和证据 |
| `opportunities.json`、`personas.json` | 机会和画像专用产物 |
| `quality_evidence.jsonl`、`excluded_evidence.jsonl` | 资格分流结果 |
| `wordcloud-visual-qa.png` | native Canvas 词云图形预览 |
| `map-overview-visual-qa.png`、`map-relations-visual-qa.png`、`map-community-visual-qa.png` | SVG 图谱静态预览 |
| `visual-qa.json` | 本地 DOM/Canvas 交互检查结果，不是浏览器验收凭证 |

### 6.2 已验证

- 2026-08-30：143 项 Node 测试、`LIGHTING_INTERFACE_OK`、`git diff --check` 通过。
- 2026-08-31 本次交接重新运行：**143 tests / 143 pass / 0 fail**，`LIGHTING_INTERFACE_OK`。
- 2026-08-30 本地 DOM/Canvas harness：词云 34/34，图谱 6 社区 / 3 产品 / 14 边；悬停、点击、空搜索、筛选、重置、下钻、反查、证据范围、关闭和返回均通过。
- 静态词云与图谱图形已检查。它们不是实际完整 HTML 页面的浏览器截图。
- 旧版本曾完成便携配置、运行时、项目工具、Windows UTF-8 等检查，见 `docs/task-10-report.md`；本次 0831 只重新跑了全量 Node 与 lighting interface，不冒充重新跑过所有历史检查。

### 6.3 尚未验证，不能宣称完成

- 实际浏览器中的完整页面排版、窄屏响应式、抽屉遮挡情况，以及浏览器字体/缩放下的指针命中。
- Browser Use 曾明确阻止 `file://` 页面访问；没有换浏览器、localhost 或 CDP 绕过。后续遵守当前工具的安全边界，可由用户手动打开验收。
- GitHub Actions 定义和静态契约已存在，但没有本文件可证实的 GitHub 云端 Reddit 成功采集记录。不要把本地 OpenCLI 成功等同于 Actions 成功。
- 供应链、MOQ、利润、制造、运费、退货率、法规适用性等商业事实未因此补齐；保持未知/待验证。

### 6.4 源 JSON 校验值

2026-08-31 重算 SHA-256，与 0830 重渲染记录一致，说明本轮可视化没有改变这些源文件：

```text
analysis.json
43746c6a46e146c746bb3eeb6a7bc337bdae5f15ac2f3272074a4bcf2d8137bb

audience_map.json
f53d9599dacc28e3bf62c48de4a8a76110bedd2e08f81672b6331772444c15ce

keyword_cloud.json
1ca664c332e9f2975f7aa7be308f4eed4b325785f5b6dea71ec04e56af56e219

manifest.json
93454cac9cbae6550dfb059a8ea817f910b0410773d98acfa0b062ebce7b7fb3
```

## 7. 已确认的业务与数据边界

- 当前研究仅美国，不做季节性预测。未知地域不擅自升级为美国事实。
- 保留原 14 个锚点词及受控扩展。深挖发现词进入候选/探索池，不自动改正式配置；品牌和新黑话同样需要审核。
- 用户要的是有证据支持的可销售产品、已有市场切入空间、潜力品类或邻近配套产品；“密封不好”等抱怨本身不是产品机会。
- 市场专属自定义规则是可选配置，不能移除通用强制排除或伪造证据。
- 图谱始终表达产品—社区—证据，不把社区节点大小写成人群规模。
- 报告用保存的 JSON 生成；单纯刷新 HTML 不重新采集、不调用模型。
- 作者深挖仅涉及公开、研究相关内容。当前中英文设计和代码的规则是：明确自述年龄转年龄段，明确自述地域最多州/大区；保留相关预算和使用场景，不模型推断收入；种族、健康及精确地址不作为画像变量。群体自述聚合至少 10 名合格用户，典型代表不展示个人敏感属性。早期关于放开人口属性的对话不能替代最终落盘规则，详见中文设计第 7.2 节。
- OpenCLI 某些评论使用合成 ID，链接仅精确到帖子；已保留 `precision` / `link_precision` 等标记，不得写成真实评论 ID 或评论级 permalink。
- 凭据只读环境存在性，不打印 `.env`、token、Cookie；不提交 `.local/`、个人路径和原始用户活动。
- 保留 `main` 和历史版本，不强推。历史发布授权不等于“现在已经发布”；后续发布按用户当时的具体指令执行。

## 8. 未完成事项与建议接续顺序

本节是待办建议，不是已完成承诺；本次 0831 请求只授权整理交接文件。

1. **人工视觉验收新版报告。** 用户手动打开最新 HTML，核对宽屏/窄屏、图谱下钻、详情关闭、返回、词云点击。浏览器工具有明确安全拒绝时不得绕过。
2. **若用户要继续改进证据质量，先审查展示层合格证据口径。** 当前 `evidence_ids` 和 `qualified_evidence_ids` 不相同；不要仅因正式机会过门槛，就把所有附带原文当合格证据。
3. **清理关键词质量和权重饱和需另开明确实现范围。** 现有词库有 `headlight new headlight`、`headlight and headlight`、`harness both bulb` 等噪声/重复短语，且多词权重达到 100。0830 改造刻意没有偷偷过滤或重评分。
4. **需要画像时再补样本和追踪作者资格流转。** 当前不能发布人群分群；不能把作者采集数直接当画像可用作者数。
5. **按后续发布指令处理本地改动。** 先看 diff、重验，再提交照明分支并按授权推送。`v1.2.1` 仍未在远程；不要未核验就宣称标签已发布，更不要移动既有 tag。
6. **云端远程调用另做真实验收。** Actions 有定义，但 public-json 的历史网络失败尚不能证明云端能跑通。

无须为了接手而重新 clone、全量爬取、重建全部 V1.2、合并改装分支或重复询问已确认的可视化设计。

## 9. 接手时的最小核验命令

先进入当前照明工作树根目录。以下命令不读取凭据、不发帖、不触发采集：

```powershell
git status --short
git branch --show-current
git log -5 --oneline
Get-Content -Raw docs/HANDOFF-0831.md
Get-Content -Raw .local/runs/formal-us-lighting-20260829-r3/manifest.json
node --test "tests/*.test.mjs"
.\tests\verify-lighting-interface.ps1
git diff --check
```

需要重生成 HTML 才运行下面命令（会写 HTML，保留首次旧版备份；不采集、不调模型）：

```powershell
node scripts/render-existing-report.mjs .local/runs/formal-us-lighting-20260829-r3
```

如果 `.local/runs/formal-us-lighting-20260829-r3/` 不存在，先报告“当前机器没有本地运行产物”，不要生成假数据冒充正式 run。

## 10. 阅读优先级与旧文档陷阱

以“当前源码 / Git / 原始 JSON 的实测状态”为最高事实依据；本文件是 0831 快照，未来有新改动必须重新核对。

建议顺序：

1. 本文件。
2. `docs/superpowers/plans/2026-08-30-report-visuals.md`。
3. `.local/runs/formal-us-lighting-20260829-r3/manifest.json`、`analysis.json`、`personas.json`。
4. 要做夜间运行才读 `.agents/HERMES_HANDOFF_V1.2.md`，并核对 `.agents/PROGRESS.md` / `.agents/OUTBOX.md` 的日期。
5. 设计背景读 `docs/superpowers/specs/2026-08-27-reddit-market-intelligence-v1.2-design.zh-CN.md`；英文原版同目录保留。
6. `docs/HANDOFF-report-run-2026-08-28.md`、旧 Task 报告只当历史诊断依据。

明确过时或容易误读的旧内容：

- 旧 handoff 中“Windows Git 不能读该 worktree”的状态不应盲目套用；0831 Windows PowerShell 已能正常读 Git。
- 旧 handoff 中“正式机会为 0”“尚缺模块/测试失败”已被后续运行和当前测试更新。
- 旧文档建议清理 CRLF 改动的 `git restore .` 不能用于当前工作树。
- `.agents/OUTBOX.md` 同时有失败 pilot 与后来的正式报告，必须按日期/run_id 区分。
- 7 个成功采集作者不等于 7 个可用于画像的作者；6 个图谱社区不等于此次采集覆盖的全部社区。
- “本地已经实现”“本地已提交”“远程已推送”“报告业务样本充分”“浏览器已验收”是五件不同的事。

## 11. 可直接复制到下个对话的开场指令

> 请先完整读取 `horse-coming-markert-radar-codex-automotive-lighting/docs/HANDOFF-0831.md`，再核对当前分支、未提交改动和正式 run 的 manifest。该文件是截至 2026-08-31 的交接快照；遇到冲突，以当前源码、Git 和 JSON 实测结果为准。保护本地未提交的词云/Audience Map 改造，不执行清理或覆盖，不把旧 pilot 当最新报告，不把自动化通过说成浏览器视觉验收，也不要默认重新爬取或发布。先用简短中文说明你理解的已完成内容和仍待验证项，然后按我接下来的具体任务继续。
