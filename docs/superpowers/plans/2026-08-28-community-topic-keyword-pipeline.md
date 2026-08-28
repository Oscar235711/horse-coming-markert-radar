# Opportunity Radar 四社区数据链路与报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在只使用四个已确认 Reddit 社区的前提下，完成“社区库 → 话题关键词库 → 帖子/评论证据 → 可解释规则聚类 → Excel/HTML”的稳定可复跑链路。

**Architecture:** `r/Cummins`、`r/Duramax`、`r/powerstroke`、`r/FordDiesels` 是本阶段唯一的正式扫描社区，作为固定基线，不做社区扩张。采集层保存原始 listing、完整 thread 和标准化帖子/评论；规则分析层从配置词库及真实帖子/评论抽取话题关键词，按“社区＋平台＋场景＋问题/目标”聚类；Excel 与 HTML 只读取同一份 `analysis.json`，并分别提供独立的社区库表和关键词库表。

**Tech Stack:** Python 3.12、现有 `opportunity_radar` 包、OpenCLI + Chrome Reddit 登录态、PyYAML、现有 Node Excel 构建脚本、离线 HTML、pytest。

**Spec:** 用户确认的固定链路：“社区库 → 话题关键词库 → 帖子/评论证据 → 可解释规则聚类 → Excel/HTML”。

## Global Constraints

- 本阶段只扫描四个正式社区：`Cummins`、`Duramax`、`powerstroke`、`FordDiesels`。
- 默认分析窗口为最近 90 天，拆分最近 30 天热点与前 60 天历史基线。
- DeepSeek 不作为本阶段阻塞项；规则聚类必须在无模型时运行，并输出 `model_mode=rule_based`。
- 所有痛点、方案不足和机会假设必须绑定帖子或评论证据 ID 与原始 Reddit URL。
- 事实、规则推断和未知必须分开保存，不能把缺失信息写成确定结论。
- 不生成删除排放、绕过监管或危险改装的操作教程；相关讨论只作为市场信号。
- Cookie、API Key、绝对路径和浏览器登录态不得进入仓库、日志、JSON 或 Excel。

---

### Task 1: 固化四社区库并增加独立社区库表

**Files:**
- Modify: `configs/community_catalog.v1.yaml`
- Modify: `configs/diesel_90d.yaml`
- Modify: `src/opportunity_radar/models.py`
- Modify: `src/opportunity_radar/config.py`
- Modify: `src/opportunity_radar/topics.py`
- Modify: `scripts/build_topic_workbook.mjs`
- Test: `tests/test_community_catalog.py`
- Modify: `tests/test_topic_export.py`

**Interfaces:**
- `Community` 保留 `name`、`aliases`、`include`、`exclude`、`category`、`brand`、`slang` 字段，并增加稳定的 `community_id` 与 `status="approved"`。
- `build_community_library(catalog: CommunityCatalog) -> list[dict[str, Any]]`。
- Excel 新增工作表 `社区库`，字段固定为：`community_id`、`subreddit`、`display_name`、`platform`、`status`、`aliases`、`include_terms`、`exclude_terms`、`slang`、`config_version`。

- [ ] **Step 1: 写失败测试，确保只有四个正式社区**

```python
def test_active_catalog_contains_only_four_approved_communities():
    catalog = load_config("configs/diesel_90d.yaml")
    assert [c.name for c in catalog.communities] == [
        "Cummins", "Duramax", "powerstroke", "FordDiesels"
    ]
    assert all(c.status == "approved" for c in catalog.communities)
```

- [ ] **Step 2: 运行测试确认字段和工作表尚未完成**

Run: `py -m pytest tests/test_community_catalog.py tests/test_topic_export.py -q`

Expected: FAIL on `community_id`/`status` and `社区库` sheet assertions.

- [ ] **Step 3: 固化社区配置和工作表导出**

四个社区的别名、平台、车型/发动机词、排除词和黑话从 YAML 读取；Excel 的 `社区库` 只展示配置快照，不从分析结果临时拼接，保证每轮可追溯。

- [ ] **Step 4: 运行测试并提交**

Run: `py -m pytest tests/test_community_catalog.py tests/test_topic_export.py -q`

Expected: PASS；Commit: `feat: add fixed community library sheet`。

### Task 2: 完整保存帖子、评论和证据

**Files:**
- Modify: `src/opportunity_radar/storage.py`
- Modify: `src/opportunity_radar/collector.py`
- Modify: `src/opportunity_radar/normalization.py`
- Modify: `src/opportunity_radar/cli_app.py`
- Test: `tests/test_run_storage.py`
- Modify: `tests/test_collection_and_deepseek.py`

**Interfaces:**
- `RunPaths.raw_listings_dir`、`RunPaths.raw_searches_dir`、`RunPaths.raw_threads_dir`、`RunPaths.normalized_dir`、`RunPaths.failures_path`。
- `persist_thread(paths: RunPaths, post_id: str, raw_thread: Mapping[str, Any]) -> Path`。
- `write_normalized_records(paths: RunPaths, posts: Sequence[NormalizedPost], comments: Sequence[ThreadComment]) -> tuple[Path, Path]`。

