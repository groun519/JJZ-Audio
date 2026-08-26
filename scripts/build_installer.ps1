param(
    [switch]$SkipAppBuild,
    [switch]$SkipTests,
    [switch]$RequireCodeSigning,
    [string]$SigningPublisher = $env:JJZERO_SIGNING_PUBLISHER,
    [string]$CertificateThumbprint = $env:JJZERO_SIGN_CERT_THUMBPRINT,
    [string]$CertificatePath = $env:JJZERO_SIGN_CERT_PATH,
    [string]$RuntimeReleaseTag = $env:JJZERO_RUNTIME_RELEASE_TAG,
    [string]$RuntimeManifestPath = $env:JJZERO_RUNTIME_MANIFEST_PATH
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appBuild = Join-Path $projectRoot "scripts\build_windows.ps1"
$distribution = Join-Path $projectRoot "dist\JJZero Audio"
$installerScript = Join-Path $projectRoot "packaging\JJZeroAudio.iss"
$versionScript = Join-Path $projectRoot "scripts\release_version.py"
$releaseDir = Join-Path $projectRoot "release"
$signScript = Join-Path $projectRoot "scripts\sign_windows_artifact.ps1"
$provenancePath = Join-Path $distribution "build-provenance.json"
$version = (& $python $versionScript "print").Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) {
    throw "Release version lookup failed with exit code $LASTEXITCODE"
}

if (-not $SkipAppBuild) {
    & $appBuild -SkipTests:$SkipTests
    if ($LASTEXITCODE -ne 0) {
        throw "Application build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $distribution "JJZero Audio.exe") -PathType Leaf)) {
    throw "Application distribution was not found: $distribution"
}
if (-not (Test-Path -LiteralPath $provenancePath -PathType Leaf)) {
    throw "Application build provenance was not found: $provenancePath"
}
$provenance = Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json
$sourceRevision = (& git rev-parse --verify HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $sourceRevision -notmatch '^[0-9a-f]{40,64}$') {
    throw "Could not determine the current source revision."
}
if ($provenance.schema_version -ne 1 -or
    $provenance.product -ne "JJZero Audio" -or
    [string]$provenance.version -ne $version -or
    [string]$provenance.source_revision -ne $sourceRevision -or
    $provenance.source_dirty -ne $false) {
    throw "Application distribution does not match the clean current source revision. Rebuild it."
}
if (git status --porcelain --untracked-files=all) {
    throw "Commit all source changes before building a release installer."
}
$signingConfigured = [bool]($CertificateThumbprint -or $CertificatePath)
if ($RequireCodeSigning -and -not $signingConfigured) {
    throw "Code signing is required, but no certificate is configured."
}
if ($signingConfigured -and -not $SigningPublisher) {
    throw "JJZERO_SIGNING_PUBLISHER is required when code signing is enabled."
}
if ($signingConfigured) {
    & $signScript -ArtifactPath (Join-Path $distribution "JJZero Audio.exe") `
        -CertificateThumbprint $CertificateThumbprint -CertificatePath $CertificatePath
    if ($LASTEXITCODE -ne 0) {
        throw "Application signing failed with exit code $LASTEXITCODE"
    }
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

$installer = Join-Path $releaseDir "JJZero-Audio-$version-Setup.exe"
if ($signingConfigured) {
    & $signScript -ArtifactPath $installer -CertificateThumbprint $CertificateThumbprint `
        -CertificatePath $CertificatePath
    if ($LASTEXITCODE -ne 0) {
        throw "Installer signing failed with exit code $LASTEXITCODE"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne "Valid" -or -not $signature.SignerCertificate) {
        throw "Installer signature is not valid after signing."
    }
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $signingCertificateSha256 = (($sha256.ComputeHash(
            $signature.SignerCertificate.RawData
        ) | ForEach-Object { $_.ToString("x2") }) -join "")
    }
    finally {
        $sha256.Dispose()
    }
}

$manifestArguments = @(
    "scripts\create_release_manifest.py",
    $releaseDir,
    $version,
    "--source-revision",
    $sourceRevision
)
if ($signingConfigured) {
    $manifestArguments += @(
        "--signing-publisher", $SigningPublisher,
        "--signing-certificate-sha256", $signingCertificateSha256
    )
}
if ($RuntimeReleaseTag) {
    $manifestArguments += @("--runtime-release-tag", $RuntimeReleaseTag)
}
if ($RuntimeManifestPath) {
    $manifestArguments += @("--runtime-manifest", $RuntimeManifestPath)
}
& $python @manifestArguments
if ($LASTEXITCODE -ne 0) {
    throw "Release manifest failed with exit code $LASTEXITCODE"
}

Write-Output "JJZero Audio installer build complete: $releaseDir"
