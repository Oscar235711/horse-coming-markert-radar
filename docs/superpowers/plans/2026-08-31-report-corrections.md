# Automotive Lighting Report Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正美国汽车照明雷达的证据口径、机会关联、画像传递、词云门槛和离线报告展示，使商业字段只呈现有来源的数据，并提供可下载的原始采集结果。

**Architecture:** 规则分析继续负责事实与门槛；报告层只负责规范化和展示，不从无关帖子推断价格。作者活动在 runner→analysis→persona 保持同一数据流；关键词展示门槛留在配置和 keyword-cloud 构建层；离线 HTML 将证据按社区折叠并从内嵌 JSON 生成 CSV。

**Tech Stack:** Node.js ESM、node:test、内嵌 HTML/CSS/JavaScript、JSON/JSONL。

## Global Constraints

- 不覆盖原始采集 JSON，不提交 `.local/`、凭据、Cookie 或个人机器路径。
- 未核实的制造、运输、退货、市场金额和产品价格不显示为事实或推断。
- 美国结论只使用美国地域证据；未知地域不升级为美国事实。
- 报告保持单文件离线可打开，不依赖外部 CDN。

---

### Task 1: 修复画像数据流并使筛选门槛可配置

**Files:**
- Modify: `src/radar-runner.mjs`
- Modify: `configs/automotive_lighting_us_full.json`
- Test: `tests/radar-runner.test.mjs`

- [ ] 为 runner→analysis 写回归测试，断言 `analyzeDetails` 收到采集到的 authorActivity，并断言配置中的 persona thresholds 被保留。
- [ ] 在 `runLightingRadar` 调用 `analyzeDetails(collection.details, config, { runId, authorActivity: collection.authorActivity })`。
- [ ] 在 full 配置增加 `persona_thresholds`，保留当前严格默认值但允许每次运行覆盖；Skill 入口读取并询问该对象。
- [ ] 运行画像和 runner 测试。

### Task 2: 修正商业信息和参考产品数据结构

**Files:**
- Modify: `src/opportunity-engine.mjs`
- Modify: `src/radar-report.mjs`
- Test: `tests/opportunity-engine.test.mjs`
- Test: `tests/radar-report.test.mjs`

- [ ] 测试无产品绑定美元数字不产生 pricing_band，且未知 manufacturing/shipping/return 字段在报告中不渲染。
- [ ] 将商业对象收敛为 `reference_products`、`pricing_band`（按官网/Amazon 分开）和 `market_potential`；价格只接受显式产品证据或外部查询结果。
- [ ] 兼容旧 JSON 但不再显示旧的 `$1–$1200` 极值、制造复杂度、运输复杂度和“可能偏高”退货推断。
- [ ] 参考产品保留 `name`, `brand`, `specification`, `packaging`, `official_url`, `amazon_url`, `official_price`, `amazon_price`, `heat`, `evidence_ids`, `observed_at`。

### Task 3: 修复痛点关系并扩展邻近配套发现

**Files:**
- Modify: `src/radar-analysis.mjs`
- Modify: `src/opportunity-engine.mjs`
- Modify: `src/radar-report.mjs`
- Test: `tests/radar-analysis.test.mjs`
- Test: `tests/opportunity-engine.test.mjs`

- [ ] 测试痛点关联正式机会和解决方向由同一证据/标签推导，且未过门槛的痛点保留为空而非伪造。
- [ ] 在分析结果生成阶段统一调用 pain normalization，避免 HTML 读取未补全的 raw pain records。
- [ ] 增加从痛点、安装上下文和同购信号产生邻近配套候选的规则；每个候选保留证据和 `adjacent_bundle` 类型，不能凭空创建正式机会。
- [ ] 报告显示“已验证关联 / 待验证方向”两种状态。

### Task 4: 增加关键词展示门槛

**Files:**
- Modify: `src/keyword-cloud.mjs`
- Modify: `src/radar-runner.mjs`
- Modify: `configs/automotive_lighting_us_full.json`
- Modify: `tests/keyword-cloud.test.mjs`

- [ ] 测试低于 `min_unique_users`, `min_threads`, `min_community_share` 任一门槛的词不进入展示词云但仍保留候选池。
- [ ] 配置 `keywords.display_thresholds`，按本次研究规模计算线程占比，不把展示词云当作原始词频全量。
- [ ] 为同义词、年份/数字和重复拼接短语保留可配置清洗规则。

### Task 5: 完善 Audience Map 和报告证据库

**Files:**
- Modify: `src/report-visuals.mjs`
- Modify: `src/radar-report.mjs`
- Test: `tests/report-visuals.test.mjs`

- [ ] 默认 map mode 改为全部关系，保留点击聚焦和同心/网络式关系视觉。
- [ ] 证据按社区分组折叠，每个社区默认只显示 3 条代表证据；代表选择兼顾质量、作者和观点。
- [ ] 在内嵌脚本增加 CSV 导出按钮，导出所有原始帖子/评论字段和链接精度，不把全文渲染进页面。
- [ ] 测试全部关系、折叠分组、代表证据和 CSV 字段/公式注入防护。

### Task 6: 生成并验证报告、提交并推送

**Files:**
- Modify: `scripts/render-existing-report.mjs`
- Modify: `docs/README` 或相关使用文档（如入口存在）

- [ ] 使用保存的正式 run 重生成报告，确认源采集字段未被覆盖。
- [ ] 运行 `node --test "tests/*.test.mjs"`、照明接口检查和 `git diff --check`。
- [ ] 检查差异只包含本次功能、测试和文档；提交到 `codex/automotive-lighting-reddit-radar` 并推送远程同名分支。
