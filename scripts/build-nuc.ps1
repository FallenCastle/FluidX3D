#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$WorkspaceRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$BuildName = 'solver-ibm-v1.0.0',
    [ValidatePattern('^v[0-9]+$')]
    [string]$PlatformToolset = 'v142'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-GitText {
    param([string[]]$ArgumentList)
    $output = @(& git -C $script:RepositoryRoot @ArgumentList)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($ArgumentList -join ' ') failed with exit code $LASTEXITCODE."
    }
    return ($output -join "`n").Trim()
}

function Write-JsonFile {
    param($Value, [string]$Path)
    $json = $Value | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Invoke-MSBuildLogged {
    param([string[]]$ArgumentList, [string]$LogPath, [switch]$Quiet)
    # Windows PowerShell can wrap native stderr as errors; the native exit code is authoritative.
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& $script:MSBuildPath @ArgumentList 2>&1)
        $nativeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    $lines = @($output | ForEach-Object { $_.ToString() })
    [System.IO.File]::WriteAllLines($LogPath, [string[]]$lines, [System.Text.UTF8Encoding]::new($false))
    if (-not $Quiet) {
        $lines | ForEach-Object { Write-Host $_ }
    }
    if ($nativeExitCode -ne 0) {
        throw "MSBuild failed with exit code $nativeExitCode. See $LogPath"
    }
    return ($lines -join "`n")
}

