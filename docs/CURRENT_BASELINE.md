# 当前固定基线

基线日期：2026-08-26

## 已验证

- Chrome登录态可供OpenCLI读取Reddit公开内容。
- 90天扫描得到78条原始结果、60条窗口内结果、41条去重帖子。
- 41/41条帖子完成全文与评论读取，共保存353条评论记录。
- 已生成中文Excel，包含候选表、完整帖子、评论明细、AI预复核、产品机会卡和用户画像。
- 已读取9位作者的主页基础公开信息。
- 已完成用户历史深挖测试：读取公开帖子和评论，过滤无关及敏感内容，形成5个行为型画像案例。

## 当前限制

- AI预复核和聚类仍以规则/关键词为主，不能视为最终产品结论。
- 多标签机会计数存在重叠。
- 大部分正文和评论保留英文原文，中文为标题、摘要或业务提示，不是逐句翻译。
- 尚未接入稳定的千问/DeepSeek结构化分析。
- 尚未实现HTML、DOCX、Codex Skill和Hermes周期任务。

## 已验证产物位置

- 数据根目录：`D:\zuop\agent-reach\data\processed-20260826`
- Excel：`D:\zuop\agent-reach\outputs\20260826\evidence_candidates_中文.xlsx`
- 用户深挖测试报告：`D:\zuop\agent-reach\outputs\20260826\user_deep_dive_test_report.md`
