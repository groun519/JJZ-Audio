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
    & $python scripts\build_runtime_packages.py $runtimeRoot $releaseDir $runtimeVersion --part-limit $PartLimit
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime package build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Output "JJZero AI runtime packages complete: $releaseDir"
