#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$WorkspaceRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$BuildName = 'baseline-original',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$CaseName = 'benchmark',
    [ValidateRange(0, 2147483647)]
    [int]$DeviceId,
    [ValidateRange(1, 86400)]
    [int]$TimeoutSeconds = 900,
    [switch]$ExpectBenchmark
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') {
    throw 'Run FluidX3D on the Windows NUC, not on the Mac.'
}
foreach ($name in @($BuildName, $CaseName)) {
    if ($name.EndsWith('.') -or $name -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
        throw "Invalid Windows directory name: $name"
    }
}

$WorkspaceRoot = [IO.Path]::GetFullPath($WorkspaceRoot)
$buildDirectory = Join-Path (Join-Path $WorkspaceRoot 'bin') $BuildName
$buildManifestPath = Join-Path $buildDirectory 'build.json'
$buildExecutable = Join-Path $buildDirectory 'FluidX3D.exe'
$build = Get-Content -LiteralPath $buildManifestPath -Raw | ConvertFrom-Json
foreach ($property in @('schemaVersion', 'status', 'gitCommit', 'sourceTree', 'executablePath',
        'executableSha256', 'platformToolset', 'buildLog', 'completedAtUtc')) {
    if ($build.PSObject.Properties.Name -notcontains $property) {
        throw "Build manifest is missing '$property': $buildManifestPath"
    }
}
if ($build.schemaVersion -ne 1 -or $build.status -ne 'succeeded') {
    throw "A successful schemaVersion=1 build manifest is required: $buildManifestPath"
}
if ($build.gitCommit -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
    throw 'Build manifest has an invalid Git commit.'
}
if ([IO.Path]::GetFullPath([string]$build.executablePath) -ine $buildExecutable) {
    throw "Build manifest executablePath does not match $buildExecutable"
}
$executableHash = (Get-FileHash -LiteralPath $buildExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
if ($executableHash -ine $build.executableSha256) {
    throw 'Executable SHA256 does not match its build manifest. Build again before running.'
}

$startedAt = [DateTime]::UtcNow
$runId = $startedAt.ToString('yyyyMMddTHHmmssfffZ') + '-' + $build.gitCommit.Substring(0, 12)
$caseDirectory = Join-Path (Join-Path $WorkspaceRoot 'workingdir') $CaseName
$runDirectory = Join-Path $caseDirectory $runId
$runtimeCaseDirectory = Join-Path (Join-Path (Join-Path $WorkspaceRoot 'bin') '_runs') $CaseName
$runtimeDirectory = Join-Path $runtimeCaseDirectory $runId
$logsDirectory = Join-Path $runDirectory 'logs'
$resultsDirectory = Join-Path $runDirectory 'results'
$inputsDirectory = Join-Path $runDirectory 'inputs'
$runtimeExecutable = Join-Path $runtimeDirectory 'FluidX3D.exe'
$exportJunction = Join-Path $runtimeDirectory 'export'
$stdoutPath = Join-Path $logsDirectory 'stdout.log'
$stderrPath = Join-Path $logsDirectory 'stderr.log'
$stdinPath = Join-Path $logsDirectory 'stdin.empty'
$runnerLog = Join-Path $logsDirectory 'runner.log'
$runManifestPath = Join-Path $runDirectory 'run.json'
$requestedDevice = $null
$programArguments = @()
if ($PSBoundParameters.ContainsKey('DeviceId')) {
    $requestedDevice = $DeviceId
    $programArguments = @($DeviceId.ToString([Globalization.CultureInfo]::InvariantCulture))
}

# Never reuse another run's directory or export mapping.
New-Item -ItemType Directory -Path $caseDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeCaseDirectory -Force | Out-Null
if ((Test-Path -LiteralPath $runDirectory) -or (Test-Path -LiteralPath $runtimeDirectory)) {
    throw "Run ID already exists; run the command again: $runId"
}
New-Item -ItemType Directory -Path $runDirectory | Out-Null
foreach ($directory in @($logsDirectory, $resultsDirectory, $inputsDirectory)) {
    New-Item -ItemType Directory -Path $directory | Out-Null
}

$record = [ordered]@{
    schemaVersion = 1
    runId = $runId
    caseName = $CaseName
    buildName = $BuildName
    status = 'starting'
    startedAtUtc = $startedAt.ToString('o')
    completedAtUtc = $null
    elapsedSeconds = $null
    processId = $null
    exitCode = $null
    timeoutSeconds = $TimeoutSeconds
    deviceIdRequested = $requestedDevice
    build = [ordered]@{
        manifestPath = $buildManifestPath
        gitCommit = $build.gitCommit
        sourceTree = $build.sourceTree
        executablePath = $buildExecutable
        executableSha256 = $executableHash
        platformToolset = $build.platformToolset
        buildLog = $build.buildLog
        completedAtUtc = $build.completedAtUtc
    }
    command = [ordered]@{
        executable = $runtimeExecutable
        arguments = $programArguments
        workingDirectory = $runDirectory
    }
    paths = [ordered]@{
        runDirectory = $runDirectory
        inputs = $inputsDirectory
        results = $resultsDirectory
        runtimeDirectory = $runtimeDirectory
        runtimeExecutable = $runtimeExecutable
        exportJunction = $exportJunction
        stdout = $stdoutPath
        stderr = $stderrPath
        runnerLog = $runnerLog
    }
    validation = [ordered]@{
        expectBenchmark = [bool]$ExpectBenchmark
        peakMlups = $null
        grid256Cubed = $false
        d3q19SrtFp16s = $false
        declaredSteps10000 = $false
    }
    failureReason = $null
}

function Save-RunRecord {
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
}

function Stop-RunProcessTree {
    param([Diagnostics.Process]$RunProcess)
    $RunProcess.Refresh()
    if ($RunProcess.HasExited) { return }
    # Use the exact process we launched; never stop FluidX3D processes by name.
    $killer = $null
    try {
        $killer = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\taskkill.exe') `
            -ArgumentList @('/PID', $RunProcess.Id.ToString(), '/T', '/F') `
            -NoNewWindow -PassThru `
            -RedirectStandardOutput (Join-Path $logsDirectory 'cleanup.stdout.log') `
            -RedirectStandardError (Join-Path $logsDirectory 'cleanup.stderr.log')
        if (-not $killer.WaitForExit(15000)) {
            $killer.Kill()
            $null = $killer.WaitForExit(5000)
            throw 'taskkill did not finish within 15 seconds.'
        }
        if (-not $RunProcess.WaitForExit(15000)) {
            throw "Could not confirm that FluidX3D process $($RunProcess.Id) exited."
        }
        $RunProcess.WaitForExit()
    }
    finally {
        if ($null -ne $killer) { $killer.Dispose() }
        $RunProcess.Refresh()
        if (-not $RunProcess.HasExited) {
            $RunProcess.Kill()
            if (-not $RunProcess.WaitForExit(15000)) {
                throw "FluidX3D process $($RunProcess.Id) is still running; inspect it on NUC."
            }
        }
    }
}

$process = $null
$clock = [Diagnostics.Stopwatch]::StartNew()
$failure = $null
try {
    Save-RunRecord
    New-Item -ItemType Directory -Path $runtimeDirectory | Out-Null
    Copy-Item -LiteralPath $buildExecutable -Destination $runtimeExecutable
    if ((Get-FileHash -LiteralPath $runtimeExecutable -Algorithm SHA256).Hash -ine $executableHash) {
        throw 'Runtime executable snapshot SHA256 verification failed.'
    }
    $build | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath (Join-Path $runDirectory 'build.json') -Encoding UTF8
    # This junction is local to this run, and its target is this run's results directory.
    New-Item -ItemType Junction -Path $exportJunction -Target $resultsDirectory | Out-Null
    [IO.File]::WriteAllBytes($stdinPath, [byte[]]@())
    "Started at $($startedAt.ToString('o')); executable: $runtimeExecutable" |
        Set-Content -LiteralPath $runnerLog -Encoding UTF8
    Write-Host "Run directory: $runDirectory"
    Write-Host "Standard output: $stdoutPath"
    $startParameters = @{
        FilePath = $runtimeExecutable
        WorkingDirectory = $runDirectory
        RedirectStandardInput = $stdinPath
        RedirectStandardOutput = $stdoutPath
        RedirectStandardError = $stderrPath
        NoNewWindow = $true
        PassThru = $true
    }
    if ($programArguments.Count -gt 0) { $startParameters.ArgumentList = $programArguments }
    # An empty stdin provides EOF: the Windows benchmark's final std::cin.get() returns.
    $process = Start-Process @startParameters
    $null = $process.Handle
    $record.processId = $process.Id
    $record.status = 'running'
    Save-RunRecord
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $record.status = 'timed_out'
        Stop-RunProcessTree -RunProcess $process
        throw "FluidX3D exceeded the $TimeoutSeconds second timeout."
    }
    # Flush the redirected output after process termination before checking its contents.
    $process.WaitForExit()
    $record.exitCode = $process.ExitCode
    if ($process.ExitCode -ne 0) {
        throw "FluidX3D exited with code $($process.ExitCode). See $stderrPath and $stdoutPath"
    }
    if (@(Select-String -LiteralPath @($stdoutPath, $stderrPath) `
            -Pattern '(?m)(?:^|\r)\s*(?:\|\s*)?Error\s*:' -List).Count -gt 0) {
        throw 'FluidX3D printed an Error message. Inspect the run logs.'
    }
    if ($ExpectBenchmark) {
        $peak = Select-String -LiteralPath $stdoutPath -Pattern 'Peak MLUPs/s\s*=\s*([0-9]+)' |
            Select-Object -Last 1
        if ($null -ne $peak) {
            $record.validation.peakMlups = [long]$peak.Matches[0].Groups[1].Value
        }
        $record.validation.grid256Cubed = [bool](Select-String -LiteralPath $stdoutPath `
            -Pattern '\|\s*Grid Resolution\s*\|\s*256 x 256 x 256 = 16777216\s*\|' -Quiet)
        $record.validation.d3q19SrtFp16s = [bool](Select-String -LiteralPath $stdoutPath `
            -Pattern '\|\s*LBM Type\s*\|\s*D3Q19 SRT \(FP32/FP16S\)\s*\|' -Quiet)
        $record.validation.declaredSteps10000 = [bool](Select-String -LiteralPath $stdoutPath `
            -Pattern '\|\s*Time Steps\s*\|\s*10000\s*\|' -Quiet)
        if ($null -eq $record.validation.peakMlups -or $record.validation.peakMlups -le 0 -or
                -not $record.validation.grid256Cubed -or -not $record.validation.d3q19SrtFp16s -or
                -not $record.validation.declaredSteps10000) {
            throw 'Original benchmark validation failed: require a positive Peak MLUPs/s, 256^3, D3Q19 SRT FP16S, and Time Steps 10000.'
        }
    }
    $record.status = 'succeeded'
}
catch {
    $failure = $_.Exception.Message
    if ($record.status -ne 'timed_out') { $record.status = 'failed' }
    $record.failureReason = $failure
}
finally {
    try {
        if ($null -ne $process) {
            Stop-RunProcessTree -RunProcess $process
            $record.exitCode = $process.ExitCode
        }
    }
    catch {
        $failure = "Cleanup failed: $($_.Exception.Message); previous failure: $failure"
        $record.status = 'cleanup_failed'
        $record.failureReason = $failure
    }
    finally {
        if ($null -ne $process) { $process.Dispose() }
        if ($record.status -in @('starting', 'running')) {
            $record.status = 'interrupted'
            $record.failureReason = 'Run interrupted before completion.'
        }
        $clock.Stop()
        $record.completedAtUtc = [DateTime]::UtcNow.ToString('o')
        $record.elapsedSeconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
        if (Test-Path -LiteralPath $stdinPath) { Remove-Item -LiteralPath $stdinPath }
        Save-RunRecord
        "Finished: $($record.status); exit code: $($record.exitCode); seconds: $($record.elapsedSeconds)" |
            Add-Content -LiteralPath $runnerLog -Encoding UTF8
    }
}
Write-Host "Run record: $runManifestPath"
if ($null -ne $failure) { throw $failure }
Write-Host "Run succeeded. Results: $resultsDirectory"
