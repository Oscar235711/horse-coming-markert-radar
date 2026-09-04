# Hot30 中文热点总览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让近30天热点检索在采集完成后，明确用中文回答“这30天大家在讨论什么、每个话题具体在讨论什么、为什么值得关注”，并且每个判断都能回到原始证据。

**Architecture:** 保留 last30days 的多平台英文原始数据，新增独立的 Hot30 中文洞察层。洞察层不依赖可能为空的 `clusters`，而是从 `ranked_candidates` 和 `items_by_source` 合并证据池，分批调用 Higress DeepSeek 做中文提取，再进行话题归并、证据校验和总览生成。HTML、Markdown 和 JSON 统一读取同一份 `analysis.json.overview`。

**Tech Stack:** Python 3.12、现有 `DeepSeekClient`、last30days Skill JSON、原生 HTML/CSS、pytest。

**Spec:** `docs/superpowers/plans/2026-09-04-hot30-chinese-overview.md` 中的“产品输出契约”和“验收标准”。

## Global Constraints

- 原始英文标题、摘要、链接和来源字段必须完整保留。
- 用户默认看到简体中文；英文原文只在折叠区展示。
- 不使用通用模板或关键词替换伪装成分析结论。
- 每个话题摘要、用户讨论内容和关注理由必须绑定有效 evidence ID。
- DeepSeek 失败时显示“分析未完成”和失败原因，不输出虚构热点。
- “值得关注”属于研究判断或机会假设，不表述为已经验证的市场结论。
- Hot30 仅表达本次30天采集样本，不声称代表全网市场份额。
- 不重新设计 Reddit 长周期 VOC 报告，本计划只修改 Hot30 多平台热点链路。

---

## 产品输出契约

页面顶部必须先出现“30天讨论总览”，而不是先出现来源状态：

```text
本轮采集了多少条有效证据、来自哪些平台
→ 归并出多少个正式热点和多少个弱信号
→ 用3—5条中文结论概括这30天的主要讨论方向
→ 按热度列出具体话题
→ 点击话题查看讨论内容、用户问题、关注理由和证据
```

`analysis.json` 新增且固定以下字段：

```json
{
  "overview": {
    "status": "completed",
    "headline_zh": "近30天讨论总体结论",
    "executive_summary_zh": ["结论一", "结论二"],
    "data_snapshot": {
      "evidence_count": 0,
      "source_count": 0,
      "formal_topic_count": 0,
      "weak_signal_count": 0,
      "actual_start": "YYYY-MM-DD",
      "actual_end": "YYYY-MM-DD"
    },
    "topics": [],
    "watchlist": [],
    "limitations_zh": []
  }
}
```

每个正式话题固定输出：

```json
{
  "topic_id": "hot30_xxx",
  "title_zh": "中文话题名",
  "title_en": "Original English label",
  "one_line_zh": "一句话概括",
  "discussion_zh": "用户围绕什么事情展开讨论",
  "user_context_zh": "涉及哪些用户、车辆或使用条件",
  "pain_need_zh": "暴露出的痛点、需求或目标",
  "current_response_zh": "用户当前如何处理",
  "why_watch_zh": "为什么值得继续关注",
  "opportunity_hypothesis_zh": "可能的产品、内容、服务或后续研究方向",
  "counter_signal_zh": "反对观点、证据不足或风险",
  "heat": {
    "score": 0,
    "label_zh": "上升/稳定/新出现/证据不足",
    "evidence_count": 0,
    "source_count": 0,
    "participant_count": 0
  },
  "evidence_ids": ["source:item"],
  "evidence": []
}
```

每条证据固定输出：

```json
{
  "evidence_id": "reddit:R12",
  "source": "reddit",
  "url": "https://...",
  "title_original": "English title",
  "title_zh": "中文标题",
  "excerpt_original": "English excerpt",
  "excerpt_zh": "中文摘录",
  "published_at": "YYYY-MM-DD",
  "author": "账号或未知",
  "engagement": 0
}
```

