# Start or resume the recent-news jobs (DECISIONS 50-51) as detached background
# processes: Gemma news labels and local FinBERT tone. Safe to rerun: finished
# packs are skipped and a running job is left alone.
# Usage:  powershell -File scripts\catalyst_start.ps1 [-EnvFile PATH]
param(
    [string]$EnvFile = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance\.env",
    [string]$V2Project = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance",
    [string]$Output = "outputs\news_v1"
)
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$V2 = "$V2Project\data\research_v2"
$jobs = Get-CimInstance Win32_Process -Filter "name='python.exe'"
if (-not (Test-Path "$Output\queue.parquet")) {
    & .venv\Scripts\python.exe -m structural_break.experiments.news_coverage build --workspace-root data\team `
        --sec-metadata "$V2\sec_metadata\source_v3" --sec-cache "$V2\cache" --output $Output
}
if ($jobs | Where-Object { $_.CommandLine -like '*news_coverage run*' }) {
    Write-Output "Gemma news job already running."
} else {
    $command = "`".venv\Scripts\python.exe`" -m structural_break.experiments.news_coverage run " +
        "--output `"$Output`" --env-file `"$EnvFile`" >> `"$Output\run.log`" 2>&1"
    Start-Process -FilePath cmd.exe -ArgumentList "/c `"$command`"" -WindowStyle Hidden -WorkingDirectory $repo
    Write-Output "Started the Gemma news job."
}
# FinBERT needs torch, which the v2 environment has (same lockfile); this
# branch's code is put first on PYTHONPATH (DECISIONS 51).
if ($jobs | Where-Object { $_.CommandLine -like '*news_coverage tone*' }) {
    Write-Output "FinBERT tone job already running."
} else {
    $python = "$V2Project\.venv\Scripts\python.exe"
    $command = "set `"PYTHONPATH=$repo\src`" && set HF_HUB_DISABLE_IMPLICIT_TOKEN=1 && " +
        "`"$python`" -m structural_break.experiments.news_coverage tone " +
        "--output `"$Output`" >> `"$Output\tone.log`" 2>&1"
    Start-Process -FilePath cmd.exe -ArgumentList "/c `"$command`"" -WindowStyle Hidden -WorkingDirectory $repo
    Write-Output "Started the FinBERT tone job."
}
if (-not ($jobs | Where-Object { $_.CommandLine -like '*catalyst_evaluate_when_done*' }) -and
    -not (Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | Where-Object { $_.CommandLine -like '*catalyst_evaluate_when_done*' })) {
    Start-Process -FilePath powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\catalyst_evaluate_when_done.ps1" -WindowStyle Hidden -WorkingDirectory $repo
    Write-Output "Started the evaluation watcher (runs the test once both jobs finish)."
}
Write-Output "Check progress with: powershell -File scripts\catalyst_progress.ps1"