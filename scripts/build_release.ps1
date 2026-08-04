param(
    [switch]$SkipTests,
    [switch]$SkipRuntimeBuild,
    [switch]$SkipAppBuild,
    [switch]$RequireCodeSigning
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeBuild = Join-Path $PSScriptRoot "build_runtime_packages.ps1"
$installerBuild = Join-Path $PSScriptRoot "build_installer.ps1"

Push-Location $projectRoot
try {
    if (-not $SkipRuntimeBuild) {
        & $runtimeBuild
        if ($LASTEXITCODE -ne 0) {
            throw "Runtime package build failed with exit code $LASTEXITCODE"
        }
    }
    & $installerBuild -SkipTests:$SkipTests -SkipAppBuild:$SkipAppBuild `
        -RequireCodeSigning:$RequireCodeSigning
    if ($LASTEXITCODE -ne 0) {
        throw "Application installer build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Output "JJZero Audio component release complete: $(Join-Path $projectRoot 'release')"
