param(
  [Parameter(Mandatory=$true)][string]$TaskName,
  [ValidateSet('DAILY','WEEKLY','MONTHLY')][string]$Frequency = 'WEEKLY',
  [Parameter(Mandatory=$true)][ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$StartTime,
  [ValidateRange(1,365)][int]$WindowDays = 90,
  [ValidateSet('quick','standard','deep','complete')][string]$Depth = 'standard',
  [string]$Communities = 'Cummins,Duramax,powerstroke,FordDiesels'
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$runner = Join-Path $repoRoot 'scripts\scheduled-run.ps1'
if (-not (Test-Path -LiteralPath $runner)) {
  throw "Missing scheduled runner: $runner"
}
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -WindowDays $WindowDays -Depth $Depth -Communities `"$Communities`""
& schtasks.exe /Create /F /TN $TaskName /SC $Frequency /ST $StartTime /TR "powershell.exe $taskArgs"
if ($LASTEXITCODE -ne 0) { throw "schtasks failed with exit code $LASTEXITCODE" }
Write-Output "已创建定时任务：$TaskName ($Frequency $StartTime)"
