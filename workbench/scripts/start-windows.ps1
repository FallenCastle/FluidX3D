#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$WorkspaceRoot = 'F:\01-Project\Opensource\01-FluidX3D',
    [ValidateRange(1024,65535)][int]$Port = 8765,
    [string]$DataRoot
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run the execution service on Windows.' }
if (-not $DataRoot) { $DataRoot = Join-Path $WorkspaceRoot 'workingdir\web-workbench' }
$package = Join-Path $WorkspaceRoot 'package\V2.0.0'
$entry = Join-Path (Split-Path -Parent $PSScriptRoot) 'service\server.py'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& python $entry --package $package --data $DataRoot --port $Port
exit $LASTEXITCODE
