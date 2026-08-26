param(
  [string]$BundledNodeModules,
  [string]$ConfigPath,
  [string]$JunctionPath
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$common = Join-Path $PSScriptRoot "common.ps1"
. $common
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot ".env" }
$radarConfig = Import-RadarEnv -ConfigPath $ConfigPath

if (-not $JunctionPath) { $JunctionPath = Join-Path $repoRoot "node_modules" }
$JunctionPath = Resolve-RadarPath -Value $JunctionPath -RepoRoot $repoRoot -DefaultRelative "node_modules"
$candidates = @()
if ($BundledNodeModules) { $candidates += $BundledNodeModules }
$configuredNodeModules = Get-RadarSetting -Name "RADAR_NODE_MODULES" -Config $radarConfig
if ($configuredNodeModules) { $candidates += $configuredNodeModules }
if ($env:USERPROFILE) { $candidates += (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules") }
$sourceModules = $candidates | ForEach-Object { [Environment]::ExpandEnvironmentVariables($_) } | Where-Object {
  Test-Path -LiteralPath (Join-Path $_ "@oai\artifact-tool\package.json")
} | Select-Object -First 1

if (-not $sourceModules) {
  throw "Report runtime not found. Set RADAR_NODE_MODULES in $ConfigPath to a node_modules directory containing @oai/artifact-tool."
}
if (Test-Path -LiteralPath $JunctionPath) {
  if (-not (Test-Path -LiteralPath (Join-Path $JunctionPath "@oai\artifact-tool\package.json"))) {
    throw "Runtime target exists but does not contain @oai/artifact-tool: $JunctionPath"
  }
  Write-Host "RUNTIME_EXISTS $JunctionPath"
  exit 0
}
$parent = Split-Path -Parent $JunctionPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
New-Item -ItemType Junction -Path $JunctionPath -Target $sourceModules | Out-Null
Write-Host "RUNTIME_READY $JunctionPath"
