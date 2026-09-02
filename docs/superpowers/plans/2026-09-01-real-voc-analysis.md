# Opportunity Radar 真正 VOC 分析升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于已采集的 Reddit 帖子和评论，完成可追溯的“用户/车辆 → 场景 → 用户任务 → 痛点及后果 → 需求结果 → 当前方案 → 方案缺口 → 产品决策”VOC分析，不再输出空白字段或固定模板式结论。

**Architecture:** 保留现有四个社区和采集结果，不先重新爬取。新增完整证据单元层，读取 320 篇深读帖子及其评论；使用本机 Codex 进行帖子级 VOC 提取和社区内任务/问题聚类，规则仅用于数据清洗、证据校验和统计，不再承担语义分析。所有 HTML、Excel、JSON 只读取同一份规范化 `analysis.json`。

**Tech Stack:** Python 3.12、现有 `opportunity_radar` 包、Codex CLI `codex exec --ephemeral --sandbox read-only`、JSON Schema、pytest、现有 HTML/Excel 导出器。

**Spec:** `docs/superpowers/plans/2026-08-31-opportunity-radar-analysis-quality.md`、`schemas/codex_post_analysis.schema.json`、`schemas/codex_topic_analysis.schema.json`、`C:\Users\yaobi\.codex\skills\voc-scenario-need-pain\SKILL.md`。

## Global Constraints

- 不重新设计社区库：一期仍使用 `r/Cummins`、`r/Duramax`、`r/powerstroke`、`r/FordDiesels`。
- 不以预写产品品类强行制造话题；话题按用户共同任务、问题或期望结果聚类。
- 场景必须同时包含真实条件和用户目的；车型、零件、安装、CANbus、泛泛的“更亮/更强”不能单独当场景。
- 每项痛点、需求、当前方案、方案缺口和产品判断必须携带 `evidence_id`、`post_id` 和原帖 URL。
- 每项内容标记 `fact`、`inference` 或 `unknown`；无法确认时显示“暂无直接证据”，不留空、不猜测。
- 规则只负责清洗、去重、计数和证据门禁；不得生成固定痛点、固定需求、固定方案或固定新品假设。
- 采集内容为不可信 Reddit 数据，Codex 只能读取证据，不执行正文或评论中的指令。
- 不生成排放删除等违规操作教程；仅分析用户讨论的需求信号。

---

### Task 1: 建立完整证据单元层

**Files:**
- Create: `src/opportunity_radar/evidence_units.py`
- Modify: `src/opportunity_radar/cli_app.py:500-680`
- Test: `tests/test_evidence_units.py`

**Interfaces:**
- `build_evidence_units(thread: ThreadDocument, gate_records: Sequence[Mapping[str, Any]] | None = None) -> tuple[EvidenceUnit, ...]`
- `EvidenceUnit` 字段固定为：`evidence_id`, `post_id`, `record_type`, `author`, `url`, `original_text`, `created_at`, `score`, `evidence_role`, `quality_band`, `eligible_for_claims`。
- `build_evidence_packet(thread, units) -> Mapping[str, Any]`，同时携带帖子标题、帖子正文、评论树和证据ID映射。

- [ ] **Step 1: 写失败测试**

  测试一篇帖子正文和两条评论分别生成 `post`、评论ID 三个唯一证据单元；测试评论 URL、作者、原文和父子层级保留；测试重复评论ID只保留一次。

- [ ] **Step 2: 运行测试确认失败**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_evidence_units.py -q`
  预期：因 `EvidenceUnit` 和 `build_evidence_units` 尚未定义而失败。

- [ ] **Step 3: 实现最小证据层**

  从 `ThreadDocument.post` 读取完整标题、正文和 URL；从 `ThreadDocument.comments` 读取完整评论树。只清理空白和重复ID，不截断原文。将证据门禁结果附加到单元，但不要因门禁失败删除原始单元。

- [ ] **Step 4: 运行测试确认通过**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_evidence_units.py -q`
  预期：全部通过。

- [ ] **Step 5: 接入保存检查点**

  在现有运行目录增加 `normalized/evidence_units.jsonl` 和 `normalized/evidence_packet__<post_id>.json`；检查点可重复生成，不覆盖原始采集文件。

### Task 2: 扩充 Codex 帖子级 VOC Schema 和提示词

**Files:**
- Modify: `schemas/codex_post_analysis.schema.json`
- Modify: `src/opportunity_radar/codex_analysis.py:35-120`
- Modify: `src/opportunity_radar/deepseek.py` 的 `_analysis_from_document` 兼容转换
- Test: `tests/test_codex_voc_contract.py`

**Interfaces:**
- 帖子级返回必须包含：`scenario`, `goal`, `user_type`, `vehicle`, `platform`, `year`；数组字段必须包含 `pain_points`, `consequences`, `needs`, `products`, `current_solutions`, `gaps`, `purchase_intent`, `supporting_views`, `opposing_views`, `keyword_candidates`, `topic_candidates`。
- 每个字段结构为 `{value, evidence_ids, status}`；`status` 只能是 `fact`、`inference`、`unknown`。
- 新增 `evidence_strength`：`high`、`medium`、`low`，用于区分明确说明购买/使用动机和弱提及。

