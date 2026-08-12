param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9.-]{3,50}$')]
    [string]$IdentityName,
    [Parameter(Mandatory = $true)]
    [string]$Publisher,
    [string]$PublisherDisplayName = "JJZero",
    [string]$DisplayName = "JJZero Audio",
    [string]$PackageVersion = "",
    [switch]$SkipAppBuild,
    [switch]$SkipTests,
    [string]$CertificateThumbprint = $env:JJZERO_SIGN_CERT_THUMBPRINT,
    [string]$CertificatePath = $env:JJZERO_SIGN_CERT_PATH
)

$ErrorActionPreference = "Stop"

function Escape-XmlValue {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [Security.SecurityElement]::Escape($Value)
}

function Convert-ToStorePackageVersion {
    param([Parameter(Mandatory = $true)][string]$ApplicationVersion)

    if ($ApplicationVersion -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
        throw "Application version must use major.minor.patch: $ApplicationVersion"
    }
    $applicationMajor = [int]$Matches[1]
    $applicationMinor = [int]$Matches[2]
    $applicationPatch = [int]$Matches[3]
    $parts = @(($applicationMajor + 1), $applicationMinor, $applicationPatch, 0)
    if ($parts | Where-Object { $_ -lt 0 -or $_ -gt 65535 }) {
        throw "Application version cannot be represented as an MSIX version: $ApplicationVersion"
    }
    return ($parts -join '.')
}

function Assert-StorePackageVersion {
    param([Parameter(Mandatory = $true)][string]$Version)

    if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') {
        throw "MSIX version must use four numeric parts: $Version"
    }
    $parts = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [int]$Matches[4])
    if ($parts[0] -eq 0 -or $parts[3] -ne 0) {
        throw "Store MSIX version requires a non-zero first part and a zero fourth part: $Version"
    }
    if ($parts | Where-Object { $_ -lt 0 -or $_ -gt 65535 }) {
        throw "MSIX version parts must be between 0 and 65535: $Version"
    }
}

function Save-LogoAsset {
    param(
        [Parameter(Mandatory = $true)][Drawing.Bitmap]$Source,
        [Parameter(Mandatory = $true)][int]$Size,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $canvas = New-Object Drawing.Bitmap $Size, $Size
    $graphics = [Drawing.Graphics]::FromImage($canvas)
    try {
        $graphics.Clear([Drawing.Color]::Transparent)
        $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.DrawImage($Source, 0, 0, $Size, $Size)
        $canvas.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $canvas.Dispose()
    }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$applicationBuild = Join-Path $PSScriptRoot "build_windows.ps1"
$versionScript = Join-Path $PSScriptRoot "release_version.py"
$distribution = Join-Path $projectRoot "dist\JJZero Audio"
$templatePath = Join-Path $projectRoot "packaging\msix\AppxManifest.xml.in"
$iconPath = Join-Path $projectRoot "packaging\jjzero.ico"
$buildRoot = Join-Path $projectRoot "build\msix"
$stagingRoot = Join-Path $buildRoot "staging"
$releaseRoot = Join-Path $projectRoot "release\store"
$signScript = Join-Path $PSScriptRoot "sign_windows_artifact.ps1"
$verifyScript = Join-Path $PSScriptRoot "verify_msix_package.ps1"

if (-not $SkipAppBuild) {
    & $applicationBuild -SkipTests:$SkipTests
    if ($LASTEXITCODE -ne 0) {
        throw "Application build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $distribution "JJZero Audio.exe") -PathType Leaf)) {
    throw "Application distribution was not found: $distribution"
}

$applicationVersion = (& $python $versionScript "print").Trim()
if ($LASTEXITCODE -ne 0 -or -not $applicationVersion) {
    throw "Application version lookup failed with exit code $LASTEXITCODE"
}
$resolvedPackageVersion = if ($PackageVersion) {
    $PackageVersion
} else {
    Convert-ToStorePackageVersion $applicationVersion
}
Assert-StorePackageVersion $resolvedPackageVersion

$resolvedBuildRoot = [IO.Path]::GetFullPath($buildRoot)
$resolvedStagingRoot = [IO.Path]::GetFullPath($stagingRoot)
if (-not $resolvedStagingRoot.StartsWith($resolvedBuildRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "MSIX staging path escaped the build directory: $resolvedStagingRoot"
}
if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
Get-ChildItem -LiteralPath $distribution -Force |
    Where-Object { $_.Name -ne "runtime" } |
    Copy-Item -Destination $stagingRoot -Recurse -Force

@{
    channel = "store"
    application_updates = "microsoft-store"
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stagingRoot "distribution-channel.json") -Encoding ASCII

$manifestText = Get-Content -LiteralPath $templatePath -Raw
$replacements = @{
    '@@IDENTITY_NAME@@' = Escape-XmlValue $IdentityName
    '@@PUBLISHER@@' = Escape-XmlValue $Publisher
    '@@PACKAGE_VERSION@@' = Escape-XmlValue $resolvedPackageVersion
    '@@DISPLAY_NAME@@' = Escape-XmlValue $DisplayName
    '@@PUBLISHER_DISPLAY_NAME@@' = Escape-XmlValue $PublisherDisplayName
}
foreach ($replacement in $replacements.GetEnumerator()) {
    $manifestText = $manifestText.Replace($replacement.Key, $replacement.Value)
}
if ($manifestText.Contains('@@')) {
    throw "MSIX manifest contains unresolved template values."
}
$manifestText | Set-Content -LiteralPath (Join-Path $stagingRoot "AppxManifest.xml") -Encoding UTF8

Add-Type -AssemblyName System.Drawing
$assetsRoot = Join-Path $stagingRoot "Assets"
New-Item -ItemType Directory -Path $assetsRoot -Force | Out-Null
$icon = New-Object Drawing.Icon $iconPath
$sourceBitmap = $icon.ToBitmap()
try {
    Save-LogoAsset $sourceBitmap 44 (Join-Path $assetsRoot "Square44x44Logo.png")
    Save-LogoAsset $sourceBitmap 150 (Join-Path $assetsRoot "Square150x150Logo.png")
    Save-LogoAsset $sourceBitmap 50 (Join-Path $assetsRoot "StoreLogo.png")
}
finally {
    $sourceBitmap.Dispose()
    $icon.Dispose()
}

. (Join-Path $PSScriptRoot "windows_sdk_tools.ps1")
$makeAppx = Find-WindowsSdkTool "makeappx.exe"
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$packagePath = Join-Path $releaseRoot "JJZero-Audio-$applicationVersion-Store.msix"
& $makeAppx pack /d $stagingRoot /p $packagePath /o | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "MSIX packaging failed with exit code $LASTEXITCODE"
}

if ($CertificateThumbprint -or $CertificatePath) {
    & $signScript -ArtifactPath $packagePath `
        -CertificateThumbprint $CertificateThumbprint `
        -CertificatePath $CertificatePath
    if ($LASTEXITCODE -ne 0) {
        throw "MSIX signing failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Warning "The MSIX is unsigned and intended only for Store submission or structural verification."
}

& $verifyScript -PackagePath $packagePath `
    -ExpectedIdentityName $IdentityName `
    -ExpectedPublisher $Publisher `
    -ExpectedVersion $resolvedPackageVersion
if ($LASTEXITCODE -ne 0) {
    throw "MSIX verification failed with exit code $LASTEXITCODE"
}

Write-Output "JJZero Audio Store package created: $packagePath"
Write-Output "Application version: $applicationVersion"
Write-Output "MSIX package version: $resolvedPackageVersion"
