param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [string]$PreviousInstallerPath = "",
    [string]$RuntimePackageIndex = "",
    [switch]$KeepArtifacts
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
$runtimeSentinel = Join-Path $installDir "runtime\rvc\weights\preserve-runtime-model.pth"
$runtimeLogSentinel = Join-Path $installDir "runtime\rvc\logs\preserve-runtime-log.txt"
$managedRuntimeSentinel = Join-Path $installDir "runtime\managed-component.bin"
$appMutexName = "JJZeroAudio.E5ED303D5BB24B1E8AA8434C16C4D3AE"
$storageFile = Join-Path $dataRoot "settings\storage.json"
$songLibraryFile = Join-Path $dataRoot "settings\song_library.json"
$legacySettingsFile = Join-Path $installDir "settings\app_settings.json"
$legacySongFile = Join-Path $installDir "workspace\library\songs\upgrade-song\song.json"
$legacyModelCatalog = Join-Path $installDir "workspace\models\catalog.json"
$externalInferenceModel = Join-Path $dataRoot "external-models\upgrade-voice.pth"

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
    $arguments = @("scripts\verify_distribution.py", $installDir)
    if (-not $RuntimePackageIndex) {
        $arguments += "--app-only"
    }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Installed distribution verification failed with exit code $LASTEXITCODE"
    }
}

function Assert-PreservedFiles([hashtable]$ExpectedHashes, [string]$Stage) {
    foreach ($path in $ExpectedHashes.Keys) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "User data disappeared during ${Stage}: $path"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actual -ne $ExpectedHashes[$path]) {
            throw "User data changed during ${Stage}: $path"
        }
    }
}

New-Item -ItemType Directory -Path (Split-Path -Parent $sentinel) -Force | Out-Null
Set-Content -LiteralPath $sentinel -Value "preserve-user-data" -Encoding UTF8
$env:JJZERO_DATA_ROOT = $dataRoot

$baselineVersion = Get-InstallerVersion $baselineInstaller
$targetVersion = Get-InstallerVersion $installer

Invoke-Setup $baselineInstaller "install-$baselineVersion.log"
Assert-InstalledVersion $baselineVersion
New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeSentinel) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeLogSentinel) -Force | Out-Null
Set-Content -LiteralPath $runtimeSentinel -Value "preserve-runtime-model" -Encoding UTF8
Set-Content -LiteralPath $runtimeLogSentinel -Value "preserve-runtime-log" -Encoding UTF8
Set-Content -LiteralPath $managedRuntimeSentinel -Value "remove-managed-runtime" -Encoding UTF8
New-Item -ItemType Directory -Path (Split-Path -Parent $legacySettingsFile) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $legacySongFile) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $legacyModelCatalog) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $externalInferenceModel) -Force | Out-Null
Set-Content -LiteralPath $legacySettingsFile -Value '{"theme_mode":"dark"}' -Encoding UTF8
Set-Content -LiteralPath $legacySongFile -Value '{"version":1,"id":"upgrade-song","title":"Upgrade Song"}' -Encoding UTF8
Set-Content -LiteralPath $externalInferenceModel -Value "linked-inference-model" -Encoding UTF8
Set-Content -LiteralPath $legacyModelCatalog -Value @"
{
  "version": 1,
  "models": [{
    "id": "linked-upgrade-voice",
    "name": "upgrade-voice",
    "mode": "linked",
    "runtime_root": "$($installDir.Replace('\', '\\'))",
    "source_folder": "$((Split-Path -Parent $externalInferenceModel).Replace('\', '\\'))",
    "inference_model": "$($externalInferenceModel.Replace('\', '\\'))",
    "index_file": "",
    "generator_checkpoint": "",
    "discriminator_checkpoint": "",
    "created_at": "2026-01-01T00:00:00+00:00",
    "display_name": "Upgrade Voice",
    "tags": [],
    "notes": "",
    "default_pitch": 0,
    "default_device": "cpu"
  }]
}
"@ -Encoding UTF8
Set-Content -LiteralPath $storageFile -Value @"
{
  "version": 1,
  "workspace_root": "$((Join-Path $installDir 'workspace').Replace('\', '\\'))",
  "workspace_anchor": "$($installDir.Replace('\', '\\'))"
}
"@ -Encoding UTF8
Set-Content -LiteralPath $songLibraryFile -Value '{"paths":["C:\\upgrade-song.wav"]}' -Encoding UTF8
$preservedFiles = @{}
foreach ($path in @(
    $sentinel,
    $storageFile,
    $songLibraryFile,
    $legacySettingsFile,
    $legacySongFile,
    $legacyModelCatalog,
    $externalInferenceModel
)) {
    $preservedFiles[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}
Invoke-Setup $installer "update-$targetVersion.log"
Assert-InstalledVersion $targetVersion
Assert-PreservedFiles $preservedFiles "application update"
if ((Get-Content -LiteralPath $runtimeSentinel -Raw).Trim() -ne "preserve-runtime-model") {
    throw "Existing runtime data changed during the app update: $runtimeSentinel"
}
if ((Get-Content -LiteralPath $runtimeLogSentinel -Raw).Trim() -ne "preserve-runtime-log") {
    throw "Existing runtime logs changed during the app update: $runtimeLogSentinel"
}
if ($RuntimePackageIndex) {
    $packageIndex = (Resolve-Path -LiteralPath $RuntimePackageIndex).Path
    & $python scripts\install_runtime_packages.py $packageIndex (Join-Path $installDir "runtime")
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime package installation failed with exit code $LASTEXITCODE"
    }
}
Invoke-DistributionVerification
Assert-PreservedFiles $preservedFiles "runtime update"

