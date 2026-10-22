#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$WorkspaceRoot = 'F:\01-Project\Opensource\01-FluidX3D',
    [ValidateRange(1024,65535)][int]$Port = 8765,
    [string]$DataRoot,
    [switch]$Background
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run the execution service on Windows.' }
if (-not $DataRoot) { $DataRoot = Join-Path $WorkspaceRoot 'workingdir\web-workbench' }
$package = Join-Path $WorkspaceRoot 'package\V2.0.0'
$entry = Join-Path (Split-Path -Parent $PSScriptRoot) 'service\server.py'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$url = "http://127.0.0.1:$Port/api/session"
$existing = $null
try { $existing = Invoke-RestMethod -Uri $url -TimeoutSec 2 } catch {}
if ($existing) {
    $expected = (Get-Content -Raw (Join-Path $package 'bin\build.json') | ConvertFrom-Json).executableSha256
    if ($existing.solver.product -ne 'Solver-IBM' -or $existing.solver.version -ne '2.0.0' -or $existing.solver.sha256 -ne $expected) {
        throw 'The port is occupied by an unexpected service.'
    }
    Write-Output "Workbench already running at http://127.0.0.1:$Port"
    exit 0
}
if (-not $Background) {
    & python $entry --package $package --data $DataRoot --port $Port
    exit $LASTEXITCODE
}
New-Item -ItemType Directory -Force (Join-Path $DataRoot 'service-logs') | Out-Null
$logRoot = Join-Path $DataRoot 'service-logs'
$python = (Get-Command python).Source
$arguments = @($python, $entry, '--package', $package, '--data', $DataRoot, '--port', "$Port", '--log-root', $logRoot) | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }
# WMI creates an independent process outside the SSH session's process job.
# Start-Process alone is terminated by Windows OpenSSH when its session exits.
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = ($arguments -join ' '); CurrentDirectory = $DataRoot}
if ($created.ReturnValue -ne 0) { throw "Cannot start service: Win32_Process.Create=$($created.ReturnValue)" }
$servicePid = $created.ProcessId
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 500
    if (-not (Get-Process -Id $servicePid -ErrorAction SilentlyContinue)) {
        throw "Execution service exited. Check $logRoot."
    }
    try {
        $ready = Invoke-RestMethod -Uri $url -TimeoutSec 1
        if ($ready.solver.version -eq '2.0.0') {
            Write-Output "Workbench ready at http://127.0.0.1:$Port (PID $servicePid)"
            exit 0
        }
    } catch {}
}
throw "Service startup is still pending. Check $logRoot before retrying."
