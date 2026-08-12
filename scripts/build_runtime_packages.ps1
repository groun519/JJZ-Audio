param(
    [long]$PartLimit = 1782579200
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimeRoot = Join-Path $projectRoot "third_party"
$releaseDir = Join-Path $projectRoot "release"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}
foreach ($component in @("ffmpeg", "demucs", "rvc")) {
    $componentSource = Join-Path $runtimeRoot $component
    if (-not (Test-Path -LiteralPath $componentSource -PathType Container)) {
        throw "Required runtime component was not found: $componentSource"
    }
}

$runtimeVersion = (& $python -c "from jang_app.runtime_version import AI_RUNTIME_VERSION; print(AI_RUNTIME_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $runtimeVersion) {
    throw "AI runtime version lookup failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Get-ChildItem -LiteralPath $releaseDir -Filter "JJZero-Runtime-$runtimeVersion-part*.zip" -File |
    Remove-Item -Force

Push-Location $projectRoot
try {
    & $python scripts\patch_rvc_runtime.py (Join-Path $runtimeRoot "rvc")
    if ($LASTEXITCODE -ne 0) {
        throw "RVC runtime patching failed with exit code $LASTEXITCODE"
    }
    & $python scripts\build_runtime_packages.py $runtimeRoot $releaseDir $runtimeVersion --part-limit $PartLimit
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime package build failed with exit code $LASTEXITCODE"
    }

    $profileVersions = & $python -c "import json; from jang_app.runtime_version import RVC_RUNTIME_PROFILE_VERSIONS; print(json.dumps(RVC_RUNTIME_PROFILE_VERSIONS))" | ConvertFrom-Json
    $precisionProfileRoots = @(
        $profileVersions.PSObject.Properties.Name |
            Where-Object { $_ -ne "cu118" } |
            ForEach-Object { Join-Path $runtimeRoot "rvc_profiles\$_" }
    )
    & $python scripts\sync_rvc_precision_packages.py @precisionProfileRoots
    if ($LASTEXITCODE -ne 0) {
        throw "RVC precision runtime synchronization failed with exit code $LASTEXITCODE"
    }
    foreach ($profile in $profileVersions.PSObject.Properties.Name) {
        $profileRoot = if ($profile -eq "cu118") {
            Join-Path $runtimeRoot "rvc\runtime"
        }
        else {
            Join-Path $runtimeRoot "rvc_profiles\$profile"
        }
        if (-not (Test-Path -LiteralPath $profileRoot -PathType Container)) {
            throw "Required RVC $profile runtime profile was not found: $profileRoot"
        }
        $profileVersion = [string]$profileVersions.$profile
        Get-ChildItem -LiteralPath $releaseDir -Filter "JJZero-RVC-$profile-$profileVersion-part*.zip" -File |
            Remove-Item -Force
        & $python scripts\build_runtime_packages.py $profileRoot $releaseDir $profileVersion `
            --part-limit $PartLimit `
            --component "rvc-runtime-$profile" `
            --package-prefix "JJZero-RVC-$profile-$profileVersion" `
            --index-name "rvc-runtime-$profile-packages.json" `
            --exclude-directory "__pycache__" `
            --exclude-suffix ".map"
        if ($LASTEXITCODE -ne 0) {
            throw "RVC $profile runtime package build failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}

Write-Output "JJZero AI runtime packages complete: $releaseDir"
