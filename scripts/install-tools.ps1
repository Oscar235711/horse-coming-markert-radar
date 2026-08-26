[CmdletBinding()]
param(
  [string]$ToolsRoot,
  [string]$ConfigPath,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot ".env" }
$radarConfig = Import-RadarEnv -ConfigPath $ConfigPath
$ToolsRoot = Resolve-RadarPath -Value $(if ($ToolsRoot) { $ToolsRoot } else { Get-RadarSetting -Name "RADAR_TOOLS_ROOT" -Config $radarConfig }) -RepoRoot $repoRoot -DefaultRelative ".tools"

$agentReachCommit = "06c202b03400a7d31886bf4399213706da1a0324"
$agentReachSource = "https://github.com/Panniantong/Agent-Reach/archive/$agentReachCommit.zip"
$openCliPackage = "@jackwener/opencli@1.8.7"
$agentReachRoot = Join-Path $ToolsRoot "agent-reach"
$agentReachVenv = Join-Path $agentReachRoot ".venv"
$agentReachPython = Join-Path $agentReachVenv "Scripts\python.exe"
$agentReachExe = Join-Path $agentReachVenv "Scripts\agent-reach.exe"
$openCliRoot = Join-Path $ToolsRoot "opencli"
$openCliExe = Join-Path $openCliRoot "node_modules\.bin\opencli.cmd"

Write-Host "TOOLS_ROOT $ToolsRoot"
Write-Host "AGENT_REACH_SOURCE $agentReachSource"
Write-Host "OPENCLI_PACKAGE $openCliPackage"
if ($DryRun) { exit 0 }

$uvExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_UV_EXE" -Config $radarConfig) -CommandName "uv"
$npmExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_NPM_EXE" -Config $radarConfig) -CommandName "npm"
if (-not $uvExe) { throw "uv not found. Install uv or set RADAR_UV_EXE in .env" }
if (-not $npmExe) { throw "npm not found. Install Node.js or set RADAR_NPM_EXE in .env" }

New-Item -ItemType Directory -Force -Path $ToolsRoot | Out-Null
if (-not (Test-Path -LiteralPath $agentReachExe)) {
  New-Item -ItemType Directory -Force -Path $agentReachRoot | Out-Null
  & $uvExe venv $agentReachVenv --python 3.12
  if ($LASTEXITCODE -ne 0) { throw "Failed to create Agent Reach virtual environment" }
  & $uvExe pip install --python $agentReachPython $agentReachSource
  if ($LASTEXITCODE -ne 0) { throw "Failed to install Agent Reach" }
}
if (-not (Test-Path -LiteralPath $openCliExe)) {
  New-Item -ItemType Directory -Force -Path $openCliRoot | Out-Null
  & $npmExe install --prefix $openCliRoot --no-audit --no-fund $openCliPackage
  if ($LASTEXITCODE -ne 0) { throw "Failed to install OpenCLI" }
}

if (-not (Test-Path -LiteralPath $agentReachExe)) { throw "Agent Reach executable missing after installation: $agentReachExe" }
if (-not (Test-Path -LiteralPath $openCliExe)) { throw "OpenCLI executable missing after installation: $openCliExe" }
Write-Host "AGENT_REACH_READY $agentReachExe"
Write-Host "OPENCLI_READY $openCliExe"
