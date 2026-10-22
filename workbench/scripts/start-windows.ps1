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
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
$log = Join-Path $DataRoot "service-logs\$stamp"
$python = (Get-Command python).Source
# Quotes are required by Windows Start-Process when any argument contains spaces.
$arguments = @($entry, '--package', $package, '--data', $DataRoot, '--port', "$Port") | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $DataRoot -WindowStyle Hidden -RedirectStandardOutput "$log.stdout.log" -RedirectStandardError "$log.stderr.log" -PassThru
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 500
    $process.Refresh()
    if ($process.HasExited) {
        Get-Content "$log.stderr.log" -ErrorAction SilentlyContinue
        throw "Execution service exited with code $($process.ExitCode)."
    }
    try {
        $ready = Invoke-RestMethod -Uri $url -TimeoutSec 1
        if ($ready.solver.version -eq '2.0.0') {
            Write-Output "Workbench ready at http://127.0.0.1:$Port (PID $($process.Id))"
            exit 0
        }
    } catch {}
}
throw "Service startup is still pending. Check $log.stderr.log before retrying."