正式热点至少有3条独立证据；只有1—2条证据的内容进入弱信号观察区。跨平台出现时显示“跨平台”，单平台高热度时如实显示“单平台信号”。

---

### Task 1: 建立 Hot30 证据池和中文洞察 Schema

**Files:**
- Create: `src/opportunity_radar/hot30_overview.py`
- Create: `schemas/hot30_overview.schema.json`
- Test: `tests/test_hot30_overview.py`

**Interfaces:**
- Consumes: last30days 原始 `report: Mapping[str, Any]`
- Produces: `build_evidence_pool(report) -> list[dict[str, Any]]`
- Produces: `validate_overview(document, evidence_pool) -> dict[str, Any]`

- [ ] **Step 1: 写失败测试，覆盖 ranked 和 source items 合并去重**

```python
def test_build_evidence_pool_works_when_clusters_are_empty():
    report = {
        "ranked_candidates": [],
        "clusters": [],
        "items_by_source": {
            "reddit": [{"item_id": "R1", "title": "Engine-out upgrades", "url": "https://reddit.test/1"}],
            "youtube": [{"item_id": "Y1", "title": "Diesel towing setup", "url": "https://youtube.test/1"}],
        },
    }
    pool = build_evidence_pool(report)
    assert [row["evidence_id"] for row in pool] == ["reddit:R1", "youtube:Y1"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hot30_overview.py -v`

Expected: FAIL，提示 `hot30_overview` 或 `build_evidence_pool` 不存在。

- [ ] **Step 3: 实现证据池**

```python
def build_evidence_pool(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Merge ranked candidates and source items by URL, preserving raw text."""
```

要求：

- URL 为第一去重键，缺少 URL 时使用 `source:item_id`；
- 只保留有标题、摘要或正文的记录；
- 保存来源、时间、作者和互动量；
- 不因 `clusters=[]` 丢弃已经采集的数据；
- 不把来源数量当参与者数量。

- [ ] **Step 4: 实现 Schema 校验器**

校验器必须删除不存在的 evidence ID，重新计算每个话题的证据数，并把无有效证据的话题移出正式话题。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hot30_overview.py -v`

Expected: PASS。

Commit: `git commit -m "feat: add hot30 overview evidence contract"`

### Task 2: DeepSeek 分批中文提取与断点缓存

**Files:**
- Modify: `src/opportunity_radar/hot30_overview.py`
- Modify: `src/opportunity_radar/last30days_adapter.py`
- Test: `tests/test_hot30_overview.py`

**Interfaces:**
- Consumes: `list[dict]` 证据池和现有 `DeepSeekClient`
- Produces: `extract_item_signals(pool, client, cache_path) -> list[dict]`
- Cache: `artifacts/hot30_item_analysis.jsonl`

- [ ] **Step 1: 写失败测试，要求英文输入生成中文字段并保留英文**

```python
def test_item_signal_keeps_original_and_requires_chinese_translation(fake_client, tmp_path):
    rows = extract_item_signals(ENGLISH_POOL, fake_client, tmp_path / "items.jsonl")
    assert rows[0]["title_original"] == "Engine-out upgrades"
    assert rows[0]["title_zh"] == "发动机拆出期间的升级项目"
    assert rows[0]["discussion_zh"]
```

- [ ] **Step 2: 实现每批20条的帖子级提取**

DeepSeek 返回字段固定为：

```text
evidence_id
title_zh
excerpt_zh
discussion_zh
user_context_zh
pain_need_zh
current_response_zh
candidate_topic_zh
candidate_topic_en
```

Prompt 必须要求：简体中文、保留车型/品牌英文专名、不得新增事实、只使用输入 evidence ID。

- [ ] **Step 3: 实现逐批写入和续跑**

每完成一批立即追加到 `hot30_item_analysis.jsonl`；再次分析时跳过已完成 evidence ID。单批失败记录错误并继续下一批，最终状态标记为 `partial`。

- [ ] **Step 4: 删除关键词替换式“伪翻译”作为正式结果的路径**

`_fallback_translate()` 只能用于界面状态提示，不得作为 `title_zh`、`discussion_zh` 或正式话题结论写入 `analysis.json`。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hot30_overview.py tests/test_last30days_adapter.py -v`

