param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$ExpectedIdentityName = "",
    [string]$ExpectedPublisher = "",
    [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "windows_sdk_tools.ps1")
$makeAppx = Find-WindowsSdkTool "makeappx.exe"
$package = (Resolve-Path -LiteralPath $PackagePath).Path
$temporaryRoot = [IO.Path]::GetFullPath(
    (Join-Path ([IO.Path]::GetTempPath()) ("jjzero-msix-verify-" + [Guid]::NewGuid().ToString("N")))
)
$systemTemporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if (-not $temporaryRoot.StartsWith($systemTemporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "MSIX verification path escaped the temporary directory: $temporaryRoot"
}

try {
    & $makeAppx unpack /p $package /d $temporaryRoot /o | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "MSIX unpack failed with exit code $LASTEXITCODE"
    }

    $manifestPath = Join-Path $temporaryRoot "AppxManifest.xml"
    $executablePath = Join-Path $temporaryRoot "JJZero Audio.exe"
    $channelPath = Join-Path $temporaryRoot "distribution-channel.json"
    foreach ($required in @($manifestPath, $executablePath, $channelPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required MSIX file is missing: $required"
        }
    }
    if (Test-Path -LiteralPath (Join-Path $temporaryRoot "runtime") -PathType Container) {
        throw "The Store package must not embed the optional AI runtime."
    }

    $channel = Get-Content -LiteralPath $channelPath -Raw | ConvertFrom-Json
    if ($channel.channel -ne "store") {
        throw "Invalid distribution channel in MSIX: $($channel.channel)"
    }

    [xml]$manifest = Get-Content -LiteralPath $manifestPath -Raw
    $identity = $manifest.Package.Identity
    if ($ExpectedIdentityName -and $identity.Name -ne $ExpectedIdentityName) {
        throw "Unexpected MSIX identity: $($identity.Name)"
    }
    if ($ExpectedPublisher -and $identity.Publisher -ne $ExpectedPublisher) {
        throw "Unexpected MSIX publisher: $($identity.Publisher)"
    }
    if ($ExpectedVersion -and $identity.Version -ne $ExpectedVersion) {
        throw "Unexpected MSIX version: $($identity.Version)"
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}

Write-Output "Verified Store MSIX package: $package"
