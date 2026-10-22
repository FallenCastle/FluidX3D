#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(1024,65535)][int]$Port = 8765,
    [string]$WorkspaceRoot = 'F:\01-Project\Opensource\01-FluidX3D',
    [string]$DataRoot
)
$ErrorActionPreference = 'Stop'
$lines = & (Join-Path $PSScriptRoot 'manage-windows.ps1') -Action stop -Port $Port -WorkspaceRoot $WorkspaceRoot -DataRoot $DataRoot
$line = @($lines | Where-Object { $_ -like 'SOLVER_WORKBENCH_STATE=*' }) | Select-Object -Last 1
if (-not $line) { throw 'No confirmed shutdown state received.' }
$state = $line.Substring('SOLVER_WORKBENCH_STATE='.Length) | ConvertFrom-Json
if ($state.result -ne 'stopped') {
    $state | ConvertTo-Json -Depth 5 | Write-Output
    throw 'A calculation or validation is still active. Service was not stopped.'
}
Write-Output 'Workbench stopped. No Solver-IBM or FluidX3D process remains.'
