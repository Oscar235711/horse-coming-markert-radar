param(
  [Parameter(Mandatory = $true)][string]$Users,
  [Parameter(Mandatory = $true)][string]$OutputDir,
  [int]$PostLimit = 30,
  [int]$CommentLimit = 50,
  [int]$IntervalSeconds = 3
)

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$userList = @($Users.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$relevantSubs = '(?i)duramax|cummins|powerstroke|forddiesels|superduty|diesel|truck|mechanic|towing|automotive|oilandgas'
$relevantText = '(?i)diesel|duramax|cummins|powerstroke|truck|f250|f350|ram 2500|ram 3500|silverado|sierra|towing|trailer|egr|dpf|def|turbo|tuner|tuning|ecm|transmission|injector|downpipe|exhaust|pcv|ccv'
$summary = @()

foreach ($user in $userList) {
  Write-Host "FETCH $user public history"
  $postsText = ((& opencli reddit user-posts $user --limit $PostLimit -f json --window foreground --site-session persistent) -join "`n")
  $commentsText = ((& opencli reddit user-comments $user --limit $CommentLimit -f json --window foreground --site-session persistent) -join "`n")
  $posts = if ($postsText.Trim().StartsWith('[')) { @($postsText | ConvertFrom-Json) } else { @() }
  $comments = if ($commentsText.Trim().StartsWith('[')) { @($commentsText | ConvertFrom-Json) } else { @() }
  $filteredPosts = @($posts | Where-Object { $_.subreddit -match $relevantSubs -or $_.title -match $relevantText })
  $filteredComments = @($comments | Where-Object { $_.subreddit -match $relevantSubs -or $_.body -match $relevantText })
  $result = [ordered]@{
    username = $user
    collected_posts = $posts.Count
    collected_comments = $comments.Count
    relevant_posts = $filteredPosts
    relevant_comments = $filteredComments
    excluded_unrelated_count = ($posts.Count + $comments.Count - $filteredPosts.Count - $filteredComments.Count)
    privacy_note = "Only public, research-relevant vehicle and usage content is retained."
  }
  [System.IO.File]::WriteAllText((Join-Path $OutputDir "$user.json"), ($result | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
  $summary += [pscustomobject]@{
    username = $user
    posts_collected = $posts.Count
    comments_collected = $comments.Count
    relevant_posts = $filteredPosts.Count
    relevant_comments = $filteredComments.Count
    usable = (($filteredPosts.Count + $filteredComments.Count) -ge 3)
  }
  Start-Sleep -Seconds $IntervalSeconds
}

[System.IO.File]::WriteAllText((Join-Path $OutputDir "summary.json"), ($summary | ConvertTo-Json -Depth 4), [System.Text.UTF8Encoding]::new($false))
$summary | Format-Table -AutoSize
