param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [string]$PreviousInstallerPath,

    [string]$RuntimePackageIndex = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = (Resolve-Path (Join-Path $projectRoot "release")).Path.TrimEnd('\')
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$previousInstaller = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
$installerScript = Join-Path $projectRoot "packaging\JJZeroAudio.iss"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$testId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$verificationInstaller = ""

function Get-InstallerVersion([string]$SetupPath) {
    $version = [string](Get-Item -LiteralPath $SetupPath).VersionInfo.ProductVersion
    $version = $version.Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        $name = [IO.Path]::GetFileName($SetupPath)
        if ($name -match '^JJZero-Audio-(\d+\.\d+\.\d+)') {
            $version = $Matches[1]
        }
    }
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        throw "Installer metadata does not contain a release version: $SetupPath"
    }
    return $version
}

function Invoke-GateScript(
    [string]$ScriptPath,
    [string[]]$Arguments,
    [string]$Description
) {
    & $powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

$compilerCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 7\ISCC.exe"
)
$compiler = $compilerCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
    Select-Object -First 1
if (-not $compiler) {
    throw "Inno Setup compiler was not found."
}

$version = Get-InstallerVersion $installer
$previousVersion = Get-InstallerVersion $previousInstaller
if ([version]$previousVersion -ge [version]$version) {
    throw "Previous installer must be older than the release candidate: $previousVersion -> $version"
}
if ([IO.Path]::GetFileName($installer) -like '*-Verification-Setup.exe') {
    throw "Release installation verification requires the public installer."
}

$verificationVersion = "$version-Gate-$testId"
$verificationInstaller = Join-Path `
    $releaseRoot `
    "JJZero-Audio-$verificationVersion-Verification-Setup.exe"

Push-Location $projectRoot
try {
    & $compiler "/DAppVersion=$verificationVersion" "/DVerificationBuild" $installerScript
    if ($LASTEXITCODE -ne 0 -or
        -not (Test-Path -LiteralPath $verificationInstaller -PathType Leaf)) {
        throw "Verification installer build failed with exit code $LASTEXITCODE."
    }

    $installerArguments = @(
        "-InstallerPath", $installer,
        "-PreviousInstallerPath", $previousInstaller
    )
    if ($RuntimePackageIndex) {
        $runtimeIndex = (Resolve-Path -LiteralPath $RuntimePackageIndex).Path
        $installerArguments += @("-RuntimePackageIndex", $runtimeIndex)
    }
    Invoke-GateScript `
        (Join-Path $PSScriptRoot "verify_installer.ps1") `
        $installerArguments `
        "Installer lifecycle verification"
    Invoke-GateScript `
        (Join-Path $PSScriptRoot "verify_uninstaller_storage.ps1") `
        @("-InstallerPath", $verificationInstaller, "-Scenario", "All") `
        "Normal uninstall verification"
    Invoke-GateScript `
        (Join-Path $PSScriptRoot "verify_complete_uninstall.ps1") `
        @("-InstallerPath", $verificationInstaller, "-Scenario", "All") `
        "Complete Removal verification"
}
finally {
    Pop-Location
    if ($verificationInstaller -and (Test-Path -LiteralPath $verificationInstaller)) {
        $resolvedArtifact = (Resolve-Path -LiteralPath $verificationInstaller).Path
        if (-not $resolvedArtifact.StartsWith(
            "$releaseRoot\",
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove verification artifact outside release: $resolvedArtifact"
        }
        [IO.File]::Delete($resolvedArtifact)
    }
}

Write-Output "Release installation and removal gates passed: $previousVersion -> $version"
