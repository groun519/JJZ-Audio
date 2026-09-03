param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [ValidateSet("All", "Managed", "External")]
    [string]$Scenario = "All"
)

$ErrorActionPreference = "Stop"
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$testId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
$testRoot = [IO.Path]::GetFullPath((Join-Path $tempRoot "jjzero-storage-uninstall-$testId"))
if (-not $testRoot.StartsWith("$tempRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe verification root: $testRoot"
}

$uninstallRegistryKey = "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$uninstallRegistryPsPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$registryBackup = Join-Path $env:TEMP "jjzero-uninstall-registry-$testId.reg"
$registrationExisted = Test-Path -LiteralPath $uninstallRegistryPsPath
$dataRootExisted = Test-Path Env:JJZERO_DATA_ROOT
$previousDataRoot = $env:JJZERO_DATA_ROOT

function Assert-Exists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        throw "$Message`: $LiteralPath"
    }
}

function Assert-Removed {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (Test-Path -LiteralPath $LiteralPath) {
        throw "$Message`: $LiteralPath"
    }
}

function Invoke-NormalUninstallScenario {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Managed", "External")]
        [string]$Name
    )

    $scenarioRoot = Join-Path $testRoot $Name.ToLowerInvariant()
    $installRoot = Join-Path $scenarioRoot "app"
    $dataRoot = Join-Path $scenarioRoot "appdata"
    $storageRoot = Join-Path $scenarioRoot "storage"
    $workspaceRoot = Join-Path $storageRoot "Data"
    $outputRoot = Join-Path $storageRoot "Output"
    $appRuntimeRoot = Join-Path $installRoot "runtime"
    $defaultCacheRoot = Join-Path $dataRoot "cache"

    if ($Name -eq "Managed") {
        $runtimeRoot = $appRuntimeRoot
        $cacheRoot = $defaultCacheRoot
    }
    else {
        $runtimeRoot = Join-Path $storageRoot "Runtime"
        $cacheRoot = Join-Path $storageRoot "Cache"
    }

    New-Item -ItemType Directory -Path $scenarioRoot -Force | Out-Null
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
        throw "$Name installer failed with exit code $($install.ExitCode)."
    }

    New-Item -ItemType Directory -Path @(
        (Join-Path $dataRoot "settings"),
        (Join-Path $dataRoot "logs"),
        $workspaceRoot,
        $outputRoot,
        (Join-Path $runtimeRoot "rvc\weights"),
        (Join-Path $runtimeRoot "rvc\logs"),
        $cacheRoot
    ) -Force | Out-Null

    $dataSentinel = Join-Path $workspaceRoot "song.txt"
    $outputSentinel = Join-Path $outputRoot "mix.wav"
    $settingsSentinel = Join-Path $dataRoot "settings\bootstrap.txt"
    $logSentinel = Join-Path $dataRoot "logs\diagnostic.log"
    $weightSentinel = Join-Path $runtimeRoot "rvc\weights\voice.pth"
    $rvcLogSentinel = Join-Path $runtimeRoot "rvc\logs\train.log"
    $runtimeSentinel = Join-Path $runtimeRoot "generated.bin"
    $cacheSentinel = Join-Path $cacheRoot "package.zip"

    Set-Content -LiteralPath $dataSentinel -Value "song"
    Set-Content -LiteralPath $outputSentinel -Value "mix"
    Set-Content -LiteralPath $settingsSentinel -Value "settings"
    Set-Content -LiteralPath $logSentinel -Value "diagnostic"
    Set-Content -LiteralPath $weightSentinel -Value "voice"
    Set-Content -LiteralPath $rvcLogSentinel -Value "training-log"
    Set-Content -LiteralPath $runtimeSentinel -Value "runtime"
    Set-Content -LiteralPath $cacheSentinel -Value "cache"

    if ($Name -eq "External") {
        New-Item -ItemType Directory -Path $appRuntimeRoot -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $appRuntimeRoot "generated.bin") -Value "app-runtime"
    }

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
    $uninstallLog = Join-Path $scenarioRoot "uninstall.log"
    $uninstall = Start-Process `
        -FilePath $uninstaller `
        -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/LOG=`"$uninstallLog`""
        ) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($uninstall.ExitCode -ne 0) {
        throw "$Name uninstaller failed with exit code $($uninstall.ExitCode). Log: $uninstallLog"
    }

    Assert-Removed -LiteralPath (Join-Path $installRoot "JJZero Audio.exe") -Message "Application executable remained after uninstall"
    Assert-Removed -LiteralPath $appRuntimeRoot -Message "Application-owned Runtime remained after uninstall"
    Assert-Exists -LiteralPath $dataSentinel -Message "Data was removed during uninstall"
    Assert-Exists -LiteralPath $outputSentinel -Message "Output was removed during uninstall"
    Assert-Exists -LiteralPath $settingsSentinel -Message "Bootstrap settings were removed during uninstall"
    Assert-Exists -LiteralPath $logSentinel -Message "Diagnostic logs were removed during uninstall"

    if ($Name -eq "Managed") {
        Assert-Removed -LiteralPath $defaultCacheRoot -Message "Default managed Cache remained after uninstall"

        $preservedRoot = Join-Path $dataRoot "preserved-runtime"
        $preservedWeight = Get-ChildItem -LiteralPath $preservedRoot -Filter "voice.pth" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        $preservedLog = Get-ChildItem -LiteralPath $preservedRoot -Filter "train.log" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $preservedWeight -or (Get-Content -Raw -LiteralPath $preservedWeight.FullName).Trim() -ne "voice") {
            throw "Managed RVC weights were not preserved correctly: $preservedRoot"
        }
        if ($null -eq $preservedLog -or (Get-Content -Raw -LiteralPath $preservedLog.FullName).Trim() -ne "training-log") {
            throw "Managed RVC logs were not preserved correctly: $preservedRoot"
        }
    }
    else {
        Assert-Exists -LiteralPath $runtimeSentinel -Message "External Runtime was removed during uninstall"
        Assert-Exists -LiteralPath $cacheSentinel -Message "External Cache was removed during uninstall"
        Assert-Exists -LiteralPath $weightSentinel -Message "External RVC weights were removed during uninstall"
        Assert-Exists -LiteralPath $rvcLogSentinel -Message "External RVC logs were removed during uninstall"
    }

    Write-Output "Verified Normal Uninstall ($Name): $installer"
}

try {
    if ($registrationExisted) {
        & reg.exe export $uninstallRegistryKey $registryBackup /y *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not back up the existing uninstall registration."
        }
    }

    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $scenarios = if ($Scenario -eq "All") { @("Managed", "External") } else { @($Scenario) }
    foreach ($currentScenario in $scenarios) {
        Invoke-NormalUninstallScenario -Name $currentScenario
    }
}
finally {
    Remove-Item -LiteralPath $uninstallRegistryPsPath -Recurse -Force -ErrorAction SilentlyContinue
    if ($registrationExisted -and (Test-Path -LiteralPath $registryBackup)) {
        & reg.exe import $registryBackup *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not restore the previous uninstall registration."
        }
    }
    if ($dataRootExisted) {
        $env:JJZERO_DATA_ROOT = $previousDataRoot
    }
    else {
        Remove-Item Env:JJZERO_DATA_ROOT -ErrorAction SilentlyContinue
    }
    if ($testRoot.StartsWith("$tempRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $registryBackup -Force -ErrorAction SilentlyContinue
}
