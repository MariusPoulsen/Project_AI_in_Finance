# Start or resume the full-coverage catalyst extraction (DECISIONS 47) as a
# detached background process. Safe to rerun: finished packs are skipped.
# Usage:  powershell -File scripts\catalyst_start.ps1 [-EnvFile PATH]
param(
    [string]$EnvFile = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance\.env",
    [string]$Checkpoints = "$env:USERPROFILE\OneDrive\Skrivebord\Dat-Øk\Applied_AI_in_Finance\Project_AI_in_Finance\data\research_v2\intelligence\development_clockgap_v2\events",
    [string]$ModelInputs = "data\team\artifacts\research\research_evaluation_16a431c4fea73ffd35f56062\model_inputs.parquet",
    [string]$Output = "outputs\catalyst_v3"
)
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$running = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like '*catalyst_coverage run*' }
if ($running) { Write-Output "Already running (process $($running[0].ProcessId))."; exit 0 }
New-Item -ItemType Directory -Force $Output | Out-Null
if (-not (Test-Path "$Output\index.parquet")) {
    & .venv\Scripts\python.exe -m structural_break.experiments.catalyst_coverage index --checkpoints $Checkpoints --output $Output
}
$command = "`".venv\Scripts\python.exe`" -m structural_break.experiments.catalyst_coverage run " +
    "--checkpoints `"$Checkpoints`" --model-inputs `"$ModelInputs`" --output `"$Output`" " +
    "--env-file `"$EnvFile`" >> `"$Output\run.log`" 2>&1"
Start-Process -FilePath cmd.exe -ArgumentList "/c `"$command`"" -WindowStyle Hidden -WorkingDirectory $repo
Write-Output "Started. Check progress with: powershell -File scripts\catalyst_progress.ps1"
