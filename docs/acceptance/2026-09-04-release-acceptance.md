# Opportunity Radar 发布验收记录（2026-09-04）

## 验收范围

本次验收覆盖：四个柴油皮卡种子社区的 Reddit 时间范围流程、关键词全站搜索覆盖、可解释的社区/关键词库、DeepSeek VOC 接口边界、Hot30 多平台 Skill、中文报告、Excel 外链和本地网页任务控制。

本记录只使用已保存运行和离线 fixture，不包含 API Key、Cookie 或 Chrome 配置。真实网络运行的数量以各自 `run_manifest.json`、`analysis.json` 和 `source_status.json` 为准。

## 已验证运行

| 流程 | Run ID | 结果 | 备注 |
|---|---|---|---|
| Reddit 365 天基线 | `20260831T-full365` | `partial`（历史文件曾记录为 completed） | 扫描 4,000 帖，深读 320 帖，分析 88 帖；Cummins、FordDiesels、powerstroke 未到达请求起点。新版本会依据 coverage 输出 `partial`。 |
| Hot30 多平台样例 | `20260904T145458Z-70bda5` | 已生成 Skill JSON/HTML/Markdown/来源状态 | 330 条来源证据、7 个中文热点；Reddit、Digg、GitHub、Hacker News 有返回，TikTok/Instagram 未配置，YouTube 无结果。 |

## 自动化验收

- Python 测试：全套 `pytest` 通过。
- Reddit OpenCLI 插件测试：6 项通过。
- 发布契约：报告图谱只展示有正式话题的社区；社区 hash 预览函数存在；移动端 hash 不产生空白详情；Excel 证据单元格使用真实 OOXML external hyperlink；Skill 文本严格 UTF-8、PowerShell 脚本可解析。
- Hot30：normal topic 与 discovery 写入同一份 `analysis.json` 的 `discovery` 节点；来源未配置、无结果、限流和失败状态分开显示。

## 产物位置

- Reddit HTML/Excel/JSON：`.local/runs/<run_id>/artifacts/`
- Hot30 HTML/Markdown/JSON/来源状态：`.local/runs/<run_id>/artifacts/`
- 项目级社区、关键词、话题库：`library/`
- 运行配置快照与覆盖状态：`.local/runs/<run_id>/`

## 已知限制

1. Reddit 的登录态、分页边界和限流由每台成员电脑决定；未到达开始日期时必须标记 `partial`，不能称为全量。
2. TikTok/Instagram 需要本机 `SCRAPECREATORS_API_KEY`；X 按当前项目约定不请求。无凭据的平台不会被伪装成“无讨论”。
3. DeepSeek 只读取已保存证据并返回结构化 VOC。网关不可用时，任务保留失败/检查点，不使用规则模板冒充模型结论。
4. `library/` 是跨运行累计索引；只有满足独立帖子、独立作者和柴油相关性门槛的社区/关键词才会进入下一轮活动库。
