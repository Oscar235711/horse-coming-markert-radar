[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginPath = Join-Path $repoRoot "opencli-plugin\opportunity-reddit"

if (-not (Get-Command opencli -ErrorAction SilentlyContinue)) {
    throw "opencli was not found. Install OpenCLI first."
}
if (-not (Test-Path -LiteralPath $pluginPath -PathType Container)) {
    throw "Plugin directory was not found: $pluginPath"
}

$installedPlugins = (& opencli plugin list --format json 2>$null | Out-String)
if ($installedPlugins -match '"name"\s*:\s*"opportunity-reddit"') {
    Write-Host "Opportunity Radar Reddit plugin is already installed; validating it." -ForegroundColor Yellow
} else {
    & opencli plugin install $pluginPath
    if ($LASTEXITCODE -ne 0) {
        throw "OpenCLI plugin installation failed (exit $LASTEXITCODE)."
    }
}
& opencli validate opportunity-reddit
if ($LASTEXITCODE -ne 0) {
    throw "OpenCLI plugin validation failed (exit $LASTEXITCODE)."
}

Write-Host "Opportunity Radar Reddit plugin installed successfully." -ForegroundColor Green
