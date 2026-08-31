[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginPath = Join-Path $repoRoot "opencli-plugin\opportunity-reddit"

$openCliCommand = (Get-Command opencli.cmd -ErrorAction SilentlyContinue).Source
if (-not $openCliCommand) {
    $openCliCommand = (Get-Command opencli -ErrorAction SilentlyContinue).Source
}
if (-not $openCliCommand) {
    throw "opencli was not found. Install OpenCLI first."
}
if (-not (Test-Path -LiteralPath $pluginPath -PathType Container)) {
    throw "Plugin directory was not found: $pluginPath"
}

$installedPluginPath = Join-Path $env:USERPROFILE ".opencli\plugins\opportunity-reddit"
if (Test-Path -LiteralPath $installedPluginPath -PathType Container) {
    Write-Host "Opportunity Radar Reddit plugin is already installed; validating it." -ForegroundColor Yellow
} else {
    if ($openCliCommand -match '\.cmd$') {
        & cmd.exe /d /c "`"$openCliCommand`" plugin install `"$pluginPath`" 2>NUL"
    } else {
        & $openCliCommand plugin install $pluginPath
    }
    if ($LASTEXITCODE -ne 0) {
        throw "OpenCLI plugin installation failed (exit $LASTEXITCODE)."
    }
}
if ($openCliCommand -match '\.cmd$') {
    & cmd.exe /d /c "`"$openCliCommand`" validate opportunity-reddit 2>NUL"
} else {
    & $openCliCommand validate opportunity-reddit
}
if ($LASTEXITCODE -ne 0) {
    throw "OpenCLI plugin validation failed (exit $LASTEXITCODE)."
}

Write-Host "Opportunity Radar Reddit plugin installed successfully." -ForegroundColor Green
