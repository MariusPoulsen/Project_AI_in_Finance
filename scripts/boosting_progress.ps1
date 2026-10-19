# Progress of the Decision 65 boosting tuning run.
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
& (Join-Path $repo ".venv\Scripts\python.exe") -m structural_break.experiments.p6_boosting status
$shells = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue
if ($shells | Where-Object { $_.CommandLine -like '*boosting_watcher*' }) { Write-Output "Watcher running (log: outputs\p6_boosting\watcher.log)" }
elseif (Test-Path "outputs\p6_boosting\DONE") { Write-Output "Watcher finished: outputs\p6_boosting\evaluation.json" }
else { Write-Output "Watcher NOT running (restart: powershell -File scripts\boosting_watcher.ps1)" }
if (Test-Path "outputs\p6_boosting\watcher.log") { Get-Content "outputs\p6_boosting\watcher.log" -Tail 3 }
