$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $repoRoot (".local\tools-test-" + [guid]::NewGuid().ToString("N"))
$toolsRoot = Join-Path $testRoot ".tools"
$agentExe = Join-Path $toolsRoot "agent-reach\.venv\Scripts\agent-reach.exe"
$openCliExe = Join-Path $toolsRoot "opencli\node_modules\.bin\opencli.cmd"
$previousToolsRoot = $env:RADAR_TOOLS_ROOT
$previousAgentExe = $env:RADAR_AGENT_REACH_EXE
$previousOpenCliExe = $env:RADAR_OPENCLI_EXE

try {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $agentExe), (Split-Path -Parent $openCliExe) | Out-Null
  New-Item -ItemType File -Force -Path $agentExe, $openCliExe | Out-Null
  $env:RADAR_TOOLS_ROOT = $toolsRoot
  $env:RADAR_AGENT_REACH_EXE = $null
  $env:RADAR_OPENCLI_EXE = $null

  $paths = (& (Join-Path $repoRoot "scripts\radar.ps1") paths -ConfigPath (Join-Path $testRoot "missing.env")) | ConvertFrom-Json
  if ($paths.agent_reach_exe -ne $agentExe) { throw "project-local Agent Reach was not discovered" }
  if ($paths.opencli_exe -ne $openCliExe) { throw "project-local OpenCLI was not discovered" }

  $plan = ((& (Join-Path $repoRoot "scripts\install-tools.ps1") -ToolsRoot $toolsRoot -DryRun 6>&1) | Out-String)
  if ($plan -notmatch "Agent-Reach/archive/06c202b03400a7d31886bf4399213706da1a0324.zip") { throw "Agent Reach install source is not pinned" }
  if ($plan -notmatch "@jackwener/opencli@1.8.7") { throw "OpenCLI install version is not pinned" }

  Write-Host "PROJECT_TOOLS_OK"
}
finally {
  $env:RADAR_TOOLS_ROOT = $previousToolsRoot
  $env:RADAR_AGENT_REACH_EXE = $previousAgentExe
  $env:RADAR_OPENCLI_EXE = $previousOpenCliExe
  $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
  $resolvedLocalRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".local"))
  if ($resolvedTestRoot.StartsWith($resolvedLocalRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTestRoot)) {
    Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
  }
}
