param(
  [string]$BundledNodeModules = "C:\Users\yaobi\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$junction = Join-Path $repoRoot "node_modules"
if (-not (Test-Path -LiteralPath $BundledNodeModules)) { throw "Bundled node_modules not found: $BundledNodeModules" }
if (Test-Path -LiteralPath $junction) {
  Write-Host "RUNTIME_EXISTS $junction"
  exit 0
}
New-Item -ItemType Junction -Path $junction -Target $BundledNodeModules | Out-Null
Write-Host "RUNTIME_READY $junction"
