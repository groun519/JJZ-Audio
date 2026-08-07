param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath
)

$ErrorActionPreference = "Stop"
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$testId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
$testRoot = [IO.Path]::GetFullPath((Join-Path $tempRoot "jjzero-storage-uninstall-$testId"))
if (-not $testRoot.StartsWith("$tempRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe verification root: $testRoot"
}

$installRoot = Join-Path $testRoot "app"
$dataRoot = Join-Path $testRoot "appdata"
$storageRoot = Join-Path $testRoot "storage"
$workspaceRoot = Join-Path $storageRoot "Data"
$outputRoot = Join-Path $storageRoot "Output"
$runtimeRoot = Join-Path $storageRoot "Runtime"
$cacheRoot = Join-Path $storageRoot "Cache"
$uninstallRegistryKey = "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$uninstallRegistryPsPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$registryBackup = Join-Path $env:TEMP "jjzero-uninstall-registry-$testId.reg"
$registrationExisted = Test-Path -LiteralPath $uninstallRegistryPsPath

try {
    if ($registrationExisted) {
        & reg.exe export $uninstallRegistryKey $registryBackup /y *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not back up the existing uninstall registration."
        }
    }

    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $install = Start-Process `
        -FilePath $installer `
        -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/DIR=`"$installRoot`""
        ) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($install.ExitCode -ne 0) {
        throw "Installer failed with exit code $($install.ExitCode)."
    }

    New-Item -ItemType Directory -Path @(
        (Join-Path $dataRoot "settings"),
        $workspaceRoot,
        $outputRoot,
        (Join-Path $runtimeRoot "rvc\weights"),
        (Join-Path $runtimeRoot "rvc\logs"),
        $cacheRoot
    ) -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $workspaceRoot "song.txt") -Value "song"
    Set-Content -LiteralPath (Join-Path $outputRoot "mix.wav") -Value "mix"
    Set-Content -LiteralPath (Join-Path $runtimeRoot "rvc\weights\voice.pth") -Value "voice"
    Set-Content -LiteralPath (Join-Path $runtimeRoot "rvc\logs\train.log") -Value "log"
    Set-Content -LiteralPath (Join-Path $runtimeRoot "generated.bin") -Value "runtime"
    Set-Content -LiteralPath (Join-Path $cacheRoot "package.zip") -Value "cache"

    $layout = @{
        version = 3
        mode = "linked"
        storage_root = $storageRoot
        workspace_root = $workspaceRoot
        workspace_anchor = $storageRoot
        output_root = $outputRoot
        runtime_root = $runtimeRoot
        cache_root = $cacheRoot
    } | ConvertTo-Json
    [IO.File]::WriteAllText(
        (Join-Path $dataRoot "settings\storage.json"),
        $layout,
        [Text.UTF8Encoding]::new($false)
    )

    $env:JJZERO_DATA_ROOT = $dataRoot
    $uninstaller = Join-Path $installRoot "unins000.exe"
    $uninstall = Start-Process `
        -FilePath $uninstaller `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($uninstall.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($uninstall.ExitCode)."
    }

    if (Test-Path -LiteralPath $runtimeRoot) {
        throw "Configured audio engine remained after uninstall: $runtimeRoot"
    }
    if (Test-Path -LiteralPath $cacheRoot) {
        throw "Configured cache remained after uninstall: $cacheRoot"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot "song.txt"))) {
        throw "Data was removed during uninstall."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $outputRoot "mix.wav"))) {
        throw "Output was removed during uninstall."
    }
    $preserved = @(
        Get-ChildItem -LiteralPath (Join-Path $dataRoot "preserved-runtime") -Recurse -File
    )
    if (-not ($preserved.Name -contains "voice.pth") -or
        -not ($preserved.Name -contains "train.log")) {
        throw "RVC weights or logs were not preserved during uninstall."
    }

    Write-Output "Verified v3 external Runtime/Cache uninstall cleanup: $installer"
}
finally {
    Remove-Item -LiteralPath $uninstallRegistryPsPath -Recurse -Force -ErrorAction SilentlyContinue
    if ($registrationExisted -and (Test-Path -LiteralPath $registryBackup)) {
        & reg.exe import $registryBackup *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not restore the previous uninstall registration."
        }
    }
    Remove-Item Env:JJZERO_DATA_ROOT -ErrorAction SilentlyContinue
    if ($testRoot.StartsWith("$tempRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $registryBackup -Force -ErrorAction SilentlyContinue
}
