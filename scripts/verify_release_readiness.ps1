param(
    [switch]$AllowUnsigned,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$releaseDir = Join-Path $projectRoot "release"
$distribution = Join-Path $projectRoot "dist\JJZero Audio"
$manifestPath = Join-Path $releaseDir "latest.json"

Push-Location $projectRoot
try {
    if (-not $SkipTests) {
        & $python -m unittest discover -s tests -p "test_*.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed with exit code $LASTEXITCODE"
        }
    }
    & $python scripts\verify_component_release.py $releaseDir $distribution
    if ($LASTEXITCODE -ne 0) {
        throw "Component release verification failed with exit code $LASTEXITCODE"
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $application = $manifest.components | Where-Object { $_.id -eq "application" }
    $installer = $application.artifacts | Select-Object -First 1
    if (-not $AllowUnsigned -and -not $installer.authenticode.required) {
        throw "Public releases require Authenticode metadata. Rebuild with -RequireCodeSigning."
    }

    if (-not $AllowUnsigned) {
        $publisher = [string]$installer.authenticode.publisher
        foreach ($path in @(
            (Join-Path $distribution "JJZero Audio.exe"),
            (Join-Path $releaseDir $installer.name)
        )) {
            $signature = Get-AuthenticodeSignature -LiteralPath $path
            if ($signature.Status -ne "Valid") {
                throw "Invalid Authenticode signature: $path ($($signature.Status))"
            }
            if (-not $signature.SignerCertificate.Subject.Contains($publisher)) {
                throw "Unexpected Authenticode publisher: $path"
            }
        }
    }
}
finally {
    Pop-Location
}

Write-Output "JJZero Audio release readiness verified: $manifestPath"
