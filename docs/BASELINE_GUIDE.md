# Opportunity Radar MVP Baseline

这是Suncentauto北美柴油皮卡改装机会雷达的本地可版本化基线。当前固化已验证的数据链路，不包含Cookie、API Key或任何登录凭据。

## 已固定的能力

1. Reddit候选帖子扫描结果处理；
2. 完整帖子与评论批量读取；
3. 中文Excel证据包生成；
4. AI预复核、需求聚类和产品机会卡第一版；
5. 代表用户公开历史深挖测试；
6. 数据、安全和画像选择规则。

## 新电脑首次安装

```powershell
git clone https://github.com/Oscar235711/horse-coming-markert-radar.git
cd horse-coming-markert-radar
.\scripts\radar.ps1 init
.\scripts\install-tools.ps1
.\scripts\setup-local-runtime.ps1
.\scripts\radar.ps1 paths
.\scripts\radar.ps1 doctor
.\scripts\radar.ps1 status
```

`init`会创建被Git忽略的`.env`及`.local`目录，不会覆盖已经存在的`.env`。相对路径始终按仓库根目录解析，因此仓库可以放在任意磁盘和目录。

`install-tools.ps1`会把固定版本的Agent Reach和OpenCLI安装到仓库自己的`.tools`目录，不要求全局安装，也不会包含或复制Chrome Cookie。`setup-local-runtime.ps1`会优先读取`.env`中的`RADAR_NODE_MODULES`，未设置时自动查找当前Windows用户的Codex运行时。

如果`install-tools.ps1`提示缺少`uv`或`npm`，先安装Python环境管理器uv和Node.js，或者在`.env`中配置`RADAR_UV_EXE`、`RADAR_NPM_EXE`。如需使用电脑上已有的Agent Reach/OpenCLI，也可通过`RADAR_AGENT_REACH_EXE`、`RADAR_OPENCLI_EXE`覆盖项目内版本。

## 放入本地数据后检查

GitHub不包含原始Reddit数据、Cookie、API Key或历史报告。把采集结果放入`.env`配置的`RADAR_DATA_ROOT`后再运行：

```powershell
.\scripts\radar.ps1 verify-baseline
.\scripts\radar.ps1 report
```

已有数据在其他目录时，可以直接修改`.env`，例如：

```text
RADAR_DATA_ROOT=E:\opportunity-radar-data\processed
RADAR_OUTPUT_ROOT=E:\opportunity-radar-data\outputs
```

## 继续采集

### 美国车灯统一试跑（推荐）

```powershell
.\scripts\radar.ps1 run -Transport opencli
```

如需先做远程/公开 JSON 契约回归，优先使用：

```powershell
.\scripts\radar.ps1 run `
  -ResearchConfig "configs\automotive_lighting_us_mini.json" `
  -Transport public-json
```

如需复现 2026-08-28 的 200 帖真实运行边界，使用：

```powershell
.\scripts\radar.ps1 run `
  -ResearchConfig "configs\automotive_lighting_us_full.json" `
  -Transport opencli
```

`automotive_lighting_us_full.json` 会保留 14 个锚点词并把帖子上限拉到 200；在 Windows + Chrome 登录态 + OpenCLI 条件下，完整长跑通常需要约 2-3 小时。

如果本机没有可用的Reddit浏览器登录态，可改用：

```powershell
.\scripts\radar.ps1 run -Transport public-json
```

报告位于`.local\runs\<run_id>\report.html`。同一`RunId`重复执行时，已完成帖子直接读取检查点，只重试失败项。运行中发现的仓库问题写入`optimization_backlog.jsonl`，不会阻止后续帖子抓取。

阅读结果时请区分三类状态：

- `manifest.status`：技术执行状态，只反映运行是否完成、部分完成或失败；
- `sample_status`：样本是否足够支撑当前分析；
- `persona_status`：画像是否达到发布门槛。

真实 200 帖运行即使 `manifest.status=complete`，也可能因为当前质量门要求较严格而出现 `sample_status=insufficient`、`persona_status=insufficient_sample`，并最终得到 `opportunities=0`。这表示“规则下证据不足”，不是程序异常。

### 历史CSV详情采集

```powershell
.\scripts\radar.ps1 fetch-details `
  -EvidenceCsv ".local\data\evidence_candidates.csv" `
  -OutputDir ".local\data\details_all"
```

## 用户主页深挖测试

```powershell
.\scripts\radar.ps1 deep-dive `
  -Users "ace_mcgee68,Lucky_Wrongdoer1270,Lil-quacker" `
  -OutputDir ".local\data\user_deep_dive_test"
```

## 安全边界

- 不提交Cookie和API Key；
- 只读取公开内容；
- 不提取或推断真实姓名、住址、联系方式、健康、种族、精确收入等敏感信息；
- 与研究无关或敏感的主页历史不进入画像；
- 排放相关讨论可以作为需求信号，但系统不生成违规操作教程。

## 后续方向

1. 用更大样本校准机会评分和美国地域识别；
2. 补充可审计的供应链、价格和退货证据；
3. 封装Codex Skill；
4. 继续补充DOCX静态报告；
5. 根据GitHub Actions运行效果决定是否接入Hermes。
