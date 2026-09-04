param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

Push-Location $repoRoot
try {
  & $python -m pytest -q
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  & node --test .\opencli-plugin\opportunity-reddit\*.test.mjs
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  & $python -m pytest tests\test_release_contract.py -q
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
