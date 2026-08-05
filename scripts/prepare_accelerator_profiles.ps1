$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$rvcRuntime = Join-Path $projectRoot "third_party\rvc\runtime"
$profileRoot = Join-Path $projectRoot "third_party\rvc_profiles"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $rvcRuntime "python.exe") -PathType Leaf)) {
    throw "Base RVC runtime was not found: $rvcRuntime"
}

Push-Location $projectRoot
try {
    & $python scripts\prepare_rvc_accelerator_profile.py directml $rvcRuntime `
        --destination (Join-Path $profileRoot "directml")
    if ($LASTEXITCODE -ne 0) {
        throw "DirectML profile preparation failed with exit code $LASTEXITCODE"
    }

    & $python scripts\bootstrap_rvc_rocm_windows_runtime.py `
        --destination (Join-Path $profileRoot "rocm-win")
    if ($LASTEXITCODE -ne 0) {
        throw "Windows ROCm profile preparation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Output "JJZero accelerator profiles complete: $profileRoot"
