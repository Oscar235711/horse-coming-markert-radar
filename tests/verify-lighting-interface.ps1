$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$radar = Join-Path $repoRoot "scripts\radar.ps1"
$pathsText = ((& $radar paths) -join "`n")
$paths = $pathsText | ConvertFrom-Json
if (-not $paths.runs_root) { throw "paths must expose runs_root" }
$help = ((& node (Join-Path $repoRoot "scripts\run-radar.mjs") --help) -join "`n")
if ($help -notmatch "automotive_lighting_us_pilot.json") { throw "lighting CLI help is missing the default config" }
$radarText = Get-Content -Raw -Encoding UTF8 $radar
if ($radarText -notmatch '"run"') { throw "radar.ps1 must expose the run command" }
Write-Host "LIGHTING_INTERFACE_OK"
