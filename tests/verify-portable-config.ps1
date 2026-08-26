$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $repoRoot (".local\portability-test-" + [guid]::NewGuid().ToString("N"))
$configPath = Join-Path $testRoot ".env"

try {
  $initOutput = & (Join-Path $repoRoot "scripts\radar.ps1") init -ConfigPath $configPath
  if (-not (Test-Path -LiteralPath $configPath)) { throw "init did not create the requested config file" }

  $paths = (& (Join-Path $repoRoot "scripts\radar.ps1") paths -ConfigPath $configPath) | ConvertFrom-Json
  $expectedData = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".local\data"))
  $expectedOutput = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".local\outputs"))
  if ($paths.data_root -ne $expectedData) { throw "relative data path was not resolved from the repository root" }
  if ($paths.output_root -ne $expectedOutput) { throw "relative output path was not resolved from the repository root" }

  [System.IO.File]::WriteAllText($configPath, "RADAR_DATA_ROOT=do-not-overwrite", [System.Text.UTF8Encoding]::new($false))
  & (Join-Path $repoRoot "scripts\radar.ps1") init -ConfigPath $configPath | Out-Null
  if ((Get-Content -Raw -Encoding UTF8 $configPath) -ne "RADAR_DATA_ROOT=do-not-overwrite") {
    throw "init overwrote an existing local config"
  }

  Write-Host "PORTABLE_CONFIG_OK"
}
finally {
  $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
  $resolvedLocalRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".local"))
  if ($resolvedTestRoot.StartsWith($resolvedLocalRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTestRoot)) {
    Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
  }
}
