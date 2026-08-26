$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceModules = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
if (-not (Test-Path -LiteralPath (Join-Path $sourceModules "@oai\artifact-tool\package.json"))) {
  throw "Test prerequisite missing: bundled artifact-tool"
}
$testRoot = Join-Path $repoRoot (".local\runtime-test-" + [guid]::NewGuid().ToString("N"))
$configPath = Join-Path $testRoot ".env"
$junctionPath = Join-Path $testRoot "node_modules"

try {
  New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
  [System.IO.File]::WriteAllText($configPath, "RADAR_NODE_MODULES=$sourceModules", [System.Text.UTF8Encoding]::new($false))
  & (Join-Path $repoRoot "scripts\setup-local-runtime.ps1") -ConfigPath $configPath -JunctionPath $junctionPath
  if (-not (Test-Path -LiteralPath (Join-Path $junctionPath "@oai\artifact-tool\package.json"))) {
    throw "runtime setup did not expose artifact-tool at the requested junction"
  }
  Write-Host "PORTABLE_RUNTIME_OK"
}
finally {
  $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
  $resolvedLocalRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".local"))
  if ($resolvedTestRoot.StartsWith($resolvedLocalRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTestRoot)) {
    Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
  }
}
