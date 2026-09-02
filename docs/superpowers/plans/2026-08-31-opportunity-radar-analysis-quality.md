# Opportunity Radar 分析质量与报告聚焦改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前“原文堆积、分析粗糙、同一证据重复绑定”的规则兜底，改成可解释、按证据逐条归因的 VOC 分析，并让 HTML/Excel 先展示业务结论，原文只作为按需展开的审计证据。

**Architecture:** 采集和深读流程保持不变，新增独立的本地 VOC synthesis 层，从每篇帖子及评论提取事实、场景、任务、痛点、方案和缺口，再在社区内按用户任务/问题聚类。每个断言保留自己的证据 ID、帖子数、作者数、频次和状态；`analysis.json` 是唯一事实源，HTML 与 Excel 只做展示投影。

**Tech Stack:** Python 3.12、现有 `PostAnalysis`/`PostSignal` 数据模型、pytest、现有 Python 报告生成器、Node `@oai/artifact-tool` Excel 导出；本轮不依赖 DeepSeek 或其他外部模型。

**Spec:** `docs/DATA_CONTRACT.md`、`docs/superpowers/plans/2026-08-28-community-topic-keyword-pipeline.md`，以及本轮用户反馈“分析少、原文过多、需要详细场景—任务—痛点—方案—机会分析”。

## Global Constraints

- 采集范围继续使用四个已批准社区，不增加新的 Reddit 社区。
- 事实、AI/规则推断、未知必须分开；没有证据的字段输出“未知”，不得用模板补齐。
- 产品方向只能写成机会假设，不得把社区样本直接表述为开品结论。
- 同一份 `analysis.json` 同时驱动 HTML、Excel 和交互预览，禁止各自重新计算数字。
- 原文保留用于审计和点击回溯，但不在摘要、话题卡和默认页面重复展开。
- 不保存或展示 Cookie、API Key、Codex 认证信息。

---

### Task 1: 固定“详细分析”数据契约并建立回归样本

**Files:**
- Modify: `docs/DATA_CONTRACT.md`
- Create: `tests/fixtures/voc_quality_fixture.json`
- Create: `tests/test_voc_analysis_contract.py`
- Modify: `tests/test_rich_report_contract.py`

**Interfaces:**
- Consumes: 现有 `analysis.json` 中的 `topics[].claim_evidence`、`topics[].evidence`、`report_metrics`。
- Produces: 每个可展示断言都必须有 `field`、`text`、`status`、`evidence_ids`、`post_count`、`author_count`、`frequency`；话题必须有 `analysis_summary` 和 `evidence_summary`。

- [ ] **Step 1: 写失败测试，锁定新契约和“不能重复绑定证据”规则**

```python
def test_claim_has_own_evidence_and_recurrence_metrics():
    topic = load_fixture()["topics"][0]
    claims = topic["claim_evidence"]["pains"]
    assert claims
    assert all(item["field"] == "pain" for item in claims)
    assert all(item["evidence_ids"] for item in claims)
    assert all(item["post_count"] >= 1 for item in claims)
    assert all(item["frequency"] == len(item["evidence_ids"]) for item in claims)
    assert len({tuple(item["evidence_ids"]) for item in claims}) > 1


def test_report_data_does_not_use_placeholder_claim_translation():
    topic = load_fixture()["topics"][0]
    assert "中文分析见话题卡" not in str(topic)
```

- [ ] **Step 2: 运行测试确认当前规则输出失败**

运行：`python -m pytest tests/test_voc_analysis_contract.py tests/test_rich_report_contract.py -q`

预期：失败，原因是当前 `EvidenceBackedClaim` 没有频次字段，且 `_rule_fallback` 将同一批证据绑定到所有断言。

- [ ] **Step 3: 在数据契约中写出字段定义和空值规则**

在 `docs/DATA_CONTRACT.md` 增加以下结构：

```json
{
  "field": "pain",
  "text": "用户描述的具体问题",
  "status": "fact",
  "evidence_ids": ["t3_xxx:post", "t1_yyy"],
  "post_ids": ["t3_xxx"],
  "post_count": 1,
  "author_count": 1,
  "frequency": 2,
  "severity": "unknown",
  "consequence": "unknown"
}
```

`status` 只能是 `fact`、`inference`、`unknown`；`unknown` 的 `evidence_ids` 必须为空。`evidence` 仅保留 `claim_en`、`claim_zh`、`url` 和 `evidence_id`，完整正文仍只存在于原始帖子/评论文件。

- [ ] **Step 4: 写入覆盖四类情况的固定 fixture**

fixture 至少包含：一个有具体维修结果的帖子、一个明确求助帖子、一个只有泛泛讨论的帖子、一个重复/非柴油帖子；每个帖子包含不同作者和至少两条评论，供后续验证频次与证据归因。

