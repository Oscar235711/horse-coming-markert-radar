# Opportunity Radar｜柴油皮卡 Reddit 社区机会雷达

本项目用于扫描北美柴油皮卡 Reddit 社区，把零散的帖子和评论整理成：

```text
社区 → 话题关键词 → 帖子/评论证据 → 可解释分析 → Excel / HTML 报告
```

它服务于 SuncentAuto 的新品和改款探索：帮助团队发现用户反复讨论的问题、已有解决办法的缺口，以及值得继续验证的产品机会。

> 重要：报告中的产品方向是“机会假设”，不是直接开品结论。项目保留市场讨论信号，但不生成违规操作教程。

## 一、当前版本做什么

- 默认扫描四个 Reddit 社区：`r/Cummins`、`r/Duramax`、`r/powerstroke`、`r/FordDiesels`。
- 采集最近 90 天数据，并比较最近 30 天与之前 60 天的信号变化。
- 从 `hot`、`top`、`new` 列表发现候选帖子，再对高信号帖子获取正文、评论和回复。
- 按柴油皮卡平台、车型、使用场景、痛点、需求、方案不足和产品词进行结构化整理。
- 输出社区库、话题关键词库、社区热点排行、话题分析卡、帖子/评论证据和弱信号观察区。
- 支持 DeepSeek/Higress；未配置模型接口时，仍可用本地规则/VOC分析完成采集和基础报告。
- 当前不做用户主页深挖，不生成网络图，重点是先跑通真实数据链路。
- 每次运行还会自动更新项目根目录的 `library/communities.json`、`library/topics.json` 和 `library/keywords.json`，用于跨运行累计观察；它们只保存索引和统计，不保存原文或密钥。

当前完整迁移版本位于 `feature/community-radar` 分支。后续合并到 `main` 后，可去掉克隆命令中的 `-b feature/community-radar`。

## 二、同事拿到仓库后的最短流程

### 1. 克隆并安装项目

Windows PowerShell：

```powershell
git clone -b feature/community-radar https://github.com/Oscar235711/horse-coming-markert-radar.git
cd horse-coming-markert-radar

py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\scripts\radar.ps1 init
```

如果 PowerShell 阻止脚本执行，只对当前窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### 2. 准备 OpenCLI 和 Excel 运行环境

项目的 Reddit 采集首选 OpenCLI + Chrome 持久会话，Agent Reach 不是运行的硬性依赖。

如果本机尚未安装 OpenCLI，可以尝试：

```powershell
.\scripts\install-tools.ps1
```

这个脚本需要本机已有 `uv` 和 `npm`。如果 OpenCLI 已经安装，直接在 `.env` 中填写它的路径即可。先用下面命令查找：

```powershell
where.exe opencli
```

将结果写入 `.env`，例如：

```text
RADAR_OPENCLI_EXE=C:\Users\你的用户名\AppData\Roaming\npm\opencli.cmd
```

完整生成 Excel 需要 Node.js 和项目的 `@oai/artifact-tool` 运行库。已有 Codex 运行库时执行：

```powershell
.\scripts\setup-local-runtime.ps1
```

如果该命令提示找不到运行库，按提示在 `.env` 配置 `RADAR_NODE_MODULES`；或者配置本机 Node：

```text
RADAR_NODE_EXE=C:\Program Files\nodejs\node.exe
```

### 3. 在 Chrome 中登录 Reddit

使用 OpenCLI 即将调用的 Chrome 持久会话登录 Reddit。每位同事使用自己的 Reddit 小号，不要互相复制 Cookie。

验证登录和四个社区是否可读：

```powershell
.\scripts\radar.ps1 doctor
.\scripts\live-reddit-smoke.ps1
```

看到 `WHOAMI_OK` 以及四条 `COMMUNITY_OK`，说明采集环境基本就绪。

## 三、运行真实数据采集

### 不配置 DeepSeek：先跑规则版

这是最快的验证方式，能真实抓取 Reddit 并生成基础分析：

```powershell
.\scripts\radar.ps1 run `
  -RunConfigPath configs/diesel_90d.yaml `
  -RunId 20260828T-user1
```

运行内容包括：

1. 读取四个社区的 `hot/top/new` 帖子列表；
2. 按帖子 ID 去重并限制最近 90 天；
3. 为每个社区最多深读 30 篇高信号帖子；
4. 保存正文、评论、回复和原始链接；
5. 用本地规则提取平台、场景、痛点、需求和候选话题；
6. 生成 JSON、Excel 和离线 HTML 报告。

### 配置公司 Higress DeepSeek：再跑模型版

复制 `.env.example` 生成的 `.env` 只保存在本机，填写公司网关配置：

```text
DEEPSEEK_BASE_URL=https://higress.suncentgroup.com/gzsyb/v1
在 `.env` 中配置 `DEEPSEEK_API_KEY`（填写公司分配的 Token）。
DEEPSEEK_FLASH_MODEL=deepseek-v4-flash
DEEPSEEK_PRO_MODEL=deepseek-v4-pro
```

不要把 Token 写进代码、配置提交、日志、Excel 或报告。模型版会使用 Flash 做帖子级提取，用 Pro 做社区内话题归并；采集流程不变。

## 四、查看结果

每次运行都写入：

```text
.local\runs\<run_id>\
├─ raw\                         原始列表、帖子和评论
├─ normalized\                  标准化帖子/评论
├─ checkpoints\                 断点文件
├─ suggestions\                 待审批的社区/关键词建议
└─ artifacts\
   ├─ analysis.json              唯一规范分析结果
   ├─ community_topics.json      话题数据投影
   ├─ community_topics.xlsx      Excel 报告
   ├─ report.html                WhatToSell 风格离线报告
   └─ community_topic_map.json   后续图谱使用的数据投影
```

