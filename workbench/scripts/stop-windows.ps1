#requires -Version 5.1
[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$url = "http://127.0.0.1:$Port/api"
$session = Invoke-RestMethod "$url/session" -TimeoutSec 3
if ($session.solver.product -ne 'Solver-IBM') { throw 'Unexpected service.' }
Invoke-RestMethod "$url/shutdown" -Method Post -ContentType 'application/json' -Body '{}' -Headers @{'X-Workbench-Token' = $session.token} | Out-Null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try { Invoke-RestMethod "$url/session" -TimeoutSec 1 | Out-Null } catch { Write-Output 'Workbench stopped.'; exit 0 }
}
throw 'Service has not stopped yet.'
