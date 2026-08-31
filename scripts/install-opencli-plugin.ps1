[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginPath = Join-Path $repoRoot "opencli-plugin\opportunity-reddit"

if (-not (Get-Command opencli -ErrorAction SilentlyContinue)) {
    throw "未找到 opencli。请先安装 OpenCLI，再运行此脚本。"
}
if (-not (Test-Path -LiteralPath $pluginPath -PathType Container)) {
    throw "找不到项目插件目录：$pluginPath"
}

& opencli plugin install $pluginPath
if ($LASTEXITCODE -ne 0) {
    throw "OpenCLI 插件安装失败（exit $LASTEXITCODE）。"
}
& opencli validate opportunity-reddit
if ($LASTEXITCODE -ne 0) {
    throw "OpenCLI 插件校验失败（exit $LASTEXITCODE）。"
}

Write-Host "Opportunity Radar Reddit 分页/深读插件安装成功。" -ForegroundColor Green
