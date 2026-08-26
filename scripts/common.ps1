function Import-RadarEnv {
  param([string]$ConfigPath)
  if (-not $ConfigPath -or -not (Test-Path -LiteralPath $ConfigPath)) { return }
  foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $ConfigPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
    $parts = $trimmed.Split("=", 2)
    if ($parts.Count -ne 2) { continue }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name -and $value -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

function Resolve-RadarPath {
  param(
    [string]$Value,
    [string]$RepoRoot,
    [string]$DefaultRelative
  )
  if (-not $Value) { $Value = $DefaultRelative }
  $expanded = [Environment]::ExpandEnvironmentVariables($Value)
  if (-not [System.IO.Path]::IsPathRooted($expanded)) { $expanded = Join-Path $RepoRoot $expanded }
  return [System.IO.Path]::GetFullPath($expanded)
}

function Find-RadarExecutable {
  param(
    [string]$ExplicitPath,
    [string]$CommandName,
    [string[]]$FallbackPaths = @(),
    [switch]$PreferFallbacks
  )
  if ($ExplicitPath) {
    $expanded = [Environment]::ExpandEnvironmentVariables($ExplicitPath)
    if (Test-Path -LiteralPath $expanded) { return [System.IO.Path]::GetFullPath($expanded) }
  }
  if ($PreferFallbacks) {
    foreach ($candidate in $FallbackPaths) {
      if ($candidate -and (Test-Path -LiteralPath $candidate)) { return [System.IO.Path]::GetFullPath($candidate) }
    }
  }
  $command = Get-Command $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($command) { return $command.Source }
  if (-not $PreferFallbacks) {
    foreach ($candidate in $FallbackPaths) {
      if ($candidate -and (Test-Path -LiteralPath $candidate)) { return [System.IO.Path]::GetFullPath($candidate) }
    }
  }
  return $null
}
