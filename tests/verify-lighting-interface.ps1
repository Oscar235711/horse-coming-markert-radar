$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$radar = Join-Path $repoRoot "scripts\radar.ps1"
$pathsText = ((& $radar paths) -join "`n")
$paths = $pathsText | ConvertFrom-Json
if (-not $paths.runs_root) { throw "paths must expose runs_root" }
$help = ((& node (Join-Path $repoRoot "scripts\run-radar.mjs") --help) -join "`n")
if ($help -notmatch "automotive_lighting_us_pilot.json") { throw "lighting CLI help is missing the default config" }
if ($help -notmatch "--profile <overnight>") { throw "lighting CLI help must document the overnight profile" }
if ($help -notmatch "--max-runtime-minutes <minutes>") { throw "lighting CLI help must document the runtime ceiling" }
if ($help -notmatch "--llm-model <model>") { throw "lighting CLI help must document the LLM model override" }
$radarText = Get-Content -Raw -Encoding UTF8 $radar
if ($radarText -notmatch '"run"') { throw "radar.ps1 must expose the run command" }
if (-not (Test-Path (Join-Path $repoRoot "configs\automotive_lighting_us_overnight_v1.2.json"))) { throw "overnight config is missing" }
if (-not (Test-Path (Join-Path $repoRoot ".agents\HERMES_HANDOFF_V1.2.md"))) { throw "Hermes handoff is missing" }
if (-not (Test-Path (Join-Path $repoRoot ".agents\PROGRESS.md"))) { throw "Hermes progress template is missing" }
if (-not (Test-Path (Join-Path $repoRoot ".agents\OUTBOX.md"))) { throw "Hermes outbox template is missing" }
Write-Host "LIGHTING_INTERFACE_OK"
