# Show progress of the full-coverage catalyst extraction (DECISIONS 47).
# Usage:  powershell -File scripts\catalyst_progress.ps1
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$running = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like '*catalyst_coverage run*' }
if ($running) { Write-Output "Process: running ($($running[0].ProcessId))" }
else { Write-Output "Process: NOT running (restart with scripts\catalyst_start.ps1)" }
& .venv\Scripts\python.exe -m structural_break.experiments.catalyst_coverage status --output outputs\catalyst_v3
