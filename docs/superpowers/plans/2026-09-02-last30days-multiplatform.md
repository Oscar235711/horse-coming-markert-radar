# Opportunity Radar 多平台近30天热点与时间范围研究

## Goal

将完整的 last30days 多平台热点能力移植到项目内，新增独立的“近30天多平台热点”入口；保留 Opportunity Radar 的 Reddit 时间范围深度研究入口。热点引擎不改成 Reddit 专用，默认主题为北美柴油皮卡改装。

## Global constraints

- 不重新爬取历史 Reddit 数据作为本次实现前置条件。
- last30days 原始脚本、doctor、发现协议、来源适配器和研究库作为独立 vendor 快照保存。
- 网站运行时不依赖用户个人 `C:\Users\\...\\.codex\\skills` 路径。
- 多平台来源按实际配置显示可用、未配置、限流、失败或无结果。
- Reddit 时间范围研究保持现有核心社区+全站关键词逻辑。
- API Key、Cookie 和认证信息不进入仓库、日志或产物。

## Tasks

1. Vendor last30days snapshot and add a local adapter that runs nominate/judge/finalize with DeepSeek-compatible judging.
2. Add dashboard/server hot30 and range modes, progress, source health, and artifact links without breaking current endpoints.
3. Add trend projection, diesel defaults, tests, documentation, and team run instructions.

## Acceptance

- Project-local `vendor/last30days` can run its CLI without the personal skill path.
- Hot30 can be created without a research question and produces source status plus brief/trends artifacts.
- Range mode accepts dates with an optional focus question.
- Existing tests continue to pass; new tests cover mode validation and output projection.
- The complete last30days upstream brief remains available and is not replaced by a Reddit-only template.
