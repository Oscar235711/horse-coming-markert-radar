param(
  [ValidateRange(1,365)][int]$WindowDays = 90,
  [ValidateSet('quick','standard','deep','complete')][string]$Depth = 'standard',
  [string]$Communities = 'Cummins,Duramax,powerstroke,FordDiesels'
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$today = Get-Date
$end = $today.ToString('yyyy-MM-dd')
$start = $today.AddDays(-$WindowDays + 1).ToString('yyyy-MM-dd')
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
Push-Location $repoRoot
try {
  & $python -m opportunity_radar run --config (Join-Path $repoRoot 'configs\diesel_90d.yaml') --start-date $start --end-date $end --depth $Depth --analysis-engine codex --communities $Communities
  exit $LASTEXITCODE
} finally { Pop-Location }
