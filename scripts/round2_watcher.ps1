# Round 2 (DECISIONS 59) end to end, unattended:
#   1. wait for 8-K headline scoring, build the headline table
#   2. stage 1 (explore 2006-2015) -> choices.json
#   3. record the choices as DECISIONS 59a, commit and push (before stage 2)
#   4. stage 2 (confirm 2016-2021, once)
#   5. record the results as DECISIONS 60, commit and push
# Safe to restart: finished steps are skipped. Log: outputs\p6_sec_explore2\watcher.log
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$v2 = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance"
$sec = "$v2\data\research_v2\sec_metadata\source_v3"
$out = "outputs\p6_sec_explore2"
New-Item -ItemType Directory -Force $out | Out-Null
$log = "$out\watcher.log"
function Say($message) { "$((Get-Date).ToUniversalTime().ToString('s'))Z $message" | Out-File -Append -Encoding utf8 $log }
$py = ".venv\Scripts\python.exe"
$common = @("--workspace-root", "data\team",
    "--features", "outputs\p6_sec_features\timing_features.parquet",
    "--features", "outputs\news_v1\news_features.parquet",
    "--features", "outputs\news_v1\tone_features.parquet",
    "--simulation", "outputs\p6_improvement\walkforward\simulation_frozen_exit.parquet",
    "--headlines", "outputs\headline_v1\headline_tone.parquet",
    "--sec-metadata", $sec, "--output-dir", $out)
$env:OMP_NUM_THREADS = "1"
Say "watcher started"
while (-not (Test-Path "outputs\headline_v1\score_done")) { Start-Sleep -Seconds 300 }
if (-not (Test-Path "outputs\headline_v1\headline_tone.parquet")) {
    Say "building headline table"
    & $py -m structural_break.experiments.headline_coverage table --sec-metadata $sec --output outputs\headline_v1 *>> $log
}
if (-not (Test-Path "$out\choices.json")) {
    Say "stage 1: explore"
    & $py -m structural_break.experiments.p6_sec_explore2 explore @common *>> $log
    if (-not (Test-Path "$out\choices.json")) { Say "ERROR: stage 1 produced no choices"; exit 1 }
}
& $py -m structural_break.experiments.p6_sec_explore2 record-choices @common *>> $log
git add docs/DECISIONS.md *>> $log
git -c core.safecrlf=false commit -q -m "Record the round-2 exploration choices before confirmation (Decision 59a)`n`nRecorded automatically by scripts/round2_watcher.ps1 after stage 1.`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" *>> $log
git push -q origin p6/sec-timing-catalysts *>> $log
Say "choices committed: $(git log --oneline -1)"
if (-not (Test-Path "$out\confirmation.json")) {
    Say "stage 2: confirm"
    & $py -m structural_break.experiments.p6_sec_explore2 confirm @common *>> $log
    if (-not (Test-Path "$out\confirmation.json")) { Say "ERROR: stage 2 produced no confirmation"; exit 1 }
}
& $py -m structural_break.experiments.p6_sec_explore2 record-results @common *>> $log
git add docs/DECISIONS.md *>> $log
git -c core.safecrlf=false commit -q -m "Record the round-2 confirmation result (Decision 60)`n`nRecorded automatically by scripts/round2_watcher.ps1 after stage 2.`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" *>> $log
git push -q origin p6/sec-timing-catalysts *>> $log
Say "results committed: $(git log --oneline -1)"
"done" | Out-File -Encoding utf8 "$out\DONE"
Say "round 2 finished"