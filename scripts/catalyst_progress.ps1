# Show progress of the recent-news jobs (DECISIONS 50-51) and the evaluation watcher.
# Usage:  powershell -File scripts\catalyst_progress.ps1
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$python = Get-CimInstance Win32_Process -Filter "name='python.exe'"
$shells = Get-CimInstance Win32_Process -Filter "name='powershell.exe'"
foreach ($job in @(@('Gemma news', '*news_coverage run*'), @('FinBERT tone', '*news_coverage tone*'))) {
    $found = $python | Where-Object { $_.CommandLine -like $job[1] }
    if ($found) { Write-Output "$($job[0]) process: running ($($found[0].ProcessId))" }
    else { Write-Output "$($job[0]) process: not running (finished, or restart with scripts\catalyst_start.ps1)" }
}
Write-Output ""
& .venv\Scripts\python.exe -m structural_break.experiments.news_coverage status --output outputs\news_v1
Write-Output ""
& .venv\Scripts\python.exe -m structural_break.experiments.news_coverage tone-status --output outputs\news_v1
Write-Output ""
if (Test-Path outputs\p6_sec_features\news_walk_forward.json) {
    Write-Output "Evaluation: finished (outputs\p6_sec_features\news_walk_forward.json)"
} elseif ($shells | Where-Object { $_.CommandLine -like '*catalyst_evaluate_when_done*' }) {
    Write-Output "Evaluation: watcher waiting for both jobs to finish"
} else {
    Write-Output "Evaluation: watcher not running (restart with scripts\catalyst_start.ps1)"
}Write-Output ""
$v2 = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance"
& .venv\Scripts\python.exe -m structural_break.experiments.headline_coverage status --sec-metadata "$v2\data\research_v2\sec_metadata\source_v3" --output outputs\headline_v1
if (Test-Path outputs\p6_sec_explore2\choices.json) { Write-Output "Round 2 exploration: stage 1 finished (choices.json written)" }
elseif ($shells | Where-Object { $_.CommandLine -like '*explore2_when_ready*' }) { Write-Output "Round 2 exploration: waiting for headline scoring" }
else { Write-Output "Round 2 exploration: not running" }