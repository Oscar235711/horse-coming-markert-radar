# Opportunity Radar V2 广泛检索与深度 VOC 报告实施计划

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal：将 Opportunity Radar 从“四个社区的一次性碎片话题报告”升级为“关键词优先、社区归因、跨社区证据聚类、中文 WhatToSell 风格 VOC 报告”。

Architecture：四个柴油皮卡社区保留为定向基线，但全站关键词搜索成为主要发现入口。采集层先形成去重帖子和评论证据，分析层先生成可引用的 VOC claim units，再跨社区按用户任务/问题/期望结果做语义归并，报告层只读取统一的 analysis.json，不再让 HTML/Excel 各自计算或调用模型。

Tech Stack：Python 3.12、现有 OpenCLI + Chrome Reddit 登录态、Codex CLI 只读 JSON 分析、PyYAML、现有 XLSX 导出器、离线 HTML。

Spec：docs/superpowers/specs/2026-09-01-broad-keyword-voc-report-v2.md

## Global Constraints

- 中文输出：所有分析叙述字段使用 zh-CN；英文只保留原始 Reddit 证据、英文关键词和品牌名。
- 数据入口：四个种子社区 + Reddit 全站关键词检索；不得只依赖四个社区的列表接口。
- 时间范围：用户可选，最多最近 365 天；报告必须显示实际覆盖日期和 complete/partial。
- 生产运行不设置候选帖子、深读帖子、评论、关键词或社区数量上限；停止条件只能是时间边界、无下一页、无新 ID、外部拒绝或用户取消。
- 证据：事实、推断、未知分开；机会只能写成机会假设，不伪造价格、利润、制造成本或法规结论。
- 质量：删除帖、机器人、广告、纯表情和无具体场景的内容不得进入正式 VOC；弱信号保留但单独展示。
- 安全：Cookie、API Key、Codex 认证信息和个人绝对路径不进入仓库、日志或报告。
- 运行策略：先复用 .local/runs/20260831T-full365 做离线重分析，再按新采集器执行真实重采集；不重复等待旧规则任务。

---

### Task 1: 固化 V2 数据契约与中英文输出

Files:

- Create: schemas/voc-claim-unit.schema.json
- Create: schemas/community-observation.schema.json
- Create: configs/diesel_broad_v2.yaml
- Modify: src/opportunity_radar/models.py
- Modify: src/opportunity_radar/config.py
- Test: tests/test_v2_contracts.py

Interfaces:

- VOCClaimUnit 必须包含 claim_id、post_id、comment_id、community、field、value_zh、source_text_en、status、author_id、evidence_url。
- CommunityObservation 必须包含 subreddit、source_queries、post_count、author_count、relevance_score、status（observed/candidate/approved）。
- DieselBroadConfig 增加 global_queries、community_queries、round_two、complete_window、language 和 topic_thresholds；complete_window=true 时不接受任何业务数量上限。

- [ ] Step 1: 写失败测试，校验中文字段、证据 URL、社区状态和 365 天边界。
- [ ] Step 2: 运行 .\.venv\Scripts\python.exe -m pytest tests/test_v2_contracts.py -q，确认新字段尚未实现而失败。
- [ ] Step 3: 实现数据类、YAML 加载和 schema 校验；把 label_en/summary 等旧字段映射为 label_zh/summary_zh，保留英文兼容字段但不让渲染器读取它们作为主文案。
- [ ] Step 4: 将正式查询词分为 platform/product/problem/scenario/intent/brand 六类；配置 4 个社区定向查询组和全站查询模板。
- [ ] Step 5: 重新运行该测试，确认通过。

### Task 2: 实现关键词优先的全站搜索、社区发现和第二轮扩展

Files:

- Create: src/opportunity_radar/search.py
- Modify: src/opportunity_radar/collector.py
- Modify: src/opportunity_radar/keywords.py
- Modify: src/opportunity_radar/cli_app.py
- Modify: src/opportunity_radar/storage.py
- Test: tests/test_global_search.py

Interfaces:

- GlobalSearchCollector.search_queries(queries, scope, paths) -> tuple[SearchRecord, ...]
- discover_communities(records) -> tuple[CommunityObservation, ...]
- select_round_two_terms(keyword_candidates) -> tuple[str, ...]
- collect_round_two_global(terms, scope, paths) -> RoundTwoCollectionResult

