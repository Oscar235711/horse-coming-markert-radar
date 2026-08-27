# Community Radar 使用指南

## 首次准备

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\scripts\radar.ps1 init
.\scripts\install-tools.ps1
.\scripts\setup-local-runtime.ps1
.\scripts\radar.ps1 paths
.\scripts\radar.ps1 doctor
```

`doctor` 会检查 Python、依赖、Agent Reach/OpenCLI 路径、Reddit `whoami`、四个种子社区、DeepSeek 变量、运行目录和 Excel 导出环境。没有 `DEEPSEEK_API_KEY` 时只会警告。

## 日常运行

```powershell
python -m opportunity_radar run --config configs/diesel_90d.yaml
python -m opportunity_radar resume --run-id <run_id>
python -m opportunity_radar status --run-id <run_id>
python -m opportunity_radar export --run-id <run_id> --formats json,xlsx
```

PowerShell 等价入口：

```powershell
.\scripts\radar.ps1 run -RunConfigPath configs/diesel_90d.yaml
.\scripts\radar.ps1 resume -RunId <run_id>
.\scripts\radar.ps1 export -RunId <run_id> -Formats json,xlsx
```

## 社区建议审批

```powershell
python -m opportunity_radar communities suggest --run-id <run_id>
python -m opportunity_radar communities approve --suggestion .local\runs\<run_id>\suggestions\community_suggestions.json --suggestion-id <id>
```

审批会生成新的社区版本文件，但不会自动替换当前活动版本。

## 三人协作分工

1. 采集同学只负责 `.env`、浏览器登录态和 `doctor` / `live-reddit-smoke.ps1`
2. 分析同学运行 `run` / `resume` / `status` / `export`，共享 `run_id` 和导出路径
3. 策略同学查看建议文件并审批生成新版本配置

## 本地安全边界

- `.env`、Cookie、原始数据、运行产物都不进入 Git
- `state.json` 和 `manifest.json` 只保存摘要、计数和路径，不保存密钥
- 建议文件只引用证据 URL，不保存登录态

## 显式联机冒烟

```powershell
.\scripts\live-reddit-smoke.ps1
```

这个脚本只做最小 Reddit 连通性检查，适合在切换电脑、Chrome 配置或 OpenCLI 版本后手动运行。
