param(
    [switch]$SkipTests,
    [switch]$SkipVerification
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = Join-Path $projectRoot "packaging\JJZeroAudio.spec"
$distribution = Join-Path $projectRoot "dist\JJZero Audio"
$runtimeSource = Join-Path $projectRoot "third_party"
$runtimeRoot = Join-Path $distribution "runtime"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}
foreach ($component in @("ffmpeg", "demucs", "rvc")) {
    $componentSource = Join-Path $runtimeSource $component
    if (-not (Test-Path -LiteralPath $componentSource -PathType Container)) {
        throw "Required runtime component was not found: $componentSource"
    }
}

Push-Location $projectRoot
try {
    if (-not $SkipTests) {
        & $python -m unittest discover -s tests -p "test_*.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed with exit code $LASTEXITCODE"
        }
    }

    & $python -m PyInstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    foreach ($component in @("ffmpeg", "demucs", "rvc")) {
        $componentSource = Join-Path $runtimeSource $component
        Copy-Item -LiteralPath $componentSource -Destination $runtimeRoot -Recurse -Force
    }
    if (-not $SkipVerification) {
        & $python scripts\verify_distribution.py $distribution
        if ($LASTEXITCODE -ne 0) {
            throw "Distribution verification failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}
