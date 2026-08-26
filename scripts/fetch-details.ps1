param(
  [Parameter(Mandatory = $true)][string]$EvidenceCsv,
  [Parameter(Mandatory = $true)][string]$OutputDir,
  [int]$IntervalSeconds = 3
)

$ErrorActionPreference = "Continue"
if (-not (Test-Path -LiteralPath $EvidenceCsv)) { throw "Evidence CSV not found: $EvidenceCsv" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$rows = Import-Csv -LiteralPath $EvidenceCsv
$total = $rows.Count
$ok = 0
$failed = 0
$i = 0

foreach ($row in $rows) {
  $i++
  $id = $row.EvidenceId
  $url = $row.Url
  $match = [regex]::Match($url, '/comments/([^/]+)')
  if (-not $match.Success) {
    Write-Host "[$i/$total] $id SKIP invalid URL"
    $failed++
    continue
  }
  $postId = $match.Groups[1].Value
  $outFile = Join-Path $OutputDir ("{0}__{1}.json" -f $id, $postId)
  if (Test-Path -LiteralPath $outFile) {
    Write-Host "[$i/$total] $id EXISTS"
    $ok++
    continue
  }
  Write-Host "[$i/$total] $id FETCH"
  try {
    $result = & opencli reddit read $postId -f json --window foreground --site-session persistent --limit 100 --depth 3 --replies 20 --expand-more true --expand-rounds 5 --max-length 5000 2>&1
    $text = ($result -join "`n")
    if ($text.TrimStart().StartsWith("[") -and $text.TrimEnd().EndsWith("]")) {
      [System.IO.File]::WriteAllText($outFile, $text, [System.Text.UTF8Encoding]::new($false))
      $ok++
    } else {
      $errorFile = Join-Path $OutputDir ("{0}__{1}.error.txt" -f $id, $postId)
      [System.IO.File]::WriteAllText($errorFile, $text, [System.Text.UTF8Encoding]::new($false))
      $failed++
    }
  } catch {
    $errorFile = Join-Path $OutputDir ("{0}__{1}.error.txt" -f $id, $postId)
    [System.IO.File]::WriteAllText($errorFile, $_.Exception.ToString(), [System.Text.UTF8Encoding]::new($false))
    $failed++
  }
  Start-Sleep -Seconds $IntervalSeconds
}

Write-Host "DETAIL_FETCH_SUMMARY total=$total ok=$ok failed=$failed"
if ($failed -gt 0) { exit 2 }
