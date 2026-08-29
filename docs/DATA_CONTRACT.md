# 数据契约

## 当前车灯雷达输入

- `configs/automotive_lighting_us_pilot.json`：美国市场、14个锚点词、受控扩展词、社区和样本限制。
- `configs/automotive_lighting_us_mini.json`：公开 JSON / CI 默认小样本配置，用于格式、workflow 和 artifact 契约回归。
- `configs/automotive_lighting_us_full.json`：本地 200 帖真实运行配置，用于 OpenCLI 长跑与格式定版验证。
- Reddit适配器输出：OpenCLI与公开JSON通道必须标准化为相同帖子/评论字段。
- `.local/runs/<run_id>/config.snapshot.json`：每次运行的不可变配置快照。

## 当前车灯雷达输出

- `manifest.json`：运行ID、技术状态、`sample_status`、`persona_status`、采集通道、数量和产物路径。
- `candidates.json`：标题扫描、去重、地域分类及高信号评分结果。
- `raw/details/*.json`：每篇标准化帖子及最多20条评论，契约见`schemas/normalized-evidence.schema.json`。
- `analysis.json`：规则分析或可选LLM增强后的唯一报告数据源。
- `evidence.jsonl`：英文原文、Reddit链接、社区、分数和地域状态。
- `keyword_candidates.json`：探索词候选、第二轮查询词、来源证据和状态（`formal`/`exploratory_used`/`candidate_review` 等）。
- `audience_map.json`：产品—社区二部图，契约见`schemas/audience-map.schema.json`。
- `quality_evidence.jsonl`：通过质量门、允许进入正式机会/画像判断的证据子集。
- `excluded_evidence.jsonl`：被质量门排除但仍需审计留痕的证据子集。
- `opportunities.json`：正式机会、候选信号、痛点、竞品/现有产品的分离报告产物。
- `personas.json`：画像结果或样本不足缺口；不允许输出伪画像。
- `report.html`：完全离线的中文卖家报告和Audience Map，不重新调用模型。
- `failures.jsonl`：搜索/详情读取失败；单项失败不得中断后续抓取。
- `optimization_backlog.jsonl`：问题、证据、影响、建议、优先级和处理状态。

`manifest.status` 与业务样本状态分离：

- `status=complete|partial|failed` 只表示技术执行是否完成；
- `sample_status=sufficient|insufficient` 单独表示样本是否达到分析门槛；
- `persona_status=complete|insufficient_sample` 单独表示画像是否达到发布门槛。

因此，`status=complete` 且 `sample_status=insufficient` / `persona_status=insufficient_sample` 是允许且需要如实展示的结果，尤其在 `automotive_lighting_us_full.json` 的 200 帖运行中，当前质量门较严时正式机会可能仍为 0。

## 历史柴油基线输入

- `evidence_candidates.csv`：候选帖子清单，必须包含 `EvidenceId`、`Url`、`Title`、`Platform`、`MatchedCategories`。
- `details_all/*.json`：帖子全文及评论，第一条记录通常为 `POST`，其余为评论层级 `L0/L1/L2...`。
- `profiles/*.json`：主页基础公开信息。
- `user_deep_dive_test/*.json`：公开历史帖子和评论经过研究相关性过滤后的测试结果。

## 历史柴油基线输出

- `analysis.json`：后续模型分析的标准结构化结果。
- `evidence_candidates_中文.xlsx`：业务查看版本。
- HTML、DOCX：历史基线阶段未实现；当前车灯雷达已实现HTML。

## 证据规则

1. 所有结论必须保留原始Reddit链接。
2. 原文事实、AI推断和未知信息必须区分。
3. 多标签聚类允许同一帖子进入多个主题，主题计数不可直接相加为用户总量。
4. 用户画像只使用公开的车辆、场景、产品和购买行为信息。
5. 与研究无关或涉及敏感私人话题的历史内容不得进入画像和报告。
6. 只有明确美国地点、市场或车型信号的帖子进入美国结论；地域未知内容保留但单列。
7. Audience Map的社区节点表示讨论来源，不能解释为人口数量或人口统计画像。
8. 品牌词和新黑话只能进入待人工确认建议，不得自动修改正式配置。
