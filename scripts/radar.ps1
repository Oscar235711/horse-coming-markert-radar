param(
  [Parameter(Position = 0, Mandatory = $true)]
  [ValidateSet("doctor", "status", "verify-baseline", "fetch-details", "deep-dive", "report")]
  [string]$Command,
  [string]$EvidenceCsv,
  [string]$OutputDir,
  [string]$Users,
  [string]$DataRoot = "D:\zuop\agent-reach\data\processed-20260826",
  [string]$OutputRoot = "D:\zuop\agent-reach\outputs\20260826"
)

$ErrorActionPreference = "Stop"
switch ($Command) {
  "doctor" {
    $doctor = "D:\zuop\agent-reach\.venv\Scripts\agent-reach.exe"
    if (-not (Test-Path -LiteralPath $doctor)) { throw "Agent Reach executable not found: $doctor" }
    & $doctor doctor --json
    opencli reddit --help | Select-Object -First 5
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
    $node = $env:RADAR_NODE_EXE
    if (-not $node) { $node = "C:\Users\yaobi\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" }
    if (-not (Test-Path -LiteralPath $node)) { throw "Node executable not found; set RADAR_NODE_EXE" }
    $env:RADAR_DATA_ROOT = $DataRoot
    $env:RADAR_OUTPUT_ROOT = $OutputRoot
    & $node (Join-Path $PSScriptRoot "build-evidence-xlsx.mjs")
  }
}
