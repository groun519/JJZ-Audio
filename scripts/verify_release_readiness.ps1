param(
    [switch]$SkipTests,

    [Parameter(Mandatory = $true)]
    [string]$PreviousInstallerPath,

    [string]$RuntimePackageIndex = "",

    [string]$SystemFootprintEvidencePath = ""
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
    $headRevision = (& git rev-parse --verify HEAD).Trim().ToLowerInvariant()
    $provenancePath = Join-Path $distribution "build-provenance.json"
    if (-not (Test-Path -LiteralPath $provenancePath -PathType Leaf)) {
        throw "Application build provenance is missing: $provenancePath"
    }
    $provenance = Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json
    if ([string]$manifest.source_revision -ne $headRevision -or
        [string]$provenance.source_revision -ne $headRevision -or
        [string]$provenance.version -ne [string]$manifest.version -or
        $provenance.source_dirty -ne $false) {
        throw "Release artifacts do not match the clean current source revision."
    }
    $componentIds = @($manifest.components | Select-Object -ExpandProperty id)
    foreach ($requiredProfile in @("cu128", "directml", "rocm-win")) {
        $componentId = "rvc-runtime-$requiredProfile"
        if ($componentId -notin $componentIds) {
            throw "Required RVC profile is missing from the release: $componentId"
        }
    }
    $application = $manifest.components | Where-Object { $_.id -eq "application" }
    $installer = $application.artifacts | Select-Object -First 1
    if (-not $installer.authenticode.required) {
        throw "Public releases require Authenticode metadata. Rebuild with -RequireCodeSigning."
    }

    $publisher = [string]$installer.authenticode.publisher
    $expectedCertificateSha256 = [string]$installer.authenticode.certificate_sha256
    if ($expectedCertificateSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Application certificate SHA-256 is missing from the manifest."
    }
    foreach ($path in @(
        (Join-Path $distribution "JJZero Audio.exe"),
        (Join-Path $releaseDir $installer.name)
    )) {
        $signature = Get-AuthenticodeSignature -LiteralPath $path
        if ($signature.Status -ne "Valid") {
            throw "Invalid Authenticode signature: $path ($($signature.Status))"
        }
        $subject = [string]$signature.SignerCertificate.Subject
        $simpleName = [string]$signature.SignerCertificate.GetNameInfo("SimpleName", $false)
        if (-not [String]::Equals($subject, $publisher, [StringComparison]::OrdinalIgnoreCase) -and
            -not [String]::Equals($simpleName, $publisher, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected Authenticode publisher: $path"
        }
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $actualCertificateSha256 = (($sha256.ComputeHash(
                $signature.SignerCertificate.RawData
            ) | ForEach-Object { $_.ToString("x2") }) -join "")
        }
        finally {
            $sha256.Dispose()
        }
        if (-not [String]::Equals(
            $actualCertificateSha256,
            $expectedCertificateSha256,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Unexpected Authenticode certificate: $path"
        }
    }

    $installationGateArguments = @{
        InstallerPath = Join-Path $releaseDir $installer.name
        PreviousInstallerPath = $PreviousInstallerPath
    }
    if ($RuntimePackageIndex) {
        $installationGateArguments.RuntimePackageIndex = $RuntimePackageIndex
    }
    if ($SystemFootprintEvidencePath) {
        $installationGateArguments.EvidencePath = $SystemFootprintEvidencePath
    }
    & (Join-Path $PSScriptRoot "verify_system_footprint.ps1") `
        @installationGateArguments
}
finally {
    Pop-Location
}

Write-Output "JJZero Audio release readiness verified: $manifestPath"