Expected: PASS。

Commit: `git commit -m "feat: extract Chinese hot30 evidence signals"`

### Task 3: 生成30天总览和正式热点话题

**Files:**
- Modify: `src/opportunity_radar/hot30_overview.py`
- Test: `tests/test_hot30_overview.py`

**Interfaces:**
- Consumes: `item_signals: Sequence[Mapping]`
- Produces: `synthesize_overview(item_signals, client) -> dict[str, Any]`

- [ ] **Step 1: 写失败测试，覆盖总览和话题内容**

```python
def test_overview_answers_what_people_discussed(fake_client):
    overview = synthesize_overview(ITEM_SIGNALS, fake_client)
    assert 3 <= len(overview["executive_summary_zh"]) <= 5
    topic = overview["topics"][0]
    assert topic["discussion_zh"]
    assert topic["why_watch_zh"]
    assert len(topic["evidence_ids"]) >= 3
```

- [ ] **Step 2: 实现社区/平台无关的话题归并**

归并依据是“用户面对的同类任务、问题或目标”，而不是简单把相同产品名放在一起。每条证据最多进入3个话题；同义表达合并；跨平台话题和单平台话题分别标记。

- [ ] **Step 3: 实现正式话题与弱信号门槛**

- 正式话题：至少3条不同 URL 的证据；
- 弱信号：1—2条证据，写入 `watchlist`；
- 无证据的模型话题直接删除；
- 总览只能总结通过校验的正式话题。

- [ ] **Step 4: 生成“值得关注”而不是直接给开品结论**

`why_watch_zh` 必须说明信号价值，例如重复痛点、场景集中、方案不满或讨论上升；`opportunity_hypothesis_zh` 必须标记为待验证假设；没有产品信号时允许输出“更适合继续调研，暂不形成产品机会”。

- [ ] **Step 5: 计算样本热度并提交**

热度由 Python 计算：证据数35%、互动量25%、来源多样性20%、时效性20%。页面明确标注“样本热度”，不解释为市场份额。

Run: `.venv\Scripts\python.exe -m pytest tests/test_hot30_overview.py -v`

Expected: PASS。

Commit: `git commit -m "feat: synthesize Chinese hot30 topic overview"`

### Task 4: 重构 Hot30 HTML 和 Markdown 总览

**Files:**
- Modify: `src/opportunity_radar/last30days_adapter.py`
- Test: `tests/test_last30days_adapter.py`

**Interfaces:**
- Consumes: `analysis.json.overview`
- Produces: `brief.html`、`brief.md`

- [ ] **Step 1: 写失败测试，要求总览出现在来源状态之前**

```python
def test_hot30_html_leads_with_chinese_overview(tmp_path):
    html = render_hot30(FIXTURE_WITH_OVERVIEW, tmp_path)
    assert html.index("这30天大家在讨论什么") < html.index("来源状态")
    assert "用户在讨论什么" in html
    assert "为什么值得关注" in html
    assert "查看英文原文" in html
```

- [ ] **Step 2: 重做页面顶部**

第一屏固定包含：

- 研究主题与实际时间范围；
- 有效证据数、有效来源数、正式热点数、弱信号数；
- “这30天大家在讨论什么”3—5条中文摘要；
- 数据状态和覆盖限制。

- [ ] **Step 3: 重做正式话题卡**

每张卡依次展示：

```text
中文话题名
一句话概括
帖子/证据/来源/参与者数字
用户在讨论什么
涉及的场景、痛点或需求
用户当前怎么处理
为什么值得关注
可能的机会或下一步研究
反对观点与证据限制
代表证据链接
折叠的英文原文
```

- [ ] **Step 4: 将来源状态移到总览和话题之后**

