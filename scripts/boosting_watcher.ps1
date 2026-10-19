# Runs the Decision 65 boosting tuning to completion, then the evaluation.
# Resumable: finished tasks are skipped. Logs to outputs\p6_boosting\watcher.log.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$out = Join-Path $repo "outputs\p6_boosting"
New-Item -ItemType Directory -Force $out | Out-Null
$log = Join-Path $out "watcher.log"
$python = Join-Path $repo ".venv\Scripts\python.exe"
"$(Get-Date -Format s) watcher started" | Out-File -Append -Encoding utf8 $log
for ($attempt = 1; $attempt -le 3; $attempt++) {
    & $python -m structural_break.experiments.p6_boosting run --workers 7 *>> $log
    if (Test-Path (Join-Path $out "run_done")) { break }
    "$(Get-Date -Format s) run attempt $attempt stopped early; retrying" | Out-File -Append -Encoding utf8 $log
}
if (Test-Path (Join-Path $out "run_done")) {
    & $python -m structural_break.experiments.p6_boosting evaluate *>> $log
    "$(Get-Date -Format s) evaluation finished" | Out-File -Append -Encoding utf8 $log
    "done" | Out-File -Encoding utf8 (Join-Path $out "DONE")
}