function ConvertTo-MSBuildDirectory {
    param([string]$Path)
    # Forward slashes avoid native argument quoting problems with a trailing backslash.
    return ([System.IO.Path]::GetFullPath($Path).Replace('\', '/').TrimEnd('/') + '/')
}

$RepositoryRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$WorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$outputDirectory = Join-Path (Join-Path $WorkspaceRoot 'bin') $BuildName
$executablePath = Join-Path $outputDirectory 'Solver-IBM.exe'
$manifestPath = Join-Path $outputDirectory 'build.json'
$temporaryManifestPath = Join-Path $outputDirectory 'build.json.tmp'
$lockStream = $null
$record = $null
$recordPath = $null
$ownsOutput = $false

try {
    if ($env:OS -ne 'Windows_NT') {
        throw 'Run this script on NUC under Windows, not on the Mac.'
    }
    $versionHeader = [IO.File]::ReadAllText((Join-Path $RepositoryRoot 'src\version.hpp'))
    $productMatch = [regex]::Match($versionHeader, '(?m)^#define\s+SOLVER_IBM_NAME\s+"([^"]+)"\s*$')
    if (-not $productMatch.Success) { throw 'Missing SOLVER_IBM_NAME in src/version.hpp.' }
    $productName = $productMatch.Groups[1].Value
    $versionParts = foreach ($part in @('MAJOR', 'MINOR', 'PATCH')) {
        $match = [regex]::Match($versionHeader, "(?m)^#define\s+SOLVER_IBM_VERSION_$part\s+([0-9]+)\s*$")
        if (-not $match.Success) { throw "Missing SOLVER_IBM_VERSION_$part in src/version.hpp." }
        $match.Groups[1].Value
    }
    $productVersion = $versionParts -join '.'
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    # One build at a time may publish a particular BuildName.
    $lockStream = [System.IO.File]::Open((Join-Path $outputDirectory '.build.lock'),
        [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    $ownsOutput = $true
    Remove-Item -LiteralPath $manifestPath, $temporaryManifestPath -Force -ErrorAction SilentlyContinue

    $gitCommit = Invoke-GitText -ArgumentList @('rev-parse', 'HEAD')
    $sourceTree = Invoke-GitText -ArgumentList @('rev-parse', 'HEAD:src')
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $buildId = "$stamp-$($gitCommit.Substring(0, 12))"
    $logDirectory = Join-Path (Join-Path (Join-Path $WorkspaceRoot 'workingdir') '_builds') $buildId
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $buildLog = Join-Path $logDirectory 'msbuild.log'
    $recordPath = Join-Path $logDirectory 'build.json'
    $record = [ordered]@{
        schemaVersion = 1
        status = 'running'
        buildName = $BuildName
        productName = $productName
        productVersion = $productVersion
        executableName = 'Solver-IBM.exe'
        gitCommit = $gitCommit
        sourceTree = $sourceTree
        repositoryPath = $RepositoryRoot
        executablePath = $executablePath
        executableSha256 = $null
        configuration = 'Release'
        platform = 'x64'
        platformToolset = $PlatformToolset
        buildLog = $buildLog
        startedAtUtc = [DateTime]::UtcNow.ToString('o')
        completedAtUtc = $null
    }
    Write-JsonFile $record $recordPath

    $gitStatus = Invoke-GitText -ArgumentList @('status', '--porcelain', '--untracked-files=all')
    if ($gitStatus) {
        throw "The source repository must be clean before building. Commit and push on the Mac, then pull on NUC.`n$gitStatus"
    }
    $projectPath = Join-Path $RepositoryRoot 'FluidX3D.vcxproj'
    if (-not (Test-Path -LiteralPath $projectPath -PathType Leaf)) {
        throw "Project file not found: $projectPath"
    }

    $vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswherePath -PathType Leaf)) {
        throw "vswhere.exe not found: $vswherePath"
    }
    $installationJson = & $vswherePath -products '*' -requires Microsoft.Component.MSBuild -format json -utf8
    if ($LASTEXITCODE -ne 0) { throw 'Visual Studio discovery failed.' }
    $installations = @($installationJson | ConvertFrom-Json)
    $MSBuildPath = $null
    $targetsPath = $null
    $selectedInstallation = $null
    foreach ($installation in $installations) {
        $candidateMSBuild = Join-Path $installation.installationPath 'MSBuild\Current\Bin\MSBuild.exe'
        $targetsRoot = Join-Path $installation.installationPath 'MSBuild\Microsoft\VC'
        if (-not (Test-Path -LiteralPath $candidateMSBuild -PathType Leaf)) { continue }
        if (-not (Test-Path -LiteralPath $targetsRoot -PathType Container)) { continue }
        foreach ($candidate in @(Get-ChildItem -LiteralPath $targetsRoot -Directory | Sort-Object Name -Descending)) {
            $toolsetProps = Join-Path $candidate.FullName "Platforms\x64\PlatformToolsets\$PlatformToolset\Toolset.props"
            if ((Test-Path -LiteralPath $toolsetProps -PathType Leaf) -and
                (Test-Path -LiteralPath (Join-Path $candidate.FullName 'Microsoft.Cpp.targets') -PathType Leaf)) {
                $MSBuildPath = $candidateMSBuild
                $targetsPath = $candidate.FullName
                $selectedInstallation = $installation
                break
            }
        }
        if ($MSBuildPath) { break }
    }
    if (-not $MSBuildPath) {
        throw "No Visual Studio installation provides MSBuild and x64 $PlatformToolset C++ targets."
    }

    $intermediateDirectory = Join-Path (Join-Path (Join-Path $RepositoryRoot 'temp') $BuildName) $buildId
    $commonArguments = @(
        $projectPath,
        '/nologo',
        '/p:Configuration=Release',
        '/p:Platform=x64',
        '/p:PreferredToolArchitecture=x64',
        "/p:PlatformToolset=$PlatformToolset",
        "/p:VCTargetsPath=$(ConvertTo-MSBuildDirectory $targetsPath)",
        "/p:SolutionDir=$(ConvertTo-MSBuildDirectory $RepositoryRoot)",
        "/p:OutDir=$(ConvertTo-MSBuildDirectory $outputDirectory)",
        "/p:IntDir=$(ConvertTo-MSBuildDirectory $intermediateDirectory)",
        '/p:TargetName=Solver-IBM'
    )
    $evaluationLog = Join-Path $logDirectory 'evaluation.json'
    $propertyNames = 'VCTargetsPath,PlatformToolset,VCToolsInstallDir,VCToolsVersion,WindowsSdkDir,WindowsTargetPlatformVersion,TargetPath,OutDir,IntDir'
    $evaluationText = Invoke-MSBuildLogged -ArgumentList ($commonArguments + @('/verbosity:quiet', "-getProperty:$propertyNames")) -LogPath $evaluationLog -Quiet
    $evaluation = ($evaluationText | ConvertFrom-Json).Properties
    if ($evaluation.WindowsTargetPlatformVersion -eq '10.0') {
        # The original project requests a floating SDK. Pin an installed full version for provenance.
        $sdkIncludeRoot = Join-Path $evaluation.WindowsSdkDir 'Include'
        $sdkCandidates = @(Get-ChildItem -LiteralPath $sdkIncludeRoot -Directory |
            Where-Object { $_.Name -match '^10\.0\.\d+\.\d+$' } |
            Sort-Object { [version]$_.Name } -Descending)
        $sdkVersion = $null
        foreach ($candidate in $sdkCandidates) {
            $requiredSdkFiles = @(
                (Join-Path $candidate.FullName 'um\Windows.h'),
                (Join-Path $candidate.FullName 'ucrt\stdio.h'),
                (Join-Path $evaluation.WindowsSdkDir "Lib\$($candidate.Name)\um\x64\kernel32.lib"),
                (Join-Path $evaluation.WindowsSdkDir "Lib\$($candidate.Name)\ucrt\x64\ucrt.lib")
            )
            $missingSdkFiles = @($requiredSdkFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
            if ($missingSdkFiles.Count -eq 0) { $sdkVersion = $candidate.Name; break }
        }
        if (-not $sdkVersion) { throw "No complete Windows 10 SDK found in $($evaluation.WindowsSdkDir)." }
        Copy-Item -LiteralPath $evaluationLog -Destination (Join-Path $logDirectory 'evaluation-floating-sdk.json')
        $commonArguments += "/p:WindowsTargetPlatformVersion=$sdkVersion"
        $evaluationText = Invoke-MSBuildLogged -ArgumentList ($commonArguments + @('/verbosity:quiet', "-getProperty:$propertyNames")) -LogPath $evaluationLog -Quiet
        $evaluation = ($evaluationText | ConvertFrom-Json).Properties
    }
    if ($evaluation.PlatformToolset -ne $PlatformToolset) {
        throw "MSBuild resolved an unexpected PlatformToolset: $($evaluation.PlatformToolset)"
    }
    if ((ConvertTo-MSBuildDirectory $evaluation.VCTargetsPath) -ne (ConvertTo-MSBuildDirectory $targetsPath)) {
        throw "MSBuild resolved an unexpected VCTargetsPath: $($evaluation.VCTargetsPath)"
    }
    if ([System.IO.Path]::GetFullPath($evaluation.TargetPath) -ne $executablePath) {
        throw "MSBuild resolved an unexpected TargetPath: $($evaluation.TargetPath)"
    }
    $compilerPath = Join-Path $evaluation.VCToolsInstallDir 'bin\Hostx64\x64\cl.exe'
    $sdkHeaderPath = Join-Path $evaluation.WindowsSdkDir "Include\$($evaluation.WindowsTargetPlatformVersion)\um\Windows.h"
    if (-not (Test-Path -LiteralPath $compilerPath -PathType Leaf)) {
        throw "The selected C++ compiler is missing: $compilerPath"
    }
    if (-not (Test-Path -LiteralPath $sdkHeaderPath -PathType Leaf)) {
        throw "The selected Windows SDK is incomplete: $sdkHeaderPath"
    }
    $record['visualStudio'] = $selectedInstallation.installationVersion
    $record['msbuildPath'] = $MSBuildPath
    $record['msbuildVersion'] = (Get-Item -LiteralPath $MSBuildPath).VersionInfo.FileVersion
    $record['vcTargetsPath'] = $evaluation.VCTargetsPath
    $record['compilerPath'] = $compilerPath
    $record['vcToolsVersion'] = $evaluation.VCToolsVersion
    $record['windowsSdkDirectory'] = $evaluation.WindowsSdkDir
    $record['windowsSdkVersion'] = $evaluation.WindowsTargetPlatformVersion
    $record['evaluationLog'] = $evaluationLog
    $record['projectBlob'] = Invoke-GitText -ArgumentList @('rev-parse', 'HEAD:FluidX3D.vcxproj')
    $record['definesBlob'] = Invoke-GitText -ArgumentList @('rev-parse', 'HEAD:src/defines.hpp')
    $record['setupBlob'] = Invoke-GitText -ArgumentList @('rev-parse', 'HEAD:src/setup.cpp')
    # Get-Content adds provider metadata to strings; PS 5.1 recursively serializes it.
    $record['declaredDefineLines'] = @([System.IO.File]::ReadAllLines((Join-Path $RepositoryRoot 'src\defines.hpp')) | Where-Object { $_ -match '^\s*#define\s+' })
    $record['msbuildArguments'] = $commonArguments + @('/t:Rebuild', '/m', '/nodeReuse:false', '/verbosity:minimal')
    Write-JsonFile $record $recordPath

    # Remove the old executable before building; a failed build cannot reuse it.
    Remove-Item -LiteralPath $executablePath -Force -ErrorAction SilentlyContinue
    Write-Host "Building $gitCommit with $PlatformToolset using $targetsPath"
    $null = Invoke-MSBuildLogged -ArgumentList $record.msbuildArguments -LogPath $buildLog
    if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
        throw "MSBuild succeeded but the executable was not produced: $executablePath"
    }
    if ((Invoke-GitText -ArgumentList @('rev-parse', 'HEAD')) -ne $gitCommit -or
        (Invoke-GitText -ArgumentList @('status', '--porcelain', '--untracked-files=all'))) {
        throw 'The source repository changed during the build; the executable will not be published.'
    }
    $record['executableSha256'] = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $versionOutput = @(& $executablePath --version)
    if ($LASTEXITCODE -ne 0 -or ($versionOutput -join "`n").Trim() -ne "$productName $productVersion") {
        throw 'Built executable --version does not match src/version.hpp.'
    }
    $record['reportedVersion'] = ($versionOutput -join "`n").Trim()
    $record['status'] = 'succeeded'
    $record['completedAtUtc'] = [DateTime]::UtcNow.ToString('o')
    Write-JsonFile $record $recordPath
    Write-JsonFile $record $temporaryManifestPath
    Move-Item -LiteralPath $temporaryManifestPath -Destination $manifestPath -Force
    Write-Host "Build succeeded: $executablePath"
    Write-Host "Build record: $manifestPath"
}
catch {
    if ($ownsOutput) {
        Remove-Item -LiteralPath $manifestPath, $temporaryManifestPath, $executablePath -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $record -and $recordPath) {
        $record['status'] = 'failed'
        $record['completedAtUtc'] = [DateTime]::UtcNow.ToString('o')
        $record['error'] = $_.Exception.Message
        Write-JsonFile $record $recordPath
    }
    throw
}
finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
}
