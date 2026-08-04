param(
    [switch]$SkipAppBuild,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appBuild = Join-Path $projectRoot "scripts\build_windows.ps1"
$distribution = Join-Path $projectRoot "dist\JJZero Audio"
$installerScript = Join-Path $projectRoot "packaging\JJZeroAudio.iss"
$versionFile = Join-Path $projectRoot "packaging\version.txt"
$releaseDir = Join-Path $projectRoot "release"
$version = (Get-Content -LiteralPath $versionFile -Raw).Trim()

if (-not $SkipAppBuild) {
    & $appBuild -SkipTests:$SkipTests
    if ($LASTEXITCODE -ne 0) {
        throw "Application build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $distribution "JJZero Audio.exe") -PathType Leaf)) {
    throw "Application distribution was not found: $distribution"
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
    throw "Inno Setup compiler was not found. Install JRSoftware.InnoSetup with winget."
}

New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
& $compiler "/DAppVersion=$version" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE"
}

& $python scripts\create_release_manifest.py $releaseDir $version
if ($LASTEXITCODE -ne 0) {
    throw "Release manifest failed with exit code $LASTEXITCODE"
}

Write-Output "JJZero Audio installer build complete: $releaseDir"
