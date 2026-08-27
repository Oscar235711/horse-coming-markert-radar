param(
  [Parameter(Position = 0, Mandatory = $true)]
  [ValidateSet("init", "paths", "doctor", "status", "verify-baseline", "fetch-details", "deep-dive", "report", "run", "resume", "export", "communities-suggest", "communities-approve")]
  [string]$Command,
  [string]$EvidenceCsv,
  [string]$OutputDir,
  [string]$Users,
  [string]$DataRoot,
  [string]$OutputRoot,
  [string]$ConfigPath,
  [string]$RunConfigPath,
  [string]$RunId,
  [string]$Formats,
  [string]$Suggestion,
  [string]$SuggestionId
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot ".env" }
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$radarConfig = Import-RadarEnv -ConfigPath $ConfigPath

$DataRoot = Resolve-RadarPath -Value $(if ($DataRoot) { $DataRoot } else { Get-RadarSetting -Name "RADAR_DATA_ROOT" -Config $radarConfig }) -RepoRoot $repoRoot -DefaultRelative ".local\data"
$OutputRoot = Resolve-RadarPath -Value $(if ($OutputRoot) { $OutputRoot } else { Get-RadarSetting -Name "RADAR_OUTPUT_ROOT" -Config $radarConfig }) -RepoRoot $repoRoot -DefaultRelative ".local\outputs"
$toolsRoot = Resolve-RadarPath -Value (Get-RadarSetting -Name "RADAR_TOOLS_ROOT" -Config $radarConfig) -RepoRoot $repoRoot -DefaultRelative ".tools"
$agentReachHome = Resolve-RadarPath -Value (Get-RadarSetting -Name "RADAR_AGENT_REACH_HOME" -Config $radarConfig) -RepoRoot $repoRoot -DefaultRelative ".local\agent-reach"
$agentReachFallbacks = @(
  (Join-Path $toolsRoot "agent-reach\.venv\Scripts\agent-reach.exe"),
  (Join-Path $toolsRoot "agent-reach\.venv\bin\agent-reach"),
  (Join-Path $agentReachHome ".venv\Scripts\agent-reach.exe"),
  (Join-Path $agentReachHome ".venv\bin\agent-reach")
)
$agentReachExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_AGENT_REACH_EXE" -Config $radarConfig) -CommandName "agent-reach" -FallbackPaths $agentReachFallbacks -PreferFallbacks
$openCliFallbacks = @(
  (Join-Path $toolsRoot "opencli\node_modules\.bin\opencli.cmd"),
  (Join-Path $toolsRoot "opencli\node_modules\.bin\opencli")
)
$openCliExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_OPENCLI_EXE" -Config $radarConfig) -CommandName "opencli" -FallbackPaths $openCliFallbacks -PreferFallbacks
$nodeFallbacks = @()
if ($env:USERPROFILE) { $nodeFallbacks += (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe") }
$nodeExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_NODE_EXE" -Config $radarConfig) -CommandName "node" -FallbackPaths $nodeFallbacks
$pythonFallbacks = @(
  (Join-Path $repoRoot ".venv\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python")
)
$pythonExe = Find-RadarExecutable -ExplicitPath (Get-RadarSetting -Name "RADAR_PYTHON_EXE" -Config $radarConfig) -CommandName "python" -FallbackPaths $pythonFallbacks

function Invoke-RadarPythonCli {
  param([string[]]$Arguments)
  if (-not $pythonExe) { throw "Python not found. Install Python 3.12+ or set RADAR_PYTHON_EXE in $ConfigPath" }
  $propagatedNames = @()
  if ($radarConfig) {
    $propagatedNames += $radarConfig.Keys | Where-Object { $_ -match '^(RADAR_|DEEPSEEK_)' }
  }
  $propagatedNames += "RADAR_DATA_ROOT", "RADAR_OUTPUT_ROOT", "RADAR_TOOLS_ROOT", "RADAR_AGENT_REACH_HOME", "RADAR_AGENT_REACH_EXE", "RADAR_OPENCLI_EXE", "RADAR_NODE_EXE", "RADAR_PYTHON_EXE"
  $propagatedNames = $propagatedNames | Sort-Object -Unique

  $previousValues = @{}
  try {
    foreach ($name in $propagatedNames) {
      $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
      $value = Get-RadarSetting -Name $name -Config $radarConfig
      if ($null -ne $value -and $value -ne "") {
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
      }
    }
    & $pythonExe "-m" "opportunity_radar" @Arguments
  }
  finally {
    foreach ($name in $propagatedNames) {
      [Environment]::SetEnvironmentVariable($name, $previousValues[$name], "Process")
    }
  }
}

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
      tools_root = $toolsRoot
      agent_reach_home = $agentReachHome
      agent_reach_exe = $agentReachExe
      opencli_exe = $openCliExe
      node_exe = $nodeExe
    } | ConvertTo-Json
  }
  "doctor" {
    Invoke-RadarPythonCli -Arguments @("doctor")
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
    $previousDataRoot = $env:RADAR_DATA_ROOT
    $previousOutputRoot = $env:RADAR_OUTPUT_ROOT
    try {
      $env:RADAR_DATA_ROOT = $DataRoot
      $env:RADAR_OUTPUT_ROOT = $OutputRoot
      & $nodeExe (Join-Path $PSScriptRoot "build-evidence-xlsx.mjs")
    }
    finally {
      $env:RADAR_DATA_ROOT = $previousDataRoot
      $env:RADAR_OUTPUT_ROOT = $previousOutputRoot
    }
  }
  "run" {
    if (-not $RunConfigPath) { throw "run requires -RunConfigPath" }
    $arguments = @("run", "--config", $RunConfigPath)
    if ($RunId) { $arguments += @("--run-id", $RunId) }
    Invoke-RadarPythonCli -Arguments $arguments
  }
  "resume" {
    if (-not $RunId) { throw "resume requires -RunId" }
    Invoke-RadarPythonCli -Arguments @("resume", "--run-id", $RunId)
  }
  "export" {
    if (-not $RunId) { throw "export requires -RunId" }
    $arguments = @("export", "--run-id", $RunId)
    if ($Formats) { $arguments += @("--formats", $Formats) }
    Invoke-RadarPythonCli -Arguments $arguments
  }
  "communities-suggest" {
    if (-not $RunId) { throw "communities-suggest requires -RunId" }
    Invoke-RadarPythonCli -Arguments @("communities", "suggest", "--run-id", $RunId)
  }
  "communities-approve" {
    if (-not $Suggestion -or -not $SuggestionId) { throw "communities-approve requires -Suggestion and -SuggestionId" }
    Invoke-RadarPythonCli -Arguments @("communities", "approve", "--suggestion", $Suggestion, "--suggestion-id", $SuggestionId)
  }
}
