# Wait for the 8-K headline scoring to finish, then build the headline table and
# run stage 1 of the Decision 59 exploration once. Log: outputs\p6_sec_explore2\explore.log
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$v2 = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance"
$sec = "$v2\data\research_v2\sec_metadata\source_v3"
while (-not (Test-Path "outputs\headline_v1\score_done")) { Start-Sleep -Seconds 300 }
if (Test-Path "outputs\p6_sec_explore2\choices.json") { exit 0 }
New-Item -ItemType Directory -Force outputs\p6_sec_explore2 | Out-Null
& .venv\Scripts\python.exe -m structural_break.experiments.headline_coverage table --sec-metadata $sec --output outputs\headline_v1 *>> outputs\p6_sec_explore2\explore.log
$env:OMP_NUM_THREADS = "1"
& .venv\Scripts\python.exe -m structural_break.experiments.p6_sec_explore2 explore --workspace-root data\team `
    --features outputs\p6_sec_features\timing_features.parquet --features outputs\news_v1\news_features.parquet `
    --features outputs\news_v1\tone_features.parquet `
    --simulation outputs\p6_improvement\walkforward\simulation_frozen_exit.parquet `
    --headlines outputs\headline_v1\headline_tone.parquet --sec-metadata $sec `
    --output-dir outputs\p6_sec_explore2 *>> outputs\p6_sec_explore2\explore.log