来源状态继续保留，但不再成为报告主内容。未配置、超时、403、429 分别显示中文原因。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/test_last30days_adapter.py -v`

Expected: PASS。

Commit: `git commit -m "feat: render actionable Chinese hot30 brief"`

### Task 5: 接入任务状态、重新分析和失败恢复

**Files:**
- Modify: `src/opportunity_radar/server.py`
- Modify: `src/opportunity_radar/dashboard.py`
- Modify: `tests/test_web_server.py`

**Interfaces:**
- Add: `POST /api/runs/{run_id}/reanalyze`
- State stages: `hot30_extracting`、`hot30_clustering`、`hot30_validating`、`exported`

- [ ] **Step 1: 写失败测试，验证已有数据无需重新采集即可重新分析**

```python
def test_reanalyze_uses_saved_hot30_source_data(manager):
    response = manager.reanalyze_hot30("run-1")
    assert response["stage"] == "hot30_extracting"
    assert response["collection_started"] is False
```

- [ ] **Step 2: 保存原始与分析数据边界**

- `source_data.json`：last30days 原始英文输出，只写一次；
- `hot30_item_analysis.jsonl`：分批中文提取检查点；
- `analysis.json`：含 `overview` 的最终统一结果；
- 重新分析不得访问采集平台。

- [ ] **Step 3: 在任务卡增加“重新生成中文总览”按钮**

仅当原始数据存在且分析失败、为空或版本过旧时显示。点击后展示分析进度，不重新采集。

- [ ] **Step 4: 修正进度文案**

进度必须区分：数据已获取、正在翻译提取、正在归并话题、正在生成总览、报告已完成。不能在只有英文原始数据时显示“全部完成”。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/test_web_server.py -v`

Expected: PASS。

Commit: `git commit -m "feat: support hot30 overview reanalysis"`

### Task 6: 用已有任务回放并完成最终验收

**Files:**
- Modify: `README.md`
- Verify: `.local/runs/20260904T121124Z-2c468f/artifacts/`

**Interfaces:**
- Consumes: 已保存的 `analysis.json` / `source_data.json`
- Produces: 更新后的中文 `brief.html`、`brief.md`、`analysis.json`

- [ ] **Step 1: 备份旧分析产物并运行重新分析**

保留旧报告为 `brief.pre-overview.html`，从已有证据回放，不重新调用 Reddit、YouTube 或其他采集源。

- [ ] **Step 2: 检查总览内容**

确认页面明确回答：

- 30天内主要在聊哪些事情；
- 每个话题具体讨论什么；
- 涉及什么用户、车辆、场景、痛点或需求；
- 为什么值得关注；
- 哪些只是弱信号；
- 证据来自哪里。

- [ ] **Step 3: 检查中英文展示**

页面正文不得出现连续的大段英文；车型、发动机、产品和品牌英文专名允许保留；完整英文只出现在折叠区。

- [ ] **Step 4: 运行完整测试**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: 100% PASS。

- [ ] **Step 5: 更新使用说明并提交**

README 写清楚：启动网站、发起热点检索、查看中文总览、重新分析已有数据、下载 JSON/Markdown、各状态的含义。

Commit: `git commit -m "docs: explain Chinese hot30 overview workflow"`

---

## 验收标准

- 报告第一屏直接出现“这30天大家在讨论什么”。
- 每个正式话题都有中文名称、一句话概括、讨论内容和关注理由。
- 每个正式话题至少绑定3条不同 URL 的证据；不足的进入弱信号区。
- 页面主要内容为简体中文，英文原文默认折叠。
- 抓取到数据但 DeepSeek 未完成时，任务不得显示为完整报告已完成。
- `clusters=[]` 但 `items_by_source` 有数据时，仍能从证据池执行 DeepSeek 话题分析。
- DeepSeek 失败时不生成模板化热点，也不把关键词替换结果当作正式中文分析。
- 总览、话题卡、来源状态和下载 JSON 的数字一致。
- 已有任务可以只重新分析，不重复触发平台采集。
- 报告中的“机会”明确标记为待验证方向，不直接形成开品结论。

