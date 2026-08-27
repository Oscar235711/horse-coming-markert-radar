param(
  [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot ".env" }
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$radarConfig = Import-RadarEnv -ConfigPath $ConfigPath

$toolsRoot = Resolve-RadarPath -Value (Get-RadarSetting -Name "RADAR_TOOLS_ROOT" -Config $radarConfig) -RepoRoot $repoRoot -DefaultRelative ".tools"
$openCliFallbacks = @(
  (Join-Path $toolsRoot "opencli\node_modules\.bin\opencli.cmd"),
  (Join-Path $toolsRoot "opencli\node_modules\.bin\opencli")
)
$openCliExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_OPENCLI_EXE" -Config $radarConfig) -CommandName "opencli" -FallbackPaths $openCliFallbacks -PreferFallbacks
if (-not $openCliExe) { throw "OpenCLI not found. Install it or set RADAR_OPENCLI_EXE in $ConfigPath" }

$communities = @("Cummins", "Duramax", "powerstroke", "FordDiesels")
$whoami = & $openCliExe reddit whoami -f json | ConvertFrom-Json
Write-Host ("WHOAMI_OK " + $whoami.username)

foreach ($community in $communities) {
  $items = & $openCliExe reddit hot $community --limit 1 -f json | ConvertFrom-Json
  Write-Host ("COMMUNITY_OK " + $community + " " + @($items).Count)
}