- [ ] **Step 5: 运行测试并提交契约变更**

运行：`python -m pytest tests/test_voc_analysis_contract.py -q`

预期：仍只有契约读取测试通过，生成器相关测试保持失败，进入 Task 2。

提交：`git add docs/DATA_CONTRACT.md tests/fixtures/voc_quality_fixture.json tests/test_voc_analysis_contract.py tests/test_rich_report_contract.py; git commit -m "test: define evidence-backed VOC report contract"`

### Task 2: 用真实帖子内容生成逐条 VOC 断言

**Files:**
- Create: `src/opportunity_radar/voc_analysis.py`
- Modify: `src/opportunity_radar/topics.py:70-110, 475-530`
- Modify: `src/opportunity_radar/cli_app.py:1481-1545`
- Test: `tests/test_voc_analysis.py`

**Interfaces:**
- Consumes: `Sequence[PostSignal]`，其中包含 `NormalizedPost`、`PostAnalysis`、评论正文和证据 URL。
- Produces: `extract_post_voc(signal) -> PostVOC`、`synthesize_topic_voc(signals, topic_key) -> TopicVOC`；`TopicVOC.claims[field]` 返回带独立证据和频次的断言。

- [ ] **Step 1: 写失败测试，确保断言来自真实字段或真实文本**

```python
def test_synthesize_topic_voc_keeps_claims_separate():
    result = synthesize_topic_voc(make_signals(), "coolant_leak")
    pains = result.claims["pain"]
    assert any("leak" in claim.source_text.casefold() for claim in pains)
    assert all(claim.evidence_ids for claim in pains)
    assert len({claim.evidence_ids for claim in pains}) >= 2
    assert not any("用户希望" in claim.text for claim in pains)


def test_no_actual_signal_means_unknown_not_template_claim():
    result = synthesize_topic_voc(make_generic_signal(), "coolant_leak")
    assert result.claims["pain"] == ()
    assert result.opportunity_status == "no_product"
```

- [ ] **Step 2: 实现 `PostVOC`、`VOCClaim` 和证据归因函数**

实现以下最小接口：

```python
@dataclass(frozen=True, slots=True)
class VOCClaim:
    field: str
    text: str
    status: str
    evidence_ids: tuple[str, ...]
    post_ids: tuple[str, ...]
    author_ids: tuple[str, ...]
    frequency: int
    severity: str = "unknown"
    consequence: str = "unknown"
    source_text: str = ""


def extract_post_voc(signal: PostSignal) -> PostVOC: ...
def synthesize_topic_voc(signals: Sequence[PostSignal], topic_key: str) -> TopicVOC: ...
```

提取顺序固定为：优先使用 `PostAnalysis` 中带 evidence IDs 的字段；缺失时只从标题、正文和评论中匹配可见的车型、平台、场景、任务、故障结果、购买/维修意图；无法匹配则返回 `unknown`。每条断言只绑定真正包含该字段或匹配词的帖子/评论，禁止使用“取前 3 条证据”作为通用绑定。

- [ ] **Step 3: 替换规则兜底中的固定话术**

保留 `_LOCAL_TOPIC_SPECS` 仅作为检索/聚类词和英文标签提示，删除其 `pains`、`needs`、`solutions`、`gaps`、`hypotheses` 直接写入报告的逻辑。`_rule_fallback` 改为调用 `synthesize_topic_voc`；没有真实断言的字段使用空列表和“当前证据未明确”，不再生成通用模板句。

- [ ] **Step 4: 增加事实/推断/未知校验**

在 `topics.py` 序列化前校验：`status == "unknown"` 时清空证据；证据 ID 不在该帖子 `evidence_urls` 中的断言直接丢弃；机会假设必须至少由两个不同作者的帖子支持，否则 `product_decision.type = "暂不形成产品机会"`。

- [ ] **Step 5: 运行单元测试**

运行：`python -m pytest tests/test_voc_analysis.py tests/test_diesel_evidence_contract.py tests/test_topic_export.py -q`

预期：所有测试通过；报告数据中不再出现“原文已保留，中文分析见话题卡”这类占位文本。

- [ ] **Step 6: 提交帖子级分析改造**

提交：`git add src/opportunity_radar/voc_analysis.py src/opportunity_radar/topics.py src/opportunity_radar/cli_app.py tests/test_voc_analysis.py; git commit -m "feat: synthesize evidence-backed VOC claims"`

### Task 3: 增加话题级频次、场景和机会判断

**Files:**
- Modify: `src/opportunity_radar/topics.py:226-350, 600-700`
- Modify: `src/opportunity_radar/metrics.py`
- Test: `tests/test_topic_analysis_quality.py`

**Interfaces:**
- Consumes: Task 2 的 `TopicVOC`。
- Produces: `topic.analysis_summary`、`topic.claim_metrics`、`topic.evidence_summary`、`topic.product_decision`；所有数字均由聚类阶段写入。

