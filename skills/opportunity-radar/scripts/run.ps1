param(
  [switch]$Doctor,
  [switch]$Resume,
  [string]$RunId,
  [string]$StartDate,
  [string]$EndDate,
  [ValidateSet('quick','standard','deep','complete')]
  [string]$Depth = 'standard',
  [string]$Communities = 'Cummins,Duramax,powerstroke,FordDiesels',
  [string]$Keywords = '',
  [switch]$NoOpen
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
if ($Doctor) { & $python -m opportunity_radar doctor; exit $LASTEXITCODE }
if ($Resume) {
  if (-not $RunId) { throw 'Resume requires -RunId.' }
  & $python -m opportunity_radar resume --run-id $RunId
  exit $LASTEXITCODE
}
if (-not $StartDate -or -not $EndDate) { throw 'Run requires -StartDate and -EndDate.' }
$cliArgs = @('-m','opportunity_radar','run','--config',(Join-Path $repoRoot 'configs\diesel_90d.yaml'),'--start-date',$StartDate,'--end-date',$EndDate,'--depth',$Depth,'--analysis-engine','codex','--communities',$Communities)
if ($RunId) { $cliArgs += @('--run-id',$RunId) }
if ($Keywords) { $cliArgs += @('--keywords',$Keywords) }
Push-Location $repoRoot
try { & $python @cliArgs; exit $LASTEXITCODE } finally { Pop-Location }