- [ ] Step 1: 用模拟 OpenCLI 返回值写测试：同一个帖子从全站、社区和关键词入口返回时只保留一个 post_id，但保留全部 source_queries 和 source_surfaces。
- [ ] Step 2: 实现全站查询入口，至少覆盖平台×部件、平台×故障、平台×场景、部件×安装/适配/价格/推荐四类组合；每个查询持续分页到开始日期、无下一页或连续页面无新帖子，并保存 after cursor、分页数和停止原因。
- [ ] Step 3: 从所有有效结果生成社区观察表。社区先以 observed 进入本次运行；达到 post_count >= 3 且 author_count >= 3 或跨 2 个查询组后标为 candidate，不得静默写入批准库。
- [ ] Step 4: 复用完整灯光项目的 n-gram、产品/痛点/购买/解决办法信号评分，生成候选关键词表；候选词保存中文翻译、父级社区/话题、来源证据、独立作者数和发现分数，并以 normalized_term 自动 upsert 到 library/keywords.json。
- [ ] Step 5: 对所有达到激活门槛的新词执行第二轮全站检索和相关社区定向检索，不设置词数和每词帖子数上限；循环到本轮不再产生新 active 词、新 active 社区或新帖子 ID。
- [ ] Step 6: 以小写 subreddit 为唯一键自动 upsert library/communities.json；本轮发现全部进入 observed，达到门槛的进入 active，并立即参与本轮后续社区定向检索。
- [ ] Step 7: 每轮开始把两个库的 active 项写入 config snapshot；每轮结束输出 loaded、observed、activated、used、rejected 及证据来源，测试“收录但未被使用”必须失败。
- [ ] Step 8: 测试分页停止、断点续跑、查询失败不影响其他查询，并运行 pytest tests/test_global_search.py -q。

### Task 3: 扩大样本并进行分层深读与证据分级

Files:

- Modify: src/opportunity_radar/collector.py
- Modify: src/opportunity_radar/evidence.py
- Modify: src/opportunity_radar/cli_app.py
- Create: src/opportunity_radar/evidence_units.py
- Test: tests/test_sampling_and_evidence.py

Interfaces:

- select_all_relevant_posts(candidates, start_date, end_date) -> tuple[WindowedPost, ...]
- build_evidence_units(threads, analyses) -> tuple[VOCClaimUnit, ...]
- evidence_summary(units) -> dict[str, int]

- [ ] Step 1: 写测试验证所选时间窗口内所有相关去重帖子都进入深读队列，不得按互动量、月份或社区配额截断。
- [ ] Step 2: 删除生产运行中的 quick/standard/deep 数量预设；仅测试模式允许显式 sample=true，测试样本不能生成业务报告。
- [ ] Step 3: 对所有相关帖子获取正文和完整可访问评论树；持续展开 More Comments 和回复分页，直到 Reddit 不再返回或明确拒绝。单帖失败写入 failures.jsonl 并可单独重试。
- [ ] Step 4: 将原始帖子和评论转为 claim units；每条 claim 保存 fact/inference/unknown、英文原文、中文摘要、证据 URL、帖子/作者/评论者计数。
- [ ] Step 5: 弱证据不从原始库删除，只从正式 VOC 计算中隔离；报告显示“正式证据”和“弱信号”两套数字。
- [ ] Step 6: 采集任务按查询页、帖子详情和评论页写检查点，支持跨天运行、暂停和续跑；进度显示已完成/已发现，不显示虚假的固定总量百分比。
- [ ] Step 7: 运行模拟数据测试，并确保原有 90 天测试不回归。

### Task 4: 用 Codex 完成帖子级 VOC，并做跨社区语义聚类

Files:

- Modify: src/opportunity_radar/codex_analysis.py
- Modify: src/opportunity_radar/voc_analysis.py
- Modify: src/opportunity_radar/topics.py
- Modify: src/opportunity_radar/cli_app.py
- Create: schemas/codex_voc_post.schema.json
- Test: tests/test_v2_voc_and_topics.py

Interfaces:

- CodexAnalysisClient.extract_post_voc(thread) -> PostVOC
- TopicClusterer.cluster_claim_units(units) -> tuple[TopicCluster, ...]
- TopicClusterer.merge_equivalent_topics(clusters) -> tuple[TopicCluster, ...]
- synthesize_topic_voc(units, topic) -> TopicVOC

- [ ] Step 1: 写测试确保 Codex 输出必须是中文分析字段、每个痛点/需求/方案缺口带 evidence ID；无证据字段必须为 unknown，不能用模板句补齐。
- [ ] Step 2: 将 Codex 输入改为“帖子+评论证据包”，要求输出：平台/车型/年份、场景、JTBD 任务、痛点/严重度/后果、期望结果、当前方案、方案不足、产品/品牌/竞品、购买/维修意向、支持与反对观点、关键词。
- [ ] Step 3: 先在全局 claim units 上按 job/problem/outcome 聚类，再把社区作为标签；不再按社区各自产生一批孤立话题。每帖最多进入 3 个话题。
- [ ] Step 4: 合并同义词、发动机代号、缩写和社区黑话，生成稳定 topic_id；不再生成“其他规则主题”。
- [ ] Step 5: 正式主题使用固定门槛：4 篇帖子/3 名作者，或 3 篇帖子跨 2 个社区，或 3 篇帖子且 8 名独立讨论参与者。其余进入弱信号区。
- [ ] Step 6: 用当前已有 88 篇 Codex 结果做离线聚类回归，目标是主报告只保留约 6–12 个有重复证据的主题；确认不再出现 1 篇帖子就占据主版面的主题。
- [ ] Step 7: 运行 pytest tests/test_v2_voc_and_topics.py -q。