- [ ] **Step 1: 写失败测试，确保话题有可读的分析而不是标签堆积**

```python
def test_topic_contains_scenario_task_pain_solution_gap_and_decision():
    topic = build_fixture_topic()
    assert topic["analysis_summary"]["scenario"]
    assert topic["analysis_summary"]["user_task"]
    assert topic["claim_metrics"]["pain"]
    assert topic["claim_metrics"]["current_solution"]
    assert topic["claim_metrics"]["solution_gap"]
    assert topic["product_decision"]["type"] in {
        "改进现有产品", "新增车型/年份SKU", "配件或组合包", "新产品开发",
        "内容、工具或服务机会", "暂不形成产品机会",
    }
```

- [ ] **Step 2: 实现话题统计和断言排序**

对每个字段按 `post_count`、`author_count`、`frequency` 降序排序；统计必须区分支撑帖子作者、评论者和参与者。每个话题同时输出：涉及平台/车型/场景、主要任务、Top 3 痛点、当前解决方案、Top 2 方案不足、支持/反对观点和验证问题。

- [ ] **Step 3: 实现非模板化产品决策规则**

规则固定为：存在重复痛点且至少两个独立作者提出明确改进/求助，才允许输出具体产品决策；只有单个帖子、只有泛泛抱怨或没有方案缺口时输出“暂不形成产品机会”，并说明缺少哪类证据。决策正文必须包含 `rationale` 和 `supporting_claim_ids`。

- [ ] **Step 4: 增加话题级质量测试**

运行：`python -m pytest tests/test_topic_analysis_quality.py tests/test_report_metrics.py -q`

预期：同一话题的痛点、方案和机会不会全部指向同一组前三条帖子；每条断言的 `post_count` 能由 `evidence_ids` 重算。

- [ ] **Step 5: 提交话题级分析改造**

提交：`git add src/opportunity_radar/topics.py src/opportunity_radar/metrics.py tests/test_topic_analysis_quality.py; git commit -m "feat: add topic-level VOC metrics and decisions"`

### Task 4: 把报告改成“摘要优先、原文按需展开”

**Files:**
- Modify: `src/opportunity_radar/report.py:60-76`
- Modify: `scripts/build_topic_workbook.mjs:150-215`
- Test: `tests/test_report_presentation.py`

**Interfaces:**
- Consumes: Task 3 的统一 `analysis.json`。
- Produces: HTML 默认显示分析摘要和证据数量；点击“查看证据”才展开最多 3 条代表证据；Excel 证据表保留完整审计行，但分析卡不再拼接整段原文。

- [ ] **Step 1: 写失败测试，锁定默认页面不能铺满原文**

```python
def test_html_is_summary_first_and_quotes_are_collapsed():
    html = render_report(fixture_analysis())
    assert "用户任务" in html
    assert "主要痛点" in html
    assert "展开代表证据" in html
    assert html.count('class="evidence"') <= 3
    assert "（原文已保留，中文分析见话题卡）" not in html
```

- [ ] **Step 2: 重做话题卡信息层级**

话题卡默认只显示：一句话结论、场景/任务、按频次排序的痛点、当前方案、方案缺口、产品决策、证据数量和置信度。每个断言显示“支持 X 帖 / Y 作者”，旁边提供“查看代表证据”；证据使用 `<details>` 折叠，默认只显示一条 160 字以内的中文概括和原帖链接。

- [ ] **Step 3: 删除重复证据渲染**

同一 `evidence_id` 在一个话题报告中只渲染一次；在断言行中显示证据编号链接，点击后滚动到证据浏览器。完整英文原文仅在证据浏览器中出现一次，中文列显示真实翻译或“未生成中文概括”，不再生成占位句。

- [ ] **Step 4: 调整完整报告结构**

完整报告顺序固定为：结论摘要 → 数据规模/趋势 → 谁在讨论 → 用户任务 → 痛点频次/严重度/后果 → 当前解决方案 → 方案不足 → 产品决策 → 支持与反对观点 → 下一步验证 → 代表证据 → 数据限制。价格、利润、制造等无数据字段继续显示“待业务补充”。

- [ ] **Step 5: 调整 Excel 展示**

“话题分析卡”增加 `痛点频次`、`痛点作者数`、`方案缺口频次`、`证据数量` 和 `结论置信度` 列；“帖子及评论证据”保留原文用于审计，但增加 `证据用途`、`是否代表证据`、`中文概括` 列，并按话题和断言分组，避免分析卡直接塞原文。

- [ ] **Step 6: 运行报告测试和离线导出**

运行：`python -m pytest tests/test_report_presentation.py tests/test_rich_report_contract.py tests/test_topic_export.py -q`

