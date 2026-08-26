param(
  [Parameter(Position = 0, Mandatory = $true)]
  [ValidateSet("init", "paths", "doctor", "status", "verify-baseline", "fetch-details", "deep-dive", "report")]
  [string]$Command,
  [string]$EvidenceCsv,
  [string]$OutputDir,
  [string]$Users,
  [string]$DataRoot,
  [string]$OutputRoot,
  [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot ".env" }
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
Import-RadarEnv -ConfigPath $ConfigPath

$DataRoot = Resolve-RadarPath -Value $(if ($DataRoot) { $DataRoot } else { $env:RADAR_DATA_ROOT }) -RepoRoot $repoRoot -DefaultRelative ".local\data"
$OutputRoot = Resolve-RadarPath -Value $(if ($OutputRoot) { $OutputRoot } else { $env:RADAR_OUTPUT_ROOT }) -RepoRoot $repoRoot -DefaultRelative ".local\outputs"
$agentReachHome = Resolve-RadarPath -Value $env:RADAR_AGENT_REACH_HOME -RepoRoot $repoRoot -DefaultRelative ".local\agent-reach"
$agentReachFallbacks = @(
  (Join-Path $agentReachHome ".venv\Scripts\agent-reach.exe"),
  (Join-Path $agentReachHome ".venv\bin\agent-reach")
)
$agentReachExe = Find-RadarExecutable -ExplicitPath $env:RADAR_AGENT_REACH_EXE -CommandName "agent-reach" -FallbackPaths $agentReachFallbacks
$openCliExe = Find-RadarExecutable -ExplicitPath $env:RADAR_OPENCLI_EXE -CommandName "opencli"
$nodeFallbacks = @()
if ($env:USERPROFILE) { $nodeFallbacks += (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe") }
$nodeExe = Find-RadarExecutable -ExplicitPath $env:RADAR_NODE_EXE -CommandName "node" -FallbackPaths $nodeFallbacks

switch ($Command) {
  "init" {
    if (Test-Path -LiteralPath $ConfigPath) {
      Write-Host "CONFIG_EXISTS $ConfigPath"
      exit 0
    }
    $configDir = Split-Path -Parent $ConfigPath
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot ".env.example") -Destination $ConfigPath
    New-Item -ItemType Directory -Force -Path $DataRoot, $OutputRoot | Out-Null
    Write-Host "CONFIG_READY $ConfigPath"
    Write-Host "DATA_READY $DataRoot"
    Write-Host "OUTPUT_READY $OutputRoot"
  }
  "paths" {
    [ordered]@{
      repo_root = $repoRoot
      config_path = $ConfigPath
      data_root = $DataRoot
      output_root = $OutputRoot
      agent_reach_home = $agentReachHome
      agent_reach_exe = $agentReachExe
      opencli_exe = $openCliExe
      node_exe = $nodeExe
    } | ConvertTo-Json
  }
  "doctor" {
    if (-not $agentReachExe) { throw "Agent Reach not found. Set RADAR_AGENT_REACH_EXE or RADAR_AGENT_REACH_HOME in $ConfigPath" }
    if (-not $openCliExe) { throw "OpenCLI not found. Install it or set RADAR_OPENCLI_EXE in $ConfigPath" }
    & $agentReachExe doctor --json
    & $openCliExe reddit --help | Select-Object -First 5
  }
  "status" {
    Get-Content -Raw -Encoding UTF8 (Join-Path (Split-Path -Parent $PSScriptRoot) "docs\CURRENT_BASELINE.md")
  }
  "verify-baseline" {
    & (Join-Path $PSScriptRoot "verify-baseline.ps1") -DataRoot $DataRoot -OutputRoot $OutputRoot
  }
  "fetch-details" {
    if (-not $EvidenceCsv -or -not $OutputDir) { throw "fetch-details requires -EvidenceCsv and -OutputDir" }
    & (Join-Path $PSScriptRoot "fetch-details.ps1") -EvidenceCsv $EvidenceCsv -OutputDir $OutputDir
  }
  "deep-dive" {
    if (-not $Users -or -not $OutputDir) { throw "deep-dive requires -Users and -OutputDir" }
    & (Join-Path $PSScriptRoot "deep-dive.ps1") -Users $Users -OutputDir $OutputDir
  }
  "report" {
    if (-not $nodeExe) { throw "Node.js not found. Install Node.js or set RADAR_NODE_EXE in $ConfigPath" }
    $env:RADAR_DATA_ROOT = $DataRoot
    $env:RADAR_OUTPUT_ROOT = $OutputRoot
    & $nodeExe (Join-Path $PSScriptRoot "build-evidence-xlsx.mjs")
  }
}
