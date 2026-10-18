# Wait until both recent-news jobs have finished, then build the features and
# run the pre-registered walk-forward evaluation once (DECISIONS 50-51).
# Started detached by scripts\catalyst_start.ps1; output in outputs\news_v1\evaluate.log.
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$out = "outputs\news_v1"
function Finished($file) {
    if (-not (Test-Path $file)) { return $false }
    return ((Get-Content $file -Raw | ConvertFrom-Json).phase -eq "finished")
}
while (-not ((Finished "$out\state.json") -and (Finished "$out\tone_state.json"))) { Start-Sleep -Seconds 300 }
if (Test-Path "outputs\p6_sec_features\news_walk_forward.json") { exit 0 }
& .venv\Scripts\python.exe -m structural_break.experiments.news_coverage features --workspace-root data\team --output $out *>> "$out\evaluate.log"
& .venv\Scripts\python.exe -m structural_break.experiments.p6_sec_features evaluate --workspace-root data\team `
    --features "$out\news_features.parquet" --features "$out\tone_features.parquet" `
    --features "outputs\p6_sec_features\timing_features.parquet" `
    --simulation "outputs\p6_improvement\walkforward\simulation_frozen_exit.parquet" `
    --output "outputs\p6_sec_features\news_walk_forward.json" *>> "$out\evaluate.log"