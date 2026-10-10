#requires -Version 5.1
<#
.SYNOPSIS
Read one detached intelligence build's progress without launching or monitoring it.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $LaunchReceipt,
    [ValidateRange(0, 100)]
    [int] $Tail = 3
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$LaunchReceipt = (Resolve-Path -LiteralPath $LaunchReceipt).ProviderPath
$receipt = Get-Content -LiteralPath $LaunchReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.schema_version -cne 'detached-intelligence-launch-v1') {
    throw 'Unsupported detached launch receipt.'
}
function Read-RecordedProcess {
    param([object] $Identity)
    try {
        $process = Get-Process -Id $Identity.pid -ErrorAction Stop
        $creation = $process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
        $executableMatches = $process.MainModule.FileName -ieq $Identity.executable
        if (-not $executableMatches) {
            $executableMatches = (Get-FileHash -LiteralPath $process.MainModule.FileName).Hash -ceq
                (Get-FileHash -LiteralPath $Identity.executable).Hash
        }
        if ($creation -cne $Identity.creation_filetime_utc -or
            -not $executableMatches) {
            return [ordered]@{ pid = $Identity.pid; state = 'PID_REUSED_OR_IDENTITY_MISMATCH' }
        }
        $native = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $Identity.pid)
        $marker = 'structural_break.research.cli'
        $markerProperty = $Identity.PSObject.Properties['command_marker']
        if ($null -ne $markerProperty) { $marker = $markerProperty.Value }
        if (-not $native -or -not $native.CommandLine -or -not $native.CommandLine.Contains($marker)) {
            return [ordered]@{ pid = $Identity.pid; state = 'COMMAND_IDENTITY_MISMATCH' }
        }
        return [ordered]@{
            pid = $Identity.pid
            state = 'LIVE'
            creation_filetime_utc = $creation
            cpu_seconds = $process.CPU
        }
    }
    catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
        return [ordered]@{ pid = $Identity.pid; state = 'NOT_LIVE_EXIT_CODE_NOT_RECORDED' }
    }
}
$processes = @(Read-RecordedProcess $receipt.process)
foreach ($identity in $receipt.observed_child_processes) {
    $processes += Read-RecordedProcess $identity
}
$workerState = $null
$workerStateProperty = $receipt.PSObject.Properties['worker_state']
if ($null -ne $workerStateProperty -and (Test-Path -LiteralPath $workerStateProperty.Value -PathType Leaf)) {
    $workerState = Get-Content -LiteralPath $workerStateProperty.Value -Raw -Encoding UTF8 | ConvertFrom-Json
    $childProperty = $workerState.PSObject.Properties['child_process']
    if ($null -ne $childProperty) { $processes += Read-RecordedProcess $childProperty.Value }
}
$exitReceipt = $null
$exitProperty = $receipt.PSObject.Properties['exit_receipt']
if ($null -ne $exitProperty -and (Test-Path -LiteralPath $exitProperty.Value -PathType Leaf)) {
    $exitReceipt = Get-Content -LiteralPath $exitProperty.Value -Raw -Encoding UTF8 | ConvertFrom-Json
}
$progress = $null
if (Test-Path -LiteralPath $receipt.progress -PathType Leaf) {
    # CLI replaces this file atomically; a transient shared-file error is reported honestly.
    $progress = Get-Content -LiteralPath $receipt.progress -Raw -Encoding UTF8 | ConvertFrom-Json
}
$completed = $receipt.completed_checkpoint_count_at_launch
if ($null -ne $progress) {
    $property = $progress.PSObject.Properties['completed_checkpoint_count']
    if ($null -eq $property) { $property = $progress.PSObject.Properties['completed'] }
    if ($null -ne $property) {
        # Prefix loading advances the event cursor without erasing verified existing files.
        $completed = [Math]::Max([long] $completed, [long] $property.Value)
    }
}
$stdoutTail = @()
$stderrTail = @()
if ($Tail -gt 0) {
    if (Test-Path -LiteralPath $receipt.stdout -PathType Leaf) {
        $stdoutTail = @(Get-Content -LiteralPath $receipt.stdout -Tail $Tail -Encoding UTF8)
    }
    if (Test-Path -LiteralPath $receipt.stderr -PathType Leaf) {
        $stderrTail = @(Get-Content -LiteralPath $receipt.stderr -Tail $Tail -Encoding UTF8)
    }
}
[ordered]@{
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    batch_name = $receipt.batch_name
    processes = $processes
    completed_checkpoint_count = $completed
    total_events = $receipt.total_events
    progress = $progress
    worker_state = $workerState
    exit_receipt = $exitReceipt
    stdout = $receipt.stdout
    stderr = $receipt.stderr
    stdout_tail = $stdoutTail
    stderr_tail = $stderrTail
    feature_manifest_present = (Test-Path -LiteralPath (
        Join-Path $receipt.batch_directory 'manifest.json'
    ) -PathType Leaf)
} | ConvertTo-Json -Depth 12
