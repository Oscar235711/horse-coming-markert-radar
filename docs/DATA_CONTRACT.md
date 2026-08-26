# 数据契约

## 固定输入

- `evidence_candidates.csv`：候选帖子清单，必须包含 `EvidenceId`、`Url`、`Title`、`Platform`、`MatchedCategories`。
- `details_all/*.json`：帖子全文及评论，第一条记录通常为 `POST`，其余为评论层级 `L0/L1/L2...`。
- `profiles/*.json`：主页基础公开信息。
- `user_deep_dive_test/*.json`：公开历史帖子和评论经过研究相关性过滤后的测试结果。

## 固定输出

- `analysis.json`：后续模型分析的标准结构化结果。
- `evidence_candidates_中文.xlsx`：业务查看版本。
- HTML、DOCX：下一阶段实现。

## 证据规则

1. 所有结论必须保留原始Reddit链接。
2. 原文事实、AI推断和未知信息必须区分。
3. 多标签聚类允许同一帖子进入多个主题，主题计数不可直接相加为用户总量。
4. 用户画像只使用公开的车辆、场景、产品和购买行为信息。
5. 与研究无关或涉及敏感私人话题的历史内容不得进入画像和报告。
