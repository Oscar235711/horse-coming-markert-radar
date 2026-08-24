# horse-coming-markert-radar
马来——北美产品机会雷达
🐴 训练方案-Opportunity Radar
Opportunity Radar GitHub + Skill MVP 实施计划
1. 项目目标与边界
建设公司私有仓库 suncentauto/opportunity-radar，为北美柴油皮卡改装新品探索提供：
●全品类粗扫和指定主题探索两种模式。
●Reddit帖子、评论及公开用户主页分析。
●新品方向、产品改进点、竞品反馈和用户画像。
●千问、DeepSeek API分析能力。
●可被Codex调用的 SKILL.md。
●可被Hermes周期执行的统一命令。
●中文结论、英文证据的HTML和DOCX报告。
第一期明确不建设网站，不接内部访谈、订单和购买数据。网站仅作为Skill连续运行成功、报告被业务采用后的产品化阶段。
涉及DPF/EGR delete、排放绕过或其他灰色改装的讨论不从研究数据中删除，系统将其标记为需求、争议或风险信号，但不生成具体违规操作教程。
2. 核心实现
仓库与技术架构
采用Python 3.12单仓库：
●src/opportunity_radar/：CLI、配置、采集、分析、用户画像、报告和本地存储。
●configs/：默认配置、品类配置、月度/季节配置及待确认建议。
●skills/opportunity-radar/SKILL.md：Codex自然语言调用说明。
使用SQLite保存去重缓存、历史运行索引和趋势基线；每次任务的完整产物保存到Git忽略的 .local/runs/<run_id>/。
Reddit获取通过Agent Reach选择OpenCLI或rdt-cli通道。专用Reddit小号登录态只存于公司受控电脑，不进入仓库、配置、日志或报告。
模型层使用统一的OpenAI兼容适配器：
●千问：配置DashScope兼容地址、API Key环境变量和模型名。官方接口文档
●DeepSeek：配置DeepSeek地址、API Key环境变量和模型名。官方接口文档
●默认优先千问，失败时按配置决定是否切换DeepSeek；模型切换不得改变分析JSON结构。
分析流水线
1.合并默认、品类、月度和本次任务配置，并保存不可变快照。
2.搜索Reddit帖子并读取评论、作者、时间、热度、Subreddit和原始链接。
3.去重，过滤纯广告和明显机器人内容。
4.提取主题、改装场景、车辆平台、痛点、现有方案、解决方案不足、竞品提及、购买信号、新词和黑话。
5.情绪分析针对“配置的主题或竞品”，输出正面、中性、负面，不分析无关的一般情绪。
6.根据独立用户数、讨论量、互动量及上期变化，标记新出现、上升、稳定和下降话题。
7.选择最多30名高相关作者，读取其近180天、最多50条公开活动，聚合为3–6类人群，并展示最多10名代表用户。
8.生成统一 analysis.json，再由固定模板生成HTML和DOCX，不允许两种报告分别重新调用模型。
9.生成下一期关键词、黑话和竞品词变更建议；必须人工确认后才能写入新配置版本。
任务按阶段保存检查点。帖子获取、评论获取、用户主页和模型分析均可独立重试；部分主页无法访问时仍生成报告，并标明用户样本不足。
3. 公共接口、配置与产物
CLI接口
●radar doctor  
检查Python依赖、Agent Reach、Reddit登录态、千问/DeepSeek API和报告环境。
●radar run --config <path> [--set key=value]  
执行全品类或指定主题探索，是Codex和Hermes共用入口。
●radar status --run-id <id>  
查看当前阶段、采集数量、失败数量、Token和预计成本。
●radar report --run-id <id> --formats html,docx  
从已有 analysis.json 重建报告。
●radar config suggest --run-id <id>  
生成下一期配置建议及证据。
●radar config approve --suggestion <path> --period YYYY-MM  
人工确认后生成新的月度配置，不覆盖历史配置。
配置Schema
配置固定包含：
●search.mode：broad 或 topic
●search.start_date/end_date；未指定时默认回看90天
●search.categories
●search.subreddits
●search.include_keywords
●search.exclude_keywords
●search.slang
●search.competitors[]：竞品名及关键词
●sentiment.targets：主题和竞品
●limits.posts/comments
●profiles.enabled/max_users/lookback_days/max_items_per_user
●llm.provider/base_url/model/api_key_env
●report.language=zh-CN
●report.evidence_language=original
配置优先级固定为：
默认配置 < 品类配置 < 月度配置 < 本次CLI覆盖
默认样本：
●指定主题：100篇帖子、600条评论。
●全品类粗扫：300篇帖子、1500条评论。
●用户画像：30名候选、最多10名代表用户。
结果类型
AnalysisResult 必须包括：
●探索范围和运行指标
●主题、情绪、热词及趋势
●竞品分析
●新品机会和产品改进机会
●用户人群及代表用户
●原文证据索引
●下期配置建议
●模型、Token、成本和失败记录
每项产品机会包含：机会类型、用户场景、问题、现有方案、方案缺口、产品假设、相关车辆/平台、人群、趋势、置信度和证据ID。
HTML为单文件、离线可打开的交互报告；DOCX使用相同章节和数据生成静态图表及表格。两份报告均包含：
●一页核心结论
●讨论量、情绪、热词和Subreddit分布
●新出现及上升主题
●竞品优缺点
●新品和改进方向
●用户画像及代表用户
●下期配置建议
●英文原文证据和Reddit链接附录
4. 开发顺序与测试
实施顺序
1.搭建Python包、CLI、核心Schema、私有仓库CI和密钥忽略规则。
2.完成配置合并、验证、快照和月度版本管理。
3.完成Agent Reach适配、帖子/评论/主页标准化、去重、缓存和断点续跑。
4.完成千问、DeepSeek适配及结构化分析流水线。
5.完成产品机会、竞品、情绪、趋势和用户画像聚合。
6.完成HTML与DOCX固定模板。
7.完成Codex Skill、Hermes调用示例、安装文档和业务使用说明。
8.用真实专用小号执行指定主题与全品类验收。
自动化测试
●配置优先级、字段校验、月度版本及快照不可变测试。
●Reddit搜索结果、评论树、作者主页的模拟适配测试。
●去重、限流、断点续跑及部分失败测试。
●千问与DeepSeek模拟服务的JSON Schema一致性测试。
●HTML与DOCX核心数字、Top机会和画像一致性测试。
●无网络环境下HTML离线打开测试。
●仓库、日志和报告的API Key/Cookie扫描测试。
●不可访问主页、空搜索结果、模型超时、无效JSON和API限流测试。
业务验收
●全品类和指定主题两种任务均可完成。
●时间、关键词、Subreddit、竞品、情绪和样本量均可自定义。
●100条人工标注评论上，主题及正中负综合准确率达到80%。
●每个新品或改进结论至少有一条真实可点击证据，虚构链接为0。
●HTML与DOCX的核心数字和结论完全一致。
●指定主题默认30分钟内完成，全品类默认60分钟内完成；限流时必须显示原因。
●Codex能通过Skill从自然语言生成配置并完成任务。
●Hermes能按配置无人值守运行并返回报告路径。
●AI配置建议未经人工确认不得进入正式月度配置。
5. Hermes运行与默认假设
●公司私有GitHub仓库，运行环境为公司受控电脑/Hermes内部环境。
●前三个月在每月1日和15日09:00（Asia/Shanghai）运行；之后每月1日09:00运行。
●每期与上一次相同范围结果比较；满一年后形成1–12月季节配置。
●8月初始重点词包含返校季、DPF、EGR、改装合法性及已知黑话；后续根据实际数据提交增删和权重调整建议。
●中文输出分析结论，英文保留原始证据。
●API Key使用环境变量；Cookie继续由Agent Reach/rdt-cli本地管理。
●第一期不建设网站、不做多人权限、不接内部VOC、不训练模型。
●网站产品化时继续复用现有CLI、配置Schema、SQLite历史数据和 analysis.json，不重写采集分析核心。
