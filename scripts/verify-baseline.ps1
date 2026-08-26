param(
  [string]$DataRoot,
  [string]$OutputRoot,
  [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot ".env" }
$radarConfig = Import-RadarEnv -ConfigPath $ConfigPath
$DataRoot = Resolve-RadarPath -Value $(if ($DataRoot) { $DataRoot } else { Get-RadarSetting -Name "RADAR_DATA_ROOT" -Config $radarConfig }) -RepoRoot $repoRoot -DefaultRelative ".local\data"
$OutputRoot = Resolve-RadarPath -Value $(if ($OutputRoot) { $OutputRoot } else { Get-RadarSetting -Name "RADAR_OUTPUT_ROOT" -Config $radarConfig }) -RepoRoot $repoRoot -DefaultRelative ".local\outputs"
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
  "scripts\common.ps1",
  "scripts\install-tools.ps1",
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

Get-Content -Raw -Encoding UTF8 (Join-Path $repoRoot "schemas\analysis.schema.json") | ConvertFrom-Json | Out-Null
Get-Content -Raw -Encoding UTF8 (Join-Path $repoRoot "schemas\user_profile.schema.json") | ConvertFrom-Json | Out-Null

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

$trackedFiles = @(& git -C $repoRoot ls-files)
if ($LASTEXITCODE -ne 0) { throw "Unable to list Git-tracked files for credential scan" }
$trackedText = $trackedFiles | Where-Object { $_ -ne "scripts/verify-baseline.ps1" } | ForEach-Object {
  $trackedPath = Join-Path $repoRoot $_
  if (Test-Path -LiteralPath $trackedPath) { Get-Content -Raw -Encoding UTF8 -ErrorAction SilentlyContinue $trackedPath }
}
$secretPatterns = 'reddit_session=|api[_-]?key\s*=\s*["''][A-Za-z0-9_-]{16,}|client_secret\s*=\s*["''][^"'']+'
if (($trackedText -join "`n") -match $secretPatterns) { throw "Potential credential material detected in repository files" }

Write-Host "BASELINE_OK candidates=$candidateCount details=$detailCount"
