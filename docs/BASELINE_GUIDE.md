# Opportunity Radar MVP Baseline

这是Suncentauto北美柴油皮卡改装机会雷达的本地可版本化基线。当前固化已验证的数据链路，不包含Cookie、API Key或任何登录凭据。

## 已固定的能力

1. Reddit候选帖子扫描结果处理；
2. 完整帖子与评论批量读取；
3. 中文Excel证据包生成；
4. AI预复核、需求聚类和产品机会卡第一版；
5. 代表用户公开历史深挖测试；
6. 数据、安全和画像选择规则。

## 快速检查

```powershell
.\scripts\setup-local-runtime.ps1
.\scripts\radar.ps1 doctor
.\scripts\radar.ps1 status
.\scripts\radar.ps1 verify-baseline
.\scripts\radar.ps1 report
```

## 继续采集

```powershell
.\scripts\radar.ps1 fetch-details `
  -EvidenceCsv "D:\zuop\agent-reach\data\processed-20260826\evidence_candidates.csv" `
  -OutputDir "D:\zuop\agent-reach\data\processed-20260826\details_all"
```

## 用户主页深挖测试

```powershell
.\scripts\radar.ps1 deep-dive `
  -Users "ace_mcgee68,Lucky_Wrongdoer1270,Lil-quacker" `
  -OutputDir "D:\zuop\agent-reach\data\processed-20260826\user_deep_dive_test"
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
