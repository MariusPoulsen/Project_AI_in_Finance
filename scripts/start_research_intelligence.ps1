#requires -Version 5.1
<#
.SYNOPSIS
Start one audited, detached research-v2 intelligence build without a session monitor.
.DESCRIPTION
Run only after the scientific checkpoint audit and source freeze. The CLI validates
the SHA-bound audit; this launcher checks Git cleanliness and refuses another live
intelligence build. It never changes policies, downloads model assets, retries a
failed job, or launches fitting. Logs and receipts remain on disk after it returns.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ResumeAudit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-fA-F0-9]{64}$')]
    [string] $ResumeAuditSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-fA-F0-9]{40}$')]
    [string] $ExpectedHead,
    [Parameter(Mandatory = $true)]
    [ValidateRange(0, 37421)]
    [int] $CompletedCheckpointCount,
    [string] $ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string] $WorkspaceRoot,
    [ValidatePattern('^[a-z][a-z0-9_]{2,99}$')]
    [string] $BatchName = 'development_detached_v2',
    [string] $GitExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-WindowsArgument {
    param([AllowEmptyString()][string] $Value)
    # Windows CRT argument quoting, including quotes and trailing backslashes.
    $result = [System.Text.StringBuilder]::new()
    [void] $result.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes++
            continue
        }
        if ($character -eq '"') {
            [void] $result.Append(('\' * (2 * $slashes + 1) -join ''))
        }
        elseif ($slashes) {
            [void] $result.Append(('\' * $slashes -join ''))
        }
        [void] $result.Append($character)
        $slashes = 0
    }
    [void] $result.Append(('\' * (2 * $slashes) -join ''))
    [void] $result.Append('"')
    return $result.ToString()
}

function Write-NewJson {
    param([string] $Path, [object] $Value)
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [System.IO.File]::WriteAllText(
        $temporary, ($Value | ConvertTo-Json -Depth 12), [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::Move($temporary, $Path)
}

function Get-NativeIdentity {
    param([System.Diagnostics.Process] $Process)
    $creation = $Process.StartTime.ToUniversalTime()
    return [ordered]@{
        pid = $Process.Id
        creation_filetime_utc = $creation.ToFileTimeUtc().ToString()
        created_at_utc = $creation.ToString('o')
        executable = $Process.MainModule.FileName
        command_marker = 'research_detached_process.py'
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'This detached launcher requires Windows. On Colab, use the research CLI directly.'
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
if (-not $WorkspaceRoot) { $WorkspaceRoot = Join-Path $ProjectRoot 'data\research_v2' }
$WorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).ProviderPath
$ResumeAudit = (Resolve-Path -LiteralPath $ResumeAudit).ProviderPath
$actualAuditSha256 = (Get-FileHash -LiteralPath $ResumeAudit -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualAuditSha256 -cne $ResumeAuditSha256.ToLowerInvariant()) {
    throw 'Resume audit SHA-256 does not match; the detached process was not started.'
}
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The project .venv Python is missing. Install the frozen NLP environment before launch.'
}
$workerScript = Join-Path $ProjectRoot 'scripts\research_detached_process.py'
if (-not (Test-Path -LiteralPath $workerScript -PathType Leaf)) {
    throw 'The detached worker script is missing.'
}
if (-not $GitExecutable) {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) { $GitExecutable = $gitCommand.Source }
    else { $GitExecutable = Join-Path $env:LOCALAPPDATA 'CodexRepoTools\git\cmd\git.exe' }
}
$GitExecutable = (Resolve-Path -LiteralPath $GitExecutable).ProviderPath
$actualHead = & $GitExecutable -C $ProjectRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualHead.Trim() -cne $ExpectedHead.ToLowerInvariant()) {
    throw 'The checkout HEAD does not match the audited source freeze.'
}
$trackedChanges = & $GitExecutable -C $ProjectRoot status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or $trackedChanges) {
    throw 'Tracked files have changed since the source freeze; commit and audit before launch.'
}
$batchDirectory = Join-Path (Join-Path $WorkspaceRoot 'intelligence') $BatchName
if (-not (Test-Path -LiteralPath (Join-Path $batchDirectory 'events') -PathType Container)) {
    throw 'The audited checkpoint directory is missing; prepare and audit this batch before launch.'
}
$checkpointCount = @(Get-ChildItem -LiteralPath (Join-Path $batchDirectory 'events') -Filter '*.json' -File).Count
if ($checkpointCount -ne $CompletedCheckpointCount) {
    throw 'The checkpoint file count changed after the audit; verify the batch before launch.'
}
if (Test-Path -LiteralPath (Join-Path $batchDirectory 'manifest.json')) {
    throw 'The batch already has a manifest. Verify the existing generation instead of relaunching.'
}
$acceptanceDirectory = Join-Path $ProjectRoot '.acceptance'
[void] [System.IO.Directory]::CreateDirectory($acceptanceDirectory)
$lockPath = Join-Path $acceptanceDirectory 'detached_intelligence_launch.lock'
$launchLock = [System.IO.File]::Open(
    $lockPath, [System.IO.FileMode]::OpenOrCreate,
    [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None
)
$launchedProcess = $null
try {
    $liveBuilds = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object {
            $_.CommandLine -and ((
                $_.CommandLine.Contains('structural_break.research.cli') -and
                $_.CommandLine.Contains('build-intelligence') -and
                $_.CommandLine.Contains('research_registry_0bd415d2a5af1f4891dc1f0d')
            ) -or $_.CommandLine.Contains($workerScript))
        })
    if ($liveBuilds.Count) {
        throw ('Another intelligence build is live (PID(s): ' +
            (($liveBuilds | ForEach-Object { $_.ProcessId }) -join ', ') + '). No duplicate was launched.')
    }
    $launchId = 'intelligence_' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '_' +
        [guid]::NewGuid().ToString('N').Substring(0, 12)
    $launchDirectory = Join-Path $acceptanceDirectory $launchId
    [void] [System.IO.Directory]::CreateDirectory($launchDirectory)
    $stdoutPath = Join-Path $launchDirectory 'stdout.log'
    $stderrPath = Join-Path $launchDirectory 'stderr.log'
    $progressPath = Join-Path $launchDirectory 'progress.json'
    $receiptPath = Join-Path $launchDirectory 'launch.json'
    $planPath = Join-Path $launchDirectory 'launch-plan.json'
    $arguments = @(
        '-u', '-m', 'structural_break.research.cli', 'build-intelligence',
        '--project-root', $ProjectRoot, '--workspace-root', $WorkspaceRoot,
        '--registry-version', 'research_registry_0bd415d2a5af1f4891dc1f0d',
        '--batch-name', $BatchName, '--sec-source', 'source_v3',
        '--sentiment-preprocessing', 'sec-sentence-quality-wordpiece-v2',
        '--catalyst-max-events', '500', '--resume-audit', $ResumeAudit,
        '--resume-audit-sha256', $actualAuditSha256, '--progress-file', $progressPath
    )
    $argumentLine = ($arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' '
    $command = (ConvertTo-WindowsArgument $python) + ' ' + $argumentLine
    $receipt = [ordered]@{
        schema_version = 'detached-intelligence-launch-v1'
        launch_method = 'WMI_SERVICE_PARENT_WITH_DURABLE_NATIVE_WAIT_WORKER'
        status = 'PREPARED'
        source_revision = $actualHead.Trim()
        project_root = $ProjectRoot
        workspace_root = $WorkspaceRoot
        batch_name = $BatchName
        registry_version = 'research_registry_0bd415d2a5af1f4891dc1f0d'
        sec_source = 'source_v3'
        sentiment_preprocessing = 'sec-sentence-quality-wordpiece-v2'
        catalyst_max_events = 500
        max_events = $null
        final_test_unlocked = $false
        resume_audit = $ResumeAudit
        resume_audit_sha256 = $actualAuditSha256
        completed_checkpoint_count_at_launch = $CompletedCheckpointCount
        total_events = 37421
        batch_directory = $batchDirectory
        executable = $python
        arguments = $arguments
        command = $command
        stdout = $stdoutPath
        stderr = $stderrPath
        progress = $progressPath
        receipt = $receiptPath
        worker_ready = (Join-Path $launchDirectory 'worker-ready.json')
        worker_ack = (Join-Path $launchDirectory 'worker-ack.json')
        worker_state = (Join-Path $launchDirectory 'worker-state.json')
        exit_receipt = (Join-Path $launchDirectory 'exit.json')
        manual_status_command = ("& '" + (
            Join-Path $ProjectRoot 'scripts\check_research_intelligence.ps1'
        ).Replace("'", "''") + "' -LaunchReceipt '" + $receiptPath.Replace("'", "''") + "'")
        started_at_utc = $null
        process = $null
        observed_child_processes = @()
        service_parent = $null
        worker_command = $null
        plan_sha256 = $null
    }
    Write-NewJson $planPath $receipt
    $planSha256 = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $workerArguments = @('-u', $workerScript, '--plan', $planPath, '--plan-sha256', $planSha256)
    $workerCommand = (ConvertTo-WindowsArgument $python) + ' ' + (
        ($workerArguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' '
    )
    # WMI's service parent, rather than the Codex shell, owns the worker.
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -Property @{
        ShowWindow = [UInt16]0
        CreateFlags = [UInt32]0x208 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    } -ClientOnly
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $workerCommand
        CurrentDirectory = $ProjectRoot
        ProcessStartupInformation = $startup
    }
    if ($created.ReturnValue -ne 0) { throw ('WMI worker creation failed: ' + $created.ReturnValue) }
    $launchedProcess = Get-Process -Id $created.ProcessId -ErrorAction Stop
    $nativeWorker = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $created.ProcessId)
    $serviceParent = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $nativeWorker.ParentProcessId)
    if ($serviceParent.Name -ine 'WmiPrvSE.exe') {
        throw 'The worker does not have the expected independent WMI service parent.'
    }
    # Bounded one-time startup handshake, not an ongoing progress monitor.
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while (-not (Test-Path -LiteralPath $receipt.worker_ready -PathType Leaf)) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Detached worker readiness timed out.' }
        Start-Sleep -Milliseconds 100
    }
    $ready = Get-Content -LiteralPath $receipt.worker_ready -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($ready.plan_sha256 -cne $planSha256 -or $ready.worker.parent_pid -ne $launchedProcess.Id) {
        throw 'Detached worker readiness belongs to another process or plan.'
    }
    $receipt.status = 'DETACHED_SERVICE_WORKER_STARTED'
    $receipt.started_at_utc = [DateTime]::UtcNow.ToString('o')
    $receipt.process = Get-NativeIdentity $launchedProcess
    $actualWorker = Get-Process -Id $ready.worker.pid -ErrorAction Stop
    $executableMatches = $actualWorker.MainModule.FileName -ieq $ready.worker.executable
    if (-not $executableMatches) {
        # uv's cpython-3.11 junction and physical cpython-3.11.x image name are aliases.
        $executableMatches = (Get-FileHash -LiteralPath $actualWorker.MainModule.FileName).Hash -ceq
            (Get-FileHash -LiteralPath $ready.worker.executable).Hash
    }
    if ($actualWorker.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -cne $ready.worker.creation_filetime_utc -or
        -not $executableMatches) {
        throw 'Detached worker native process identity changed during startup.'
    }
    $receipt.observed_child_processes = @($ready.worker)
    $receipt.service_parent = [ordered]@{
        pid = $serviceParent.ProcessId
        name = $serviceParent.Name
        created_at_utc = $serviceParent.CreationDate.ToUniversalTime().ToString('o')
        timestamp_precision = 'CIM microseconds'
    }
    $receipt.worker_command = $workerCommand
    $receipt.plan_sha256 = $planSha256
    Write-NewJson $receiptPath $receipt
    Write-NewJson $receipt.worker_ack @{
        plan_sha256 = $planSha256
        wmi_wrapper_pid = $launchedProcess.Id
    }
    $receipt | ConvertTo-Json -Depth 12
}
catch {
    if ($null -ne $launchedProcess) {
        Write-Warning ('A detached process was started at PID ' + $launchedProcess.Id +
            '; retain its launch-plan and logs. It has not been stopped or automatically retried.')
    }
    throw
}
finally {
    $launchLock.Dispose()
}