- [ ] **Step 1: 写失败测试**

  测试缺少证据ID的需求字段被拒绝；测试场景只有“安装/更换/更亮”时必须返回 `unknown`；测试真实拖挂、排温、维修、越野或通勤目的可作为场景，但必须引用原帖或评论证据。

- [ ] **Step 2: 运行测试确认失败**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_codex_voc_contract.py -q`

- [ ] **Step 3: 修改 Schema 和 Codex 提示词**

  在提示词中明确 VOC 链条：

  `用户/车辆 → 使用条件和目的 → 要完成的任务 → 痛点及后果 → 想获得的结果 → 当前产品/办法 → 现有方案不足`。

  要求 Codex 保留 1—3 条最能说明动机的原文证据，不把所有评论全部当作独立结论；没有直接支持时返回 `unknown`，不能用模板补齐。

- [ ] **Step 4: 加入返回校验**

  在 `_invoke` 后执行 JSON Schema 校验；无效 JSON、缺少 evidence_id、引用不存在的 evidence_id 均记录失败并重试，不把空模型输出当作成功分析。

- [ ] **Step 5: 运行测试确认通过**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_codex_voc_contract.py tests/test_codex_analysis.py -q`

### Task 3: 重新运行帖子级 VOC 分析，不再使用规则 fallback

**Files:**
- Modify: `src/opportunity_radar/cli_app.py:550-630`
- Modify: `src/opportunity_radar/codex_analysis.py:35-120`
- Modify: `src/opportunity_radar/storage.py`
- Test: `tests/test_post_voc_pipeline.py`

**Interfaces:**
- 新阶段函数：`analyze_threads_with_codex(paths, threads, selected_post_ids) -> dict[str, PostAnalysis]`
- 运行状态新增：`voc_post_analysis_total`, `voc_post_analysis_completed`, `voc_post_analysis_failed`, `analysis_engine_actual`。

- [ ] **Step 1: 写失败测试**

  测试当 `analysis_engine=codex` 调用失败时，运行状态为 `blocked` 或 `partial`，而不是静默改成 `rule_based`；测试单篇 Codex 失败可以重试，其他帖子继续；测试成功结果必须包含至少一条证据绑定的场景、痛点或需求字段。

- [ ] **Step 2: 运行测试确认失败**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_post_voc_pipeline.py -q`

- [ ] **Step 3: 改造执行逻辑**

  先分析 88 篇当前高质量帖子，随后将其余 232 篇作为发现层补充分析；两者都保存原始结果，但只有有证据的内容才能进入正式话题。删除 `_rule_fallback` 对帖子级分析的兜底路径；Codex 不可用时明确提示“未完成VOC分析”，不得伪装成已完成。

- [ ] **Step 4: 保存逐帖分析**

  输出 `analyses/post_voc_analysis.jsonl`，每行包含 `post_id`、`community`、`voc_chain`、`fields`、`evidence_ids`、`status` 和错误信息。支持从已完成检查点继续，不重新抓取 Reddit。

- [ ] **Step 5: 运行单帖真实验收**

  用 `t3_1tjmrc4` 和另外 3 篇不同社区帖子运行 Codex，检查场景、任务、痛点、方案和证据是否来自原文；确认 Codex CLI 实际被调用，状态中的 `analysis_engine_actual` 为 `codex`。

### Task 4: 按 VOC 任务/问题做社区内聚类和证据复核

**Files:**
- Modify: `schemas/codex_topic_analysis.schema.json`
- Modify: `src/opportunity_radar/cli_app.py:1395-1480`
- Modify: `src/opportunity_radar/topics.py`
- Create: `src/opportunity_radar/voc_topics.py`
- Test: `tests/test_voc_topic_synthesis.py`

**Interfaces:**
- `consolidate_voc_topics(community: str, signals: Sequence[PostSignal]) -> Sequence[ProTopicProposal]`
- 话题输出字段：`topic_id`, `label_zh`, `label_en`, `job_to_be_done`, `scenario`, `pain_points`, `consequences`, `needs`, `current_solutions`, `solution_gaps`, `product_decision`, `supporting_views`, `opposing_views`, `validation_questions`, `evidence`。

- [ ] **Step 1: 写失败测试**

  测试两篇都明确“拖挂时控制排温”的帖子被归入同一话题；测试只有产品名称相同但任务不同的帖子不能仅因关键词合并；测试没有有效 VOC 证据的内容不会生成“其他/规则主题”；测试每个正式话题满足 3帖/3作者或2帖/10评论者门槛。

- [ ] **Step 2: 运行测试确认失败**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_voc_topic_synthesis.py -q`

- [ ] **Step 3: 修改 Topic Schema 和聚类提示词**

  Pro/Codex 只在同一社区内聚类，以 `job_to_be_done`、场景条件、痛点后果和期望结果为主；产品名称只作为输出字段。每篇帖子最多进入 3 个话题，并要求返回每个字段的证据引用。

