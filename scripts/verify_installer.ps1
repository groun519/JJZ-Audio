param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [string]$PreviousInstallerPath = "",
    [string]$RuntimePackageIndex = "",
    [string]$AppMutexName = "JJZeroAudio.E5ED303D5BB24B1E8AA8434C16C4D3AE",
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
$storageFile = Join-Path $dataRoot "settings\storage.json"
$initialSetupFile = Join-Path $dataRoot "settings\initial_setup.json"
$songLibraryFile = Join-Path $dataRoot "settings\song_library.json"
$legacySettingsFile = Join-Path $installDir "settings\app_settings.json"
$legacySongFile = Join-Path $installDir "workspace\library\songs\upgrade-song\song.json"
$legacySongAudio = Join-Path $installDir "workspace\library\songs\upgrade-song\01_source\audio\upgrade-song.wav"
$legacyVocalRoot = Join-Path $installDir "workspace\library\songs\upgrade-song\02_vocal\separations\run-upgrade\htdemucs\upgrade-song"
$legacyVocalFile = Join-Path $legacyVocalRoot "vocals.wav"
$legacyInstrumentalFile = Join-Path $legacyVocalRoot "no_vocals.wav"
$legacyExportFile = Join-Path $installDir "output\exports\upgrade-mix.wav"
$legacyCacheFile = Join-Path $dataRoot "cache\upgrade-cache.bin"
$legacyModelCatalog = Join-Path $installDir "workspace\models\catalog.json"
$externalInferenceModel = Join-Path $dataRoot "external-models\upgrade-voice.pth"
$managedStorageRoot = Join-Path $testRoot "managed-storage"
$uninstallRegistryKey = "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$uninstallRegistryPsPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$registryBackup = Join-Path $env:TEMP "jjzero-uninstall-$testId.reg"

function Get-InstallerVersion([string]$SetupPath) {
    $version = [string](Get-Item -LiteralPath $SetupPath).VersionInfo.ProductVersion
    $version = $version.Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        $name = [System.IO.Path]::GetFileName($SetupPath)
        if ($name -match '^JJZero-Audio-(\d+\.\d+\.\d+)') {
            $version = $Matches[1]
        }
    }
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        throw "Installer metadata does not contain a release version: $SetupPath"
    }
    return $version
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

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

$registrationExisted = $false
if (Test-Path -LiteralPath $uninstallRegistryPsPath) {
    & reg.exe export $uninstallRegistryKey $registryBackup /y *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not back up the existing JJZero Audio uninstall registration."
    }
    $registrationExisted = $true
}