直接双击 `report.html` 即可查看报告；打开 `community_topics.xlsx` 可查看以下工作表：

- 运行概览
- 社区库
- 话题关键词库
- 社区热点排行
- 话题分析卡
- 帖子及评论证据
- 弱信号观察区
- 排除与失败记录

所有报告都从同一份 `analysis.json` 生成，避免 HTML、Excel 和 JSON 的数字不一致。

## 五、失败后如何继续

单个帖子失败不会让整轮任务失效。遇到限流、页面失败或网络中断，使用同一个运行 ID 续跑：

```powershell
.\scripts\radar.ps1 resume -RunId 20260828T-user1
```

查看运行状态：

```powershell
.\scripts\radar.ps1 status -RunId 20260828T-user1
```

重新导出已经保存的结果：

```powershell
.\scripts\radar.ps1 export `
  -RunId 20260828T-user1 `
  -Formats json,xlsx,html
```

如果只有之前保存的原始数据，也可以跳过模型接口重新生成本地报告：

```powershell
.\.venv\Scripts\python scripts\rebuild_local_analysis.py `
  --run-id 20260828T-user1
```

## 六、社区库和关键词库

当前活动社区库是：

```text
configs/community_catalog.v1.yaml
```

首轮固定四个社区，不自动扩张。每个社区记录别名、纳入词、排除词、平台、品牌和社区黑话。

话题关键词会从正式词库、帖子标题/正文、评论和分析结果中产生。候选词不会自动改变正式配置，需要人工查看后审批：

```powershell
python -m opportunity_radar communities suggest --run-id <run_id>
python -m opportunity_radar communities approve `
  --suggestion <suggestion_file> `
  --suggestion-id <suggestion_id>
```

正式扫描配置位于：

```text
configs/diesel_90d.yaml
```

如需调整时间范围、深读数量或评论数量，只修改配置文件并提交说明，不要直接改动运行目录中的快照。

每次运行结束后，项目库会自动累计本轮见到的社区、稳定话题和关键词候选：

```text
library/
├─ communities.json
├─ topics.json
└─ keywords.json
```

项目库是跨运行的观察索引，不会自动扩张本轮固定的四个扫描社区，也不会把候选词直接变成正式检索词。

## 七、常用命令

```powershell
# 环境检查
.\scripts\radar.ps1 doctor

# 查看路径
.\scripts\radar.ps1 paths

# 真实采集并分析
.\scripts\radar.ps1 run -RunConfigPath configs/diesel_90d.yaml

# 断点续跑
.\scripts\radar.ps1 resume -RunId <run_id>

# 查看状态
.\scripts\radar.ps1 status -RunId <run_id>

# 导出报告
.\scripts\radar.ps1 export -RunId <run_id> -Formats json,xlsx,html

# 运行测试
pytest
```

也可以直接使用 Python 入口：

```powershell
.\.venv\Scripts\python -m opportunity_radar doctor
.\.venv\Scripts\python -m opportunity_radar run --config configs/diesel_90d.yaml
```

直接使用 Python 时，需要先在当前终端设置环境变量；PowerShell 包装脚本会自动读取仓库根目录的 `.env`。

## 八、常见问题

### `OpenCLI not found`

执行 `where.exe opencli`，把完整路径写入 `.env` 的 `RADAR_OPENCLI_EXE`，然后重新运行 `doctor`。

### `No Reddit cookies found` 或未通过 `WHOAMI_OK`

说明 OpenCLI 使用的 Chrome 持久会话没有登录 Reddit。请在该会话中完成登录后重新运行 `live-reddit-smoke.ps1`。不需要 Firefox。

### Reddit 返回 429

这是限流。等待一段时间后使用 `resume`，不要反复新建运行任务。

### DeepSeek 返回 401 或 404

检查 `.env` 中的 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和模型名称。公司网关配置不应填写 DeepSeek 官方地址。

### 找不到 Node 或无法生成 XLSX

运行 `doctor` 查看 Node 路径；设置 `RADAR_NODE_EXE`，并确认 `RADAR_NODE_MODULES` 指向包含 `@oai/artifact-tool` 的目录。只需要 JSON/HTML 时，可以先保存原始数据，之后补齐 Node 再执行 `export`。

### `run_id already exists`

同一个 ID 已经有运行目录。未完成任务使用 `resume`；要重新开始则换一个新的运行 ID。

## 九、三人协作方式

- 采集负责人：维护自己的 Chrome/Reddit 登录态，运行 `doctor`、`live-reddit-smoke` 和真实采集。
- 分析负责人：查看 `analysis.json`、Excel 和 HTML，复核话题、证据和机会假设。
- 配置/代码负责人：维护社区库、关键词库、CLI、报告和测试。

建议每个人使用自己的 Git 分支，提交代码和配置变更；运行结果用 `run_id` 标识，通过公司内部渠道共享报告。

以下内容已经被 `.gitignore` 排除，禁止提交：

```text
.env
.local/
.tools/
.venv/
cookies/
credentials/
原始 Reddit 数据和包含个人信息的导出文件
```

## 十、验收标准

一次完整运行至少应满足：

- 四个种子社区能够读取；
- 原始帖子、评论和原帖链接可回查；
- 最近 30 天与前 60 天可以区分；
- 社区库和话题关键词库有明确记录；
- HTML、Excel 和 JSON 的社区数、话题数和核心结论一致；
- 失败记录可见，单个帖子失败不影响整轮运行；
- 未配置 DeepSeek 时仍可完成规则版采集与报告；
- API Key、Cookie 和绝对路径不进入 GitHub。