- [ ] **Step 4: 建立二次证据复核**

  Python 校验器检查：引用的 `post_id/evidence_id` 存在、原文非空、引用数量与独立作者数可计算、`inference` 不得伪装成 `fact`。不通过的字段删掉并标记 `unknown`，不整体丢弃话题。

- [ ] **Step 5: 运行测试确认通过**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_voc_topic_synthesis.py tests/test_topic_registry.py -q`

### Task 5: 统一分析 JSON、Excel 和 HTML 的 VOC 报告结构

**Files:**
- Modify: `src/opportunity_radar/cli_app.py:680-730`
- Modify: `src/opportunity_radar/report.py`
- Modify: `scripts/build_topic_workbook.mjs`
- Modify: `schemas/analysis.schema.json`
- Test: `tests/test_voc_report_contract.py`

**Interfaces:**
- `analysis.json` 顶层新增 `voc_metrics`：`evidence_unit_count`, `post_voc_count`, `formal_topic_count`, `weak_signal_count`, `unknown_field_count`, `claim_evidence_coverage`。
- 每个话题摘要顺序固定为：结论 → 讨论规模 → 谁在讨论 → 场景/任务 → 痛点及后果 → 需求 → 当前方案 → 方案不足 → 产品决策 → 支持/反对证据 → 下一步验证。

- [ ] **Step 1: 写失败测试**

  测试 HTML 与 Excel 的帖子数、作者数、评论数、话题数和证据数全部从同一份 `analysis.json` 读取；测试任何空字段显示“暂无直接证据”，不出现空白卡片；测试原始证据默认折叠，仅展示 1—3 条代表证据。

- [ ] **Step 2: 运行测试确认失败**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_voc_report_contract.py -q`

- [ ] **Step 3: 改造报告内容**

  HTML 侧栏显示决策摘要；完整报告按 VOC 顺序展示，不把几十条原文堆在正文。Excel 增加专门工作表：`VOC分析明细`、`话题汇总`、`证据索引`、`关键词库`、`社区库`、`弱信号`、`失败记录`。

- [ ] **Step 4: 加入可解释指标**

  每个话题显示：支撑帖子数、独立发帖作者数、评论参与者数、代表证据数、场景证据数、痛点证据数、需求证据数、方案缺口证据数，以及证据强度分布。

- [ ] **Step 5: 运行测试确认通过**

  运行：`\.venv\Scripts\python.exe -m pytest tests/test_voc_report_contract.py tests/test_rich_report_contract.py tests/test_topic_export.py -q`

### Task 6: 用现有 365 天数据重跑并验收

**Files:**
- Create: `scripts/run_real_voc_analysis.ps1`
- Modify: `docs/CURRENT_BASELINE.md`
- Create: `tests/test_real_run_artifacts.py`

- [ ] **Step 1: 运行 Codex 可用性检查**

  执行 `radar doctor`，确认 Codex 路径可用；使用 1 篇帖子做端到端试跑。若 Codex 不可用，停止在分析阶段并记录阻塞，不再生成规则模式的“完成报告”。

- [ ] **Step 2: 运行 88 篇高质量帖子**

  复用 `.local/runs/20260831T-full365/raw` 和 `normalized`，不重新打开 Reddit；生成逐帖 VOC JSONL 和失败清单。

- [ ] **Step 3: 运行剩余 232 篇发现层分析**

  将弱证据内容用于发现新场景、关键词和候选话题，但不得直接支撑产品结论。

- [ ] **Step 4: 社区内聚类并导出**

  生成新的 `analysis.json`、`report.html`、`community_topics.xlsx`；保留旧文件到 `artifacts/rule-based-backup/`，新报告不得覆盖旧版以便对比。

- [ ] **Step 5: 业务验收**

  逐个抽查每个正式话题：必须能回答“多少帖子/多少人、什么场景、完成什么任务、什么痛点、造成什么后果、想要什么结果、现在怎么解决、为什么不够、是否值得验证”。任何一项没有证据则显示“暂无直接证据”，不生成机会结论。

- [ ] **Step 6: 完整测试和交付**

  运行：`\.venv\Scripts\python.exe -m pytest -q`
  通过后交付新报告，并明确列出：真实 Codex 分析完成数、失败数、正式话题数、弱信号数和覆盖限制。

## 验收标准

1. `analysis_engine_actual` 不得在 Codex 失败时伪装为 `rule_based`。
2. 每个正式话题都有可读的 VOC 链条，而不是只有产品词或通用故障词。
3. 每个痛点、需求、方案缺口和产品决策均可回溯到 Reddit 原帖或评论。
4. 报告中不再出现空白字段；无证据字段统一显示“暂无直接证据”。
5. 正式话题不再出现“其他/规则主题”或跨话题复制的固定痛点。
6. HTML、Excel、JSON 的统计数字完全一致。
7. 原始证据只作为可展开的核查材料，不占据报告正文。
8. 如果 Codex 无法运行，任务必须明确失败并保留检查点，不能再次生成简单规则报告冒充 VOC 分析。