预期：HTML 默认可读摘要明显多于原文；HTML、Excel、JSON 的帖子数、作者数、评论数、证据数和话题排名一致。

- [ ] **Step 7: 提交报告改造**

提交：`git add src/opportunity_radar/report.py scripts/build_topic_workbook.mjs tests/test_report_presentation.py; git commit -m "feat: make reports summary first with on-demand evidence"`

### Task 5: 用现有 20260831T-full365 数据重跑并验收

**Files:**
- Modify: `.local/runs/20260831T-full365/`（仅生成产物，不提交仓库）
- Create: `docs/analysis-quality-acceptance-20260831.md`
- Test: `tests/test_real_run_quality.py`

**Interfaces:**
- Consumes: 现有原始帖子/评论、Task 2–4 的代码和四社区配置。
- Produces: 新的 `analysis.json`、`report.html`、`community_topics.xlsx` 和一份验收记录。

- [ ] **Step 1: 只从已保存 raw/checkpoint 恢复，不重新请求 Reddit**

运行：`python -m opportunity_radar resume --run-id 20260831T-full365 --analysis-engine rules --formats json,xlsx,html`

预期：使用已有 4,000 个候选、320 个深读帖子和 7,839 条评论生成新产物，不触发 Chrome 采集。

- [ ] **Step 2: 做自动质量断言**

```python
def test_real_run_claims_are_grounded_and_non_repetitive():
    data = load_real_analysis()
    for topic in data["topics"]:
        claims = [item for values in topic["claim_evidence"].values() if isinstance(values, list) for item in values]
        assert all(item["evidence_ids"] for item in claims)
        assert all(item["status"] in {"fact", "inference", "unknown"} for item in claims)
        assert not any("中文分析见话题卡" in str(item) for item in claims)
        assert len({tuple(item["evidence_ids"]) for item in claims}) >= min(2, len(claims))
```

- [ ] **Step 3: 人工快速验收五个最高热度话题**

逐个确认：能否在 30 秒内回答“多少帖子/多少作者在讨论什么、场景是什么、要完成什么任务、痛点是什么、正在用什么办法、哪里不足、是否值得验证”；若不能，记录为缺陷，不用增加原文数量掩盖分析不足。

- [ ] **Step 4: 输出验收记录**

记录旧版与新版的：正式话题数、每话题平均断言数、每断言平均证据数、重复证据比例、摘要字数、默认页面原文字符数，以及 HTML/Excel/JSON 数字一致性。明确“88 篇有效帖子”仍是证据门禁结果，不将其误写成市场规模。

- [ ] **Step 5: 提交测试和文档，不提交运行数据**

提交：`git add tests/test_real_run_quality.py docs/analysis-quality-acceptance-20260831.md; git commit -m "test: validate detailed VOC report quality"`

### Task 6: 更新使用说明并交付

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_BASELINE.md`
- Create: `docs/REPORT_READING_GUIDE.md`

- [ ] **Step 1: 在 README 中说明新版报告读法**

明确：主页面先看社区和话题摘要；话题卡先看频次、作者数、场景、任务、痛点和方案缺口；只有需要核实时再展开代表证据；完整原文位于证据浏览器和 Excel 审计表。

- [ ] **Step 2: 写出本地运行与验收命令**

```powershell
radar resume --run-id 20260831T-full365 --analysis-engine rules --formats json,xlsx,html
radar status --run-id 20260831T-full365
```

同时说明规则模式的边界：它只做可解释提取和聚类，不会凭空判断价格、利润、制造难度或用户身份。

- [ ] **Step 3: 完成最终测试**

运行：`python -m pytest -q`

预期：全量测试通过；离线打开 `report.html` 时默认显示分析摘要，原文需要主动展开；HTML、Excel、JSON 核心数字一致。

- [ ] **Step 4: 提交交付文档**

提交：`git add README.md docs/CURRENT_BASELINE.md docs/REPORT_READING_GUIDE.md; git commit -m "docs: explain evidence-first report workflow"`

## 验收标准

- 每个正式话题都有真实场景、用户任务、至少一条具体痛点、当前方案、方案不足和下一步验证问题；缺失项明确显示未知。
- 每条痛点、方案不足和机会假设都绑定自己的证据，不再把同一批前三条帖子复制到所有字段。
- 话题分析显示帖子数、独立作者数、评论者数、频次和支持/反对观点；这些数字能由 `analysis.json` 重算。
- HTML 首屏以分析摘要为主，代表证据默认折叠；完整英文原文在一个话题内只出现一次。
- Excel 仍保留完整原文审计表，但分析卡不再堆叠原文。
- 规则模式不输出无证据的价格、利润、制造工艺、身份和开品结论。
- 现有 20260831T-full365 运行可离线恢复并生成新报告；不需要重新爬取即可验证改造效果。
