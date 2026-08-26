param(
  [string]$DataRoot = "D:\zuop\agent-reach\data\processed-20260826",
  [string]$OutputRoot = "D:\zuop\agent-reach\outputs\20260826"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredRepoFiles = @(
  "README.md",
  ".gitignore",
  ".env.example",
  "configs\diesel_90d.yaml",
  "schemas\analysis.schema.json",
  "schemas\user_profile.schema.json",
  "docs\CURRENT_BASELINE.md",
  "docs\DATA_CONTRACT.md",
  "scripts\radar.ps1",
  "scripts\fetch-details.ps1",
  "scripts\deep-dive.ps1",
  "scripts\build-evidence-xlsx.mjs",
  "scripts\setup-local-runtime.ps1"
)
$missing = @()
foreach ($relative in $requiredRepoFiles) {
  if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relative))) { $missing += $relative }
}
if ($missing.Count -gt 0) { throw "Missing repository files: $($missing -join ', ')" }

Get-Content -Raw (Join-Path $repoRoot "schemas\analysis.schema.json") | ConvertFrom-Json | Out-Null
Get-Content -Raw (Join-Path $repoRoot "schemas\user_profile.schema.json") | ConvertFrom-Json | Out-Null

$requiredBaseline = @(
  (Join-Path $DataRoot "evidence_candidates.csv"),
  (Join-Path $DataRoot "details_all"),
  (Join-Path $OutputRoot "evidence_candidates_中文.xlsx"),
  (Join-Path $OutputRoot "user_deep_dive_test_report.md")
)
foreach ($path in $requiredBaseline) {
  if (-not (Test-Path -LiteralPath $path)) { throw "Missing local baseline artifact: $path" }
}

$candidateCount = (Import-Csv -LiteralPath (Join-Path $DataRoot "evidence_candidates.csv")).Count
$detailCount = (Get-ChildItem -LiteralPath (Join-Path $DataRoot "details_all") -Filter "*.json" -File).Count
if ($candidateCount -ne 41) { throw "Expected 41 candidate rows, found $candidateCount" }
if ($detailCount -ne 41) { throw "Expected 41 detail files, found $detailCount" }

$trackedText = Get-ChildItem -LiteralPath $repoRoot -Recurse -File | Where-Object { $_.FullName -notmatch '\\.git\\|\\node_modules\\' -and $_.Name -ne "verify-baseline.ps1" } | ForEach-Object { Get-Content -Raw -ErrorAction SilentlyContinue $_.FullName }
$secretPatterns = 'reddit_session=|api[_-]?key\s*=\s*["''][A-Za-z0-9_-]{16,}|client_secret\s*=\s*["''][^"'']+'
if (($trackedText -join "`n") -match $secretPatterns) { throw "Potential credential material detected in repository files" }

Write-Host "BASELINE_OK candidates=$candidateCount details=$detailCount"
