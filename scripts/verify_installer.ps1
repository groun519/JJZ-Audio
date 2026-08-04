param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [string]$PreviousInstallerPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$baselineInstaller = if ($PreviousInstallerPath) {
    (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
} else {
    $installer
}
$testId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$testRoot = Join-Path $env:TEMP ("jz-" + $testId)
$installDir = Join-Path $testRoot "app"
$dataRoot = Join-Path $testRoot "data"
$sentinel = Join-Path $dataRoot "settings\preserve.txt"

function Get-InstallerVersion([string]$SetupPath) {
    $name = [System.IO.Path]::GetFileName($SetupPath)
    if ($name -notmatch '^JJZero-Audio-(\d+\.\d+\.\d+)-Setup\.exe$') {
        throw "Installer name does not contain a release version: $name"
    }
    return $Matches[1]
}

function Invoke-Setup([string]$SetupPath, [string]$LogName) {
    $logPath = Join-Path $testRoot $LogName
    $arguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=`"$installDir`"",
        "/LOG=`"$logPath`""
    )
    $process = Start-Process -FilePath $SetupPath -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Installer failed with exit code $($process.ExitCode). Log: $logPath"
    }
}

function Assert-InstalledVersion([string]$ExpectedVersion) {
    $executable = Join-Path $installDir "JJZero Audio.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Installed executable was not found: $executable"
    }
    $actualVersion = (Get-Item -LiteralPath $executable).VersionInfo.ProductVersion
    if ($actualVersion -ne $ExpectedVersion) {
        throw "Installed version mismatch. Expected $ExpectedVersion, found $actualVersion"
    }
}

function Invoke-DistributionVerification {
    & $python scripts\verify_distribution.py $installDir
    if ($LASTEXITCODE -ne 0) {
        throw "Installed distribution verification failed with exit code $LASTEXITCODE"
    }
}

New-Item -ItemType Directory -Path (Split-Path -Parent $sentinel) -Force | Out-Null
Set-Content -LiteralPath $sentinel -Value "preserve-user-data" -Encoding UTF8

$baselineVersion = Get-InstallerVersion $baselineInstaller
$targetVersion = Get-InstallerVersion $installer

Invoke-Setup $baselineInstaller "install-$baselineVersion.log"
Assert-InstalledVersion $baselineVersion
Invoke-Setup $installer "update-$targetVersion.log"
Assert-InstalledVersion $targetVersion
Invoke-DistributionVerification

if ((Get-Content -LiteralPath $sentinel -Raw).Trim() -ne "preserve-user-data") {
    throw "User data changed during the update test: $sentinel"
}

$uninstaller = Join-Path $installDir "unins000.exe"
if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    throw "Uninstaller was not created: $uninstaller"
}
$uninstallLog = Join-Path $testRoot "uninstall.log"
$uninstallArguments = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/LOG=`"$uninstallLog`""
)
$uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList $uninstallArguments -Wait -PassThru -WindowStyle Hidden
if ($uninstallProcess.ExitCode -ne 0) {
    throw "Uninstaller failed with exit code $($uninstallProcess.ExitCode). Log: $uninstallLog"
}
if (Test-Path -LiteralPath (Join-Path $installDir "JJZero Audio.exe") -PathType Leaf) {
    throw "Application executable remained after uninstall: $installDir"
}
if ((Get-Content -LiteralPath $sentinel -Raw).Trim() -ne "preserve-user-data") {
    throw "User data was removed during uninstall: $sentinel"
}

Write-Output "Verified installer upgrade $baselineVersion -> $targetVersion and uninstall: $installer"
Write-Output "Verification logs: $testRoot"
