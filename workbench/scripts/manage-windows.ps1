#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('start','stop','status')][string]$Action,
    [string]$WorkspaceRoot = 'F:\01-Project\Opensource\01-FluidX3D',
    [ValidateRange(1024,65535)][int]$Port = 8765,
    [string]$DataRoot
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not $DataRoot) { $DataRoot = Join-Path $WorkspaceRoot 'workingdir\web-workbench' }
$entry = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) 'service\server.py'))
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$api = "http://127.0.0.1:$Port/api"

function Get-WorkbenchState {
    $processes = @(Get-CimInstance Win32_Process)
    $services = @($processes | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match ('(?:^|\s)"?' + [regex]::Escape($entry) + '"?(?=\s|$)') -and
        $_.CommandLine -match ('"?--data"?\s+"?' + [regex]::Escape($DataRoot) + '"?(?=\s|$)')
    })
    # Also detect validation and orphan processes. Never terminate external calculations.
    $solvers = @($processes | Where-Object { $_.Name -match '^(Solver-IBM|FluidX3D)\.exe$' } |
        Select-Object ProcessId,ParentProcessId,Name,ExecutablePath)
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq $Port })
    $session = $null
    $job = $null
    if ($listeners.Count -gt 0) {
        if ($services.Count -ne 1 -or @($listeners | Where-Object {
            $_.OwningProcess -ne $services[0].ProcessId -or $_.LocalAddress -ne '127.0.0.1'
        }).Count -gt 0) { throw "Port $Port belongs to another process. No process was stopped." }
        $session = Invoke-RestMethod "$api/session" -TimeoutSec 5
        $build = Get-Content -Raw (Join-Path $WorkspaceRoot 'package\V2.0.0\bin\build.json') | ConvertFrom-Json
        if ($session.solver.product -ne 'Solver-IBM' -or $session.solver.version -ne '2.0.0' -or
            $session.solver.sha256 -ne $build.executableSha256) {
            throw 'Unexpected service or solver identity. No process was stopped.'
        }
        if ($session.active_job) { $job = Invoke-RestMethod "$api/jobs/$($session.active_job)" -TimeoutSec 5 }
    } elseif ($services.Count -gt 0) {
        throw 'Workbench process exists but its API is unavailable. Check service-logs; nothing was terminated.'
    }
    return [pscustomobject]@{session=$session;job=$job;services=$services;solvers=$solvers;listeners=$listeners}
}

function Write-State($state, [string]$result, [bool]$started = $false) {
    $jobInfo = $null
    if ($state.job) { $jobInfo = $state.job | Select-Object id,case_name,status,process_id }
    $identity = $null
    if ($state.session) { $identity = $state.session.solver }
    # Session token stays inside PowerShell and is never printed.
    $output = [ordered]@{
        result=$result; started=$started; active_job=$jobInfo; solver=$identity
        service_pids=@($state.services | ForEach-Object { $_.ProcessId })
        solver_processes=@($state.solvers); listening=($state.listeners.Count -gt 0)
    }
    Write-Output ('SOLVER_WORKBENCH_STATE=' + ($output | ConvertTo-Json -Depth 6 -Compress))
}

$state = Get-WorkbenchState
if ($Action -eq 'status') {
    $result = if ($state.session) { 'running' } else { 'stopped' }
    Write-State $state $result
    exit 0
}
if ($Action -eq 'start') {
    $started = -not [bool]$state.session
    if ($started) {
        & (Join-Path $PSScriptRoot 'start-windows.ps1') -WorkspaceRoot $WorkspaceRoot -DataRoot $DataRoot -Port $Port -Background
        if ($LASTEXITCODE -ne 0) { throw 'Windows service startup failed.' }
        $state = Get-WorkbenchState
        if (-not $state.session) { throw 'Service did not become ready.' }
    }
    Write-State $state 'running' $started
    exit 0
}
if ($state.job -or $state.solvers.Count -gt 0) {
    Write-State $state 'blocked'
    exit 0
}
if ($state.session) {
    $originalService = $state.services[0]
    try {
        Invoke-RestMethod "$api/shutdown" -Method Post -ContentType 'application/json' -Body '{}' `
            -Headers @{'X-Workbench-Token'=$state.session.token} -TimeoutSec 5 | Out-Null
    } catch {
        # The API lock prevents a new job racing with the idle check.
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
            Write-State (Get-WorkbenchState) 'blocked'
            exit 0
        }
        throw
    }
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        $stillRunning = Get-CimInstance Win32_Process -Filter "ProcessId=$($originalService.ProcessId)"
        if (-not $stillRunning -or $stillRunning.CreationDate -ne $originalService.CreationDate) { break }
        Start-Sleep -Milliseconds 250
    }
    $state = Get-WorkbenchState
    if ($state.session -or $state.services.Count -gt 0 -or $state.listeners.Count -gt 0) {
        throw 'Service has not fully stopped. SSH tunnel is preserved.'
    }
    if ($state.solvers.Count -gt 0) {
        Write-State $state 'blocked'
        exit 0
    }
}
Write-State $state 'stopped'
