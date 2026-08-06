param(
    [switch]$SkipAppBuild,
    [switch]$SkipTests,
    [switch]$RequireCodeSigning,
    [string]$SigningPublisher = $env:JJZERO_SIGNING_PUBLISHER,
    [string]$CertificateThumbprint = $env:JJZERO_SIGN_CERT_THUMBPRINT,
    [string]$CertificatePath = $env:JJZERO_SIGN_CERT_PATH,
    [string]$RuntimeReleaseTag = $env:JJZERO_RUNTIME_RELEASE_TAG
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
}

$manifestArguments = @("scripts\create_release_manifest.py", $releaseDir, $version)
if ($signingConfigured) {
    $manifestArguments += @("--signing-publisher", $SigningPublisher)
}
if ($RuntimeReleaseTag) {
    $manifestArguments += @("--runtime-release-tag", $RuntimeReleaseTag)
}
& $python @manifestArguments
if ($LASTEXITCODE -ne 0) {
    throw "Release manifest failed with exit code $LASTEXITCODE"
}

Write-Output "JJZero Audio installer build complete: $releaseDir"
