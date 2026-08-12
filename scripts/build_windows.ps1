param(
    [switch]$SkipTests,
    [switch]$SkipVerification
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = Join-Path $projectRoot "packaging\JJZeroAudio.spec"
$distribution = Join-Path $projectRoot "dist\JJZero Audio"
$versionScript = Join-Path $projectRoot "scripts\release_version.py"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}
Push-Location $projectRoot
try {
    & $python $versionScript "write-windows-info"
    if ($LASTEXITCODE -ne 0) {
        throw "Windows version metadata generation failed with exit code $LASTEXITCODE"
    }

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

    if (-not $SkipVerification) {
        & $python "scripts\verify_distribution.py" $distribution "--app-only"
        if ($LASTEXITCODE -ne 0) {
            throw "Distribution verification failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}