if ((Get-Content -LiteralPath $runtimeSentinel -Raw).Trim() -ne "preserve-runtime-model") {
    throw "Runtime model data changed during the runtime update: $runtimeSentinel"
}
if ((Get-Content -LiteralPath $runtimeLogSentinel -Raw).Trim() -ne "preserve-runtime-log") {
    throw "Runtime log data changed during the runtime update: $runtimeLogSentinel"
}

if ((Get-Content -LiteralPath $sentinel -Raw).Trim() -ne "preserve-user-data") {
    throw "User data changed during the update test: $sentinel"
}

$uninstaller = Join-Path $installDir "unins000.exe"
if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    throw "Uninstaller was not created: $uninstaller"
}
$appMutex = [System.Threading.Mutex]::new($false, $appMutexName)
try {
    $blockedUninstall = Start-Process `
        -FilePath $uninstaller `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($blockedUninstall.ExitCode -eq 0) {
        throw "Uninstaller did not report the running application mutex."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $installDir "JJZero Audio.exe") -PathType Leaf)) {
        throw "Uninstaller removed application files while the application mutex was active."
    }
}
finally {
    $appMutex.Dispose()
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
if (Test-Path -LiteralPath (Join-Path $installDir "runtime")) {
    throw "Downloaded runtime remained after uninstall: $installDir"
}
$preservedRuntimeRoot = Join-Path $dataRoot "preserved-runtime"
$preservedModel = @(
    Get-ChildItem -LiteralPath $preservedRuntimeRoot -Recurse -Filter "preserve-runtime-model.pth" -File
)
$preservedLog = @(
    Get-ChildItem -LiteralPath $preservedRuntimeRoot -Recurse -Filter "preserve-runtime-log.txt" -File
)
if ($preservedModel.Count -ne 1 -or
    (Get-Content -LiteralPath $preservedModel[0].FullName -Raw).Trim() -ne "preserve-runtime-model") {
    throw "Runtime model was not preserved during uninstall: $preservedRuntimeRoot"
}
if ($preservedLog.Count -ne 1 -or
    (Get-Content -LiteralPath $preservedLog[0].FullName -Raw).Trim() -ne "preserve-runtime-log") {
    throw "Runtime logs were not preserved during uninstall: $preservedRuntimeRoot"
}
if ((Get-Content -LiteralPath $sentinel -Raw).Trim() -ne "preserve-user-data") {
    throw "User data was removed during uninstall: $sentinel"
}
Assert-PreservedFiles $preservedFiles "uninstall"

Write-Output "Verified installer upgrade $baselineVersion -> $targetVersion and uninstall: $installer"
if ($KeepArtifacts) {
    Write-Output "Verification logs: $testRoot"
}
else {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
    Write-Output "Removed installer verification files: $testRoot"
}