try {
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
New-Item -ItemType Directory -Path (Split-Path -Parent $legacySongAudio) -Force | Out-Null
New-Item -ItemType Directory -Path $legacyVocalRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $legacyExportFile) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $legacyCacheFile) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $legacyModelCatalog) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $externalInferenceModel) -Force | Out-Null
Write-Utf8NoBom $legacySettingsFile '{"theme_mode":"dark"}'
Set-Content -LiteralPath $legacySongAudio -Value "upgrade-song-audio" -Encoding UTF8
Set-Content -LiteralPath $legacyVocalFile -Value "upgrade-vocal" -Encoding UTF8
Set-Content -LiteralPath $legacyInstrumentalFile -Value "upgrade-instrumental" -Encoding UTF8
Set-Content -LiteralPath $legacyExportFile -Value "upgrade-export" -Encoding UTF8
Set-Content -LiteralPath $legacyCacheFile -Value "upgrade-cache" -Encoding UTF8
Write-Utf8NoBom $legacySongFile @"
{
  "version": 1,
  "id": "upgrade-song",
  "title": "Upgrade Song",
  "created_at": "2026-01-01T00:00:00+00:00",
  "removed": false,
  "source": {
    "audio": "01_source/audio/upgrade-song.wav",
    "type": "local",
    "url": "",
    "sha256": "",
    "original_name": "upgrade-song.wav"
  },
  "vocal": {
    "active_output_id": "upgrade-output",
    "detached_outputs": [],
    "outputs": [{
      "id": "upgrade-output",
      "label": "Upgrade Separation",
      "job_dir": "@project/workspace/library/songs/upgrade-song/02_vocal/separations/run-upgrade/htdemucs/upgrade-song",
      "added_at": "2026-01-01T00:00:00+00:00",
      "active_converted": ""
    }]
  }
}
"@
Set-Content -LiteralPath $externalInferenceModel -Value "linked-inference-model" -Encoding UTF8
Write-Utf8NoBom $legacyModelCatalog @"
{
  "version": 1,
  "models": [{
    "id": "linked-upgrade-voice",
    "name": "upgrade-voice",
    "mode": "linked",
    "runtime_root": "$((Join-Path $installDir 'runtime\rvc').Replace('\', '\\'))",
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
"@
Write-Utf8NoBom $initialSetupFile @"
{
  "version": 1,
  "media_root": "$($installDir.Replace('\', '\\'))",
  "diagnostics_ready": true
}
"@
Write-Utf8NoBom $storageFile @"
{
  "version": 1,
  "workspace_root": "$((Join-Path $installDir 'workspace').Replace('\', '\\'))",
  "workspace_anchor": "$($installDir.Replace('\', '\\'))"
}
"@
Write-Utf8NoBom $songLibraryFile '{"paths":["C:\\upgrade-song.wav"]}'
$preservedFiles = @{}
foreach ($path in @(
    $sentinel,
    $storageFile,
    $initialSetupFile,
    $songLibraryFile,
    $legacySettingsFile,
    $legacySongFile,
    $legacySongAudio,
    $legacyVocalFile,
    $legacyInstrumentalFile,
    $legacyExportFile,
    $legacyCacheFile,
    $legacyModelCatalog,
    $externalInferenceModel
)) {
    $preservedFiles[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}
$immutableSourceFiles = $preservedFiles.Clone()
$immutableSourceFiles.Remove($storageFile)
Invoke-Setup $installer "update-$targetVersion.log"
Assert-InstalledVersion $targetVersion
Assert-PreservedFiles $preservedFiles "application update"
if ((Get-Content -LiteralPath $runtimeSentinel -Raw).Trim() -ne "preserve-runtime-model") {
    throw "Existing runtime data changed during the app update: $runtimeSentinel"
}
if ((Get-Content -LiteralPath $runtimeLogSentinel -Raw).Trim() -ne "preserve-runtime-log") {
    throw "Existing runtime logs changed during the app update: $runtimeLogSentinel"
}

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $projectRoot "src"
try {
    & $python scripts\verify_storage_upgrade.py $installDir $dataRoot $managedStorageRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Managed storage migration verification failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
Assert-PreservedFiles $immutableSourceFiles "managed storage migration"

$managedFiles = @(
    (Join-Path $managedStorageRoot "Data\library\songs\upgrade-song\song.json"),
    (Join-Path $managedStorageRoot "Data\library\songs\upgrade-song\01_source\audio\upgrade-song.wav"),
    (Join-Path $managedStorageRoot "Data\library\songs\upgrade-song\02_vocal\separations\run-upgrade\htdemucs\upgrade-song\vocals.wav"),
    (Join-Path $managedStorageRoot "Data\models\catalog.json"),
    (Join-Path $managedStorageRoot "Output\exports\upgrade-mix.wav"),
    (Join-Path $managedStorageRoot "Runtime\rvc\weights\preserve-runtime-model.pth")
)
$managedHashes = @{}
foreach ($path in $managedFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Managed storage file was not created: $path"
    }
    $managedHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}
$managedUserHashes = $managedHashes.Clone()
$managedUserHashes.Remove((Join-Path $managedStorageRoot "Runtime\rvc\weights\preserve-runtime-model.pth"))

$env:QT_QPA_PLATFORM = "offscreen"
$installedExecutable = Join-Path $installDir "JJZero Audio.exe"
$smokeProcess = Start-Process `
    -FilePath $installedExecutable `
    -ArgumentList @("--startup-smoke-test") `
    -PassThru `
    -WindowStyle Hidden
if (-not $smokeProcess.WaitForExit(90000)) {
    $smokeProcess.Kill()
    throw "Updated application startup timed out after managed storage migration."
}
if ($smokeProcess.ExitCode -ne 0) {
    throw "Updated application failed after managed storage migration with exit code $($smokeProcess.ExitCode)."
}
Assert-PreservedFiles $managedHashes "updated application startup"

if ($RuntimePackageIndex) {
    $packageIndex = (Resolve-Path -LiteralPath $RuntimePackageIndex).Path
    & $python scripts\install_runtime_packages.py $packageIndex (Join-Path $installDir "runtime")
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime package installation failed with exit code $LASTEXITCODE"
    }
}
Invoke-DistributionVerification
Assert-PreservedFiles $immutableSourceFiles "runtime update"

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
$appMutex = [System.Threading.Mutex]::new($false, $AppMutexName)
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
if ($preservedModel.Count -lt 1 -or @(
    $preservedModel | Where-Object {
        (Get-Content -LiteralPath $_.FullName -Raw).Trim() -ne "preserve-runtime-model"
    }
).Count -ne 0) {
    throw "Runtime model was not preserved during uninstall: $preservedRuntimeRoot"
}
if ($preservedLog.Count -lt 1 -or @(
    $preservedLog | Where-Object {
        (Get-Content -LiteralPath $_.FullName -Raw).Trim() -ne "preserve-runtime-log"
    }
).Count -ne 0) {
    throw "Runtime logs were not preserved during uninstall: $preservedRuntimeRoot"
}
if ((Get-Content -LiteralPath $sentinel -Raw).Trim() -ne "preserve-user-data") {
    throw "User data was removed during uninstall: $sentinel"
}
Assert-PreservedFiles $immutableSourceFiles "uninstall"
Assert-PreservedFiles $managedUserHashes "uninstall"
if (Test-Path -LiteralPath (Join-Path $managedStorageRoot "Runtime")) {
    throw "Configured audio engine remained after uninstall: $managedStorageRoot"
}
if (Test-Path -LiteralPath (Join-Path $managedStorageRoot "Cache")) {
    throw "Configured cache remained after uninstall: $managedStorageRoot"
}

    Write-Output "Verified installer upgrade $baselineVersion -> $targetVersion and uninstall: $installer"
    if ($KeepArtifacts) {
        Write-Output "Verification logs: $testRoot"
    }
    else {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
        Write-Output "Removed installer verification files: $testRoot"
    }
}
finally {
    Remove-Item -LiteralPath $uninstallRegistryPsPath -Recurse -Force -ErrorAction SilentlyContinue
    if ($registrationExisted) {
        & reg.exe import $registryBackup *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not restore the previous JJZero Audio uninstall registration: $registryBackup"
        }
    }
    Remove-Item -LiteralPath $registryBackup -Force -ErrorAction SilentlyContinue
}