- [ ] **Step 1: 写失败测试，要求最终目录结构完整**

```python
def test_run_paths_create_thread_and_normalized_locations(tmp_path):
    paths = create_run_paths(tmp_path, "run-1")
    assert paths.raw_threads_dir.exists()
    assert paths.normalized_dir.exists()
    assert paths.failures_path.name == "failures.jsonl"
```

- [ ] **Step 2: 保存原始 thread 和失败记录**

深读成功时将 OpenCLI 原始 JSON 写入 `raw/threads/<post_id>.json`；失败时追加脱敏失败记录，字段固定为 `community`、`post_id`、`stage`、`error_type`、`retryable`。

- [ ] **Step 3: 输出标准化帖子和评论 JSONL**

帖子字段至少包含 `post_id`、`subreddit`、`title`、`body`、`author`、`created_at`、`score`、`comment_count`、`url`、`source_surfaces`；评论字段至少包含 `comment_id`、`post_id`、`parent_id`、`body`、`author`、`depth`、`url`。

- [ ] **Step 4: 运行断点和存储测试并提交**

Run: `py -m pytest tests/test_run_storage.py tests/test_collection_and_deepseek.py -q`

Expected: PASS；Commit: `feat: persist reddit threads comments and evidence`。

### Task 3: 生成独立话题关键词库和关键词库表

**Files:**
- Modify: `src/opportunity_radar/keywords.py`
- Modify: `src/opportunity_radar/cli.py`
- Modify: `src/opportunity_radar/cli_app.py`
- Modify: `src/opportunity_radar/topics.py`
- Modify: `scripts/build_topic_workbook.mjs`
- Create: `tests/test_topic_keywords.py`
- Modify: `tests/test_keyword_discovery.py`

**Interfaces:**
- `TopicKeyword(term_en: str, term_zh: str, keyword_type: str, community: str, topic_key: str, source_ids: tuple[str, ...], author_count: int, post_count: int, score: float, status: str)`。
- `build_topic_keyword_library(posts: Sequence[NormalizedPost], comments: Sequence[ThreadComment], analyses: Sequence[PostAnalysis], config: RadarConfig) -> dict[str, Any]`。
- `write_keyword_library(paths: RunPaths, library: Mapping[str, Any]) -> tuple[Path, Path]`。
- Excel 新增工作表 `话题关键词库`，字段固定为：`keyword_id`、`term_en`、`term_zh`、`keyword_type`、`community`、`topic_key`、`variants`、`source_post_ids`、`source_comment_ids`、`post_count`、`author_count`、`signal_types`、`score`、`status`。

- [ ] **Step 1: 写失败测试，区分配置词、发现词、候选词和噪声词**

```python
def test_topic_keyword_library_keeps_provenance_and_rejects_brand_only_terms():
    library = build_topic_keyword_library(posts, comments, analyses, config)
    assert all(item["source_post_ids"] or item["source_comment_ids"] for item in library["candidates"])
    assert "ford" not in {item["term_en"] for item in library["candidates"]}
```

- [ ] **Step 2: 从标题、正文、评论和结构化字段抽取关键词**

抽取产品词、车型/发动机代号、安装与故障表达、使用场景、现有方案、方案失败、竞品和社区黑话；同义词、大小写、连字符、复数和缩写归一化，同时保留原始变体。

- [ ] **Step 3: 计算候选词分数并保存来源**

候选分数由独立帖子数 30%、独立作者数 20%、社区覆盖 20%、痛点/购买/失败方案信号 20%、近期增长 10% 组成；无法确认的中文翻译写为“待翻译”，不编造翻译。

- [ ] **Step 4: 写出词库 JSON 和 Excel 独立表**

每轮写入 `keywords/keyword_library.json` 与 `keywords/keyword_candidates.json`；正式词和候选词分开，`话题关键词库` 由同一份 `analysis.json` 与词库快照生成。

- [ ] **Step 5: 运行测试并提交**

Run: `py -m pytest tests/test_keyword_discovery.py tests/test_topic_keywords.py tests/test_topic_export.py -q`

Expected: PASS；Commit: `feat: add auditable topic keyword library`。

### Task 4: 实现可解释规则聚类和分析质量门禁

**Files:**
- Modify: `src/opportunity_radar/topics.py`
- Modify: `src/opportunity_radar/cli_app.py`
- Modify: `src/opportunity_radar/models.py`
- Create: `tests/test_rule_topic_clustering.py`
- Modify: `tests/test_topic_registry.py`

**Interfaces:**
- `RuleTopicProposal(canonical_key: str, label_en: str, label_zh: str, post_ids: tuple[str, ...], evidence: tuple[TopicEvidence, ...], reason_codes: tuple[str, ...])`。
- `cluster_rule_topics(signals: Sequence[PostSignal], keyword_library: Mapping[str, Any]) -> tuple[RuleTopicProposal, ...]`。
- `aggregate_rule_topics(community: str, signals: Sequence[PostSignal], registry: TopicRegistry, as_of: datetime) -> TopicAggregationResult`。

