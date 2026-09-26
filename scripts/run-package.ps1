#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,
    [string]$ConfigPath,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$CaseName = 'solver-ibm-demo',
    [ValidateRange(0, 2147483647)]
    [int]$DeviceId,
    [ValidateRange(1, 86400)]
    [int]$TimeoutSeconds = 900,
    [switch]$PrepareOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run Solver-IBM on the Windows NUC, not on the Mac.' }
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot -ErrorAction Stop).ProviderPath.TrimEnd('\', '/')
$WorkspaceRoot = [IO.Path]::GetFullPath($WorkspaceRoot).TrimEnd('\', '/')

function Assert-OutsidePackage {
    param([string]$Path)
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if ($full.Equals($PackageRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($PackageRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Workspace and run outputs must stay outside the immutable package: $full"
    }
    # Reject junctions/symlinks on existing output paths rather than write through
    # an alias that could point back into the fixed release package.
    $current = $full
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Workspace output paths cannot contain a junction or symlink: $current"
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

Assert-OutsidePackage $WorkspaceRoot
Assert-OutsidePackage (Join-Path (Join-Path $WorkspaceRoot 'workingdir') $CaseName)
Assert-OutsidePackage (Join-Path (Join-Path (Join-Path $WorkspaceRoot 'bin') '_runs') $CaseName)

$manifest = Get-Content -LiteralPath (Join-Path $PackageRoot 'manifest.json') -Raw | ConvertFrom-Json
$build = Get-Content -LiteralPath (Join-Path $PackageRoot 'bin\build.json') -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.product -cne 'Solver-IBM' -or
    $build.status -cne 'succeeded' -or $build.productName -cne $manifest.product -or
    $build.productVersion -cne $manifest.version -or $build.sourceTree -cne $manifest.source_tree) {
    throw 'Release identity does not match the successful build manifest.'
}
$executable = Join-Path $PackageRoot 'bin\Solver-IBM.exe'
$entry = @($manifest.files | Where-Object { $_.path -ceq 'bin/Solver-IBM.exe' })
$hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
if ($entry.Count -ne 1 -or $hash -cne $build.executableSha256 -or
    $hash -cne $entry[0].sha256 -or (Get-Item -LiteralPath $executable).Length -ne $entry[0].bytes) {
    throw 'Packaged executable size/SHA256 does not match the release and build manifests.'
}
if (-not $ConfigPath) { $ConfigPath = Join-Path $PackageRoot 'cases\configs\periodic-lattice.json' }
$parameters = @{
    WorkspaceRoot = $WorkspaceRoot
    ExecutablePath = $executable
    ConfigPath = $ConfigPath
    CaseName = $CaseName
    BuildName = 'solver-ibm-v' + $manifest.version
    TimeoutSeconds = $TimeoutSeconds
    PrepareOnly = $PrepareOnly
}
if ($PSBoundParameters.ContainsKey('DeviceId')) { $parameters.DeviceId = $DeviceId }
& (Join-Path $PackageRoot 'source\scripts\run-nuc.ps1') @parameters