### Task 5: 重做中文 WhatToSell 风格报告和 Excel

Files:

- Modify: src/opportunity_radar/report.py
- Modify: src/opportunity_radar/topics.py
- Modify: tests/test_rich_report_contract.py
- Create: tests/test_v2_report_language.py

Interfaces:

- build_report_model(analysis) -> ReportModel
- render_html(analysis, output_path) -> Path
- export_topic_analysis(analysis, output_dir, formats) -> TopicExportArtifacts

- [ ] Step 1: 写测试校验 HTML/Excel/JSON 的社区数、帖子数、作者数、评论数和主题数都直接来自 analysis.report_metrics。
- [ ] Step 2: 把报告首页改成 WhatToSell 式结构：中文卖家结论、机会评分/置信度、需求验证、研究覆盖、At a Glance、Top 痛点、Seller Insight、机会方向、Why hasn’t this been solved、竞争/现有方案、验证问题。
- [ ] Step 3: 每个主主题显示“多少篇帖子、多少发帖作者、多少评论者、来自哪些社区、时间趋势”，再展示场景→任务→痛点→后果→需求→当前方案→方案不足→机会假设。
- [ ] Step 4: 主页面只显示中文摘要和少量代表性证据；英文原文、中文翻译和全部链接放入可折叠证据浏览器，避免原文淹没结论。
- [ ] Step 5: 对没有业务数据的价格、利润、制造复杂度、运输和退货字段统一显示“待业务补充”，禁止模型自行猜测。
- [ ] Step 6: 社区库、话题关键词库、候选词和弱信号分别输出独立表格；报告可筛选社区、平台、车型、主题状态、趋势和证据强度。
- [ ] Step 7: 运行报告测试并用浏览器检查中文、数字、点击下钻和离线打开。

### Task 6: 用已有数据先重分析，再执行一次扩展采集验收

Files:

- Modify: README.md
- Create: docs/BROAD_KEYWORD_VOC_GUIDE.md
- Test: tests/test_v2_end_to_end.py

- [ ] Step 1: 用 .local/runs/20260831T-full365 的原始帖子/评论跑一次新关键词抽取、claim unit 构建和跨社区聚类；这一步不打开 Chrome，先验证数据结构和报告内容。
- [ ] Step 2: 检查本次离线结果：中文字段覆盖率、正式主题证据门槛、主报告主题数、社区观察表和关键词表是否有内容。
- [ ] Step 3: 按用户选择的最近 365 天完整窗口运行一次真实扩展采集；不设置候选和深读数量上限，记录全站查询数、分页数、去重帖子数、深读数、评论数、有效证据数、社区发现数、实际日期覆盖及每个停止原因。
- [ ] Step 4: 运行 .\.venv\Scripts\python.exe -m pytest -q，再用 radar status --run-id <run_id> 检查状态为 completed 或明确的 partial。
- [ ] Step 5: 交付四个文件：analysis.json、report.html、opportunity_radar.xlsx、run_manifest.json，并附中文“本轮结论/样本限制/下一步验证”摘要。

## 参考实现的借鉴边界

- 借鉴完整灯光项目的 query_groups → deriveCandidates → keyword discovery → round-two search → evidence gate → opportunities/candidate_signals → offline report 链路。
- 借鉴它的失败记录、断点续跑、候选词评分、正式机会与候选信号分离、证据质量门禁和离线报告。
- 不直接复制灯光领域的产品词、痛点正则、美国地域规则或固定机会阈值；柴油皮卡词库和阈值必须单独配置。
- WhatToSell 的“卖家结论—痛点—机会—为什么尚未解决—研究覆盖”是报告信息架构参考，不复制其具体文案或商业数字。

## 预期结果

最终报告不是“49 个零散话题清单”，而是从更大样本中收敛出的约 6–12 个高证据主题；每个主题都能回答：谁在什么车辆和使用条件下，为完成什么任务遇到了什么问题，当前怎么解决，为什么仍不满意，SuncentAuto 可以验证哪一种产品/配件/工具/服务方向，以及这些判断分别由哪些 Reddit 帖子和评论支持。