- [ ] **Step 1: 写失败测试，阻止空洞的通用话题**

```python
def test_rule_cluster_key_contains_platform_and_problem_or_goal():
    proposals = cluster_rule_topics(signals, keyword_library)
    assert proposals
    assert all("generic_diesel_chat" not in p.canonical_key for p in proposals)
    assert all(p.evidence for p in proposals)
```

- [ ] **Step 2: 定义规则聚类键和字段来源**

优先使用 `community + platform + scenario + problem_or_goal`；缺少场景时使用 `community + platform + category + normalized_keyword`；只有品牌词、车型词或无证据文本的记录进入弱信号。

- [ ] **Step 3: 实施同义词合并和三标签上限**

将 `power stroke/powerstroke`、`CCV reroute/crankcase ventilation`、发动机代号和产品别名映射到同一规范词；一篇帖子最多进入 3 个话题，并在 `reason_codes` 保存命中的词和字段。

- [ ] **Step 4: 应用证据门槛、事实/推断/未知分离**

正式话题要求 3 篇不同帖子且 3 名作者，或 2 篇帖子且 10 名评论者；其他内容写入 `weak_signal`。没有原帖或评论证据的字段写为 `unknown`，不能生成痛点、方案不足或机会假设。

- [ ] **Step 5: 运行规则聚类测试并提交**

Run: `py -m pytest tests/test_rule_topic_clustering.py tests/test_topic_registry.py tests/test_topic_export.py -q`

Expected: PASS；Commit: `feat: add explainable rule topic analysis`。

### Task 5: 重建数字一致的 WhatToSell 风格 HTML 和 Excel

**Files:**
- Modify: `src/opportunity_radar/report.py`
- Modify: `src/opportunity_radar/topics.py`
- Modify: `scripts/build_topic_workbook.mjs`
- Modify: `scripts/build_diesel_demo.py`
- Create: `tests/test_report_consistency.py`
- Modify: `tests/test_topic_export.py`
- Modify: `README.md`

**Interfaces:**
- `export_run(run_id: str, formats: Sequence[str]) -> TopicExportArtifacts` 必须只读取同一份 `analysis.json`。
- HTML 必须支持社区筛选、话题关键词筛选、弱信号展开、证据 URL 点击和中英文并列显示。
- Excel 固定工作表顺序：`运行概览`、`社区库`、`话题关键词库`、`社区热点排行`、`话题分析卡`、`帖子及评论证据`、`弱信号观察区`、`排除与失败记录`。

- [ ] **Step 1: 写失败测试，统一 JSON、Excel、HTML 数字口径**

```python
def test_exports_share_analysis_counts(tmp_path):
    artifacts = export_run("run-1", ["json", "xlsx", "html"])
    expected = read_analysis_counts(artifacts.analysis_json)
    assert extract_html_counts(artifacts.report_path) == expected
    assert read_workbook_counts(artifacts.workbook_path) == expected
```

- [ ] **Step 2: 统一指标计算入口**

所有社区数、话题数、正式/弱信号数、帖子数、作者数、评论数和证据数只在 `analysis.json` 生成一次；HTML 和 Excel 禁止自行重新统计。

- [ ] **Step 3: 重做 HTML 信息层级**

保持 WhatToSell 逻辑：左侧社区列表，中间社区空心节点与话题实心节点，右侧话题分析卡；分析卡必须显示关键词、场景、痛点、现有方案、方案不足、机会假设、证据数量和可点击原帖/评论链接。

- [ ] **Step 4: 用固定样例和真实数据分别验收**

运行：`python scripts/build_diesel_demo.py --input configs/diesel_demo_analysis.json --output outputs/diesel-demo-v2`；再用现有真实 run 重新导出。固定样例必须显示四个社区和可解释话题；真实数据若为规则模式必须显式显示“规则分析 Demo”，不得伪装成模型结论。

- [ ] **Step 5: 完成全流程验收并提交**

Run: `py -m pytest -q`; `powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\verify-portable-config.ps1`; `powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\verify-windows-utf8.ps1`

Expected: PASS；Commit: `feat: align report metrics and library tables`。

## 当前社区库结论

本阶段社区库固定为四个，不做扩张。更大范围检索暂时不进入实现范围；等四社区的数据、关键词库、证据存储和报告指标稳定后，再单独评估是否增加社区。

## Self-review checklist

- [ ] 四个正式社区每轮可复现，配置快照可追溯。
- [ ] `raw/threads`、`normalized/posts.jsonl`、`normalized/comments.jsonl`、`failures.jsonl` 均有实际产物。
- [ ] Excel 有独立 `社区库` 和 `话题关键词库` 工作表。
- [ ] 规则聚类能解释每个话题为什么形成，并绑定证据。
- [ ] HTML、Excel 和 JSON 的数字完全一致。
- [ ] 规则兜底结果明确标注为 Demo，不冒充最终业务结论。
