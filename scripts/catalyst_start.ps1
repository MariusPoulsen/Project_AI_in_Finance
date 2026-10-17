# Start or resume the recent-news catalyst extraction (DECISIONS 50) as a
# detached background process. Safe to rerun: finished packs are skipped.
# Usage:  powershell -File scripts\catalyst_start.ps1 [-EnvFile PATH]
param(
    [string]$EnvFile = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance\.env",
    [string]$V2 = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance\data\research_v2",
    [string]$Output = "outputs\news_v1"
)
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$running = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like '*news_coverage run*' }
if ($running) { Write-Output "Already running (process $($running[0].ProcessId))."; exit 0 }
if (-not (Test-Path "$Output\queue.parquet")) {
    & .venv\Scripts\python.exe -m structural_break.experiments.news_coverage build --workspace-root data\team `
        --sec-metadata "$V2\sec_metadata\source_v3" --sec-cache "$V2\cache" --output $Output
}
$command = "`".venv\Scripts\python.exe`" -m structural_break.experiments.news_coverage run " +
    "--output `"$Output`" --env-file `"$EnvFile`" >> `"$Output\run.log`" 2>&1"
Start-Process -FilePath cmd.exe -ArgumentList "/c `"$command`"" -WindowStyle Hidden -WorkingDirectory $repo
Write-Output "Started. Check progress with: powershell -File scripts\catalyst_progress.ps1"