# Opportunity Radar 项目库

这里是跨运行自动累积的轻量索引，不保存 Reddit 原文、Cookie 或 API Key。

- `communities.json`：每次运行见到的社区及其来源次数。
- `topics.json`：按“社区 + 规范话题”合并后的历史话题索引。
- `keywords.json`：从帖子、评论和分析字段自动发现的关键词候选。

每次 `radar run` 或离线重建都会更新这三个文件。它们是观察库，不会自动改变四个已批准的扫描社区，也不会把候选词自动加入下一轮检索配置。
