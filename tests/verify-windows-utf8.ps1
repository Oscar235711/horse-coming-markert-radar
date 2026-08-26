$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$text = & (Join-Path $repoRoot "scripts\radar.ps1") status
$joined = $text -join [Environment]::NewLine
$expected = Get-Content -Raw -Encoding UTF8 (Join-Path $repoRoot "docs\CURRENT_BASELINE.md")
if ($joined.TrimEnd() -ne $expected.TrimEnd()) {
  throw "UTF-8 status verification failed"
}
Write-Host "WINDOWS_POWERSHELL_UTF8_OK"
