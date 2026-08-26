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
.\scripts\setup-local-runtime.ps1
.\scripts\radar.ps1 paths
.\scripts\radar.ps1 doctor
.\scripts\radar.ps1 status
```

`init`会创建被Git忽略的`.env`及`.local`目录，不会覆盖已经存在的`.env`。相对路径始终按仓库根目录解析，因此仓库可以放在任意磁盘和目录。

如果`doctor`提示找不到Agent Reach或OpenCLI，编辑`.env`填写对应安装位置；如果命令已经在PATH中则保持为空。`setup-local-runtime.ps1`会优先读取`.env`中的`RADAR_NODE_MODULES`，未设置时自动查找当前Windows用户的Codex运行时。

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

## 下一阶段

1. 生成统一`analysis.json`；
2. 接入千问/DeepSeek结构化分析；
3. 封装Codex Skill；
4. 生成HTML和DOCX；
5. 接入Hermes周期运行。
