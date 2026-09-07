param(
    [switch]$Draft,
    [switch]$SkipTests,

    [Parameter(Mandatory = $true)]
    [string]$PreviousInstallerPath,

    [string]$RuntimePackageIndex = "",
    [string]$SystemFootprintEvidencePath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseDir = Join-Path $projectRoot "release"
$manifestPath = Join-Path $releaseDir "latest.json"
$readinessScript = Join-Path $PSScriptRoot "verify_release_readiness.ps1"
$gh = Get-Command gh.exe -ErrorAction SilentlyContinue
if (-not $gh) {
    throw "GitHub CLI is required. Install it with: winget install GitHub.cli"
}

function Get-Sha256Hex([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

Push-Location $projectRoot
try {
    if (git status --porcelain) {
        throw "Commit all source changes before publishing a release."
    }
    $previousInstaller = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
    $readinessArguments = @{
        SkipTests = $SkipTests
        PreviousInstallerPath = $previousInstaller
    }
    if ($RuntimePackageIndex) {
        $readinessArguments.RuntimePackageIndex = (Resolve-Path -LiteralPath $RuntimePackageIndex).Path
    }
    if ($SystemFootprintEvidencePath) {
        $readinessArguments.SystemFootprintEvidencePath = $SystemFootprintEvidencePath
    }
    & $readinessScript @readinessArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Release readiness verification failed with exit code $LASTEXITCODE"
    }
    & $gh.Source auth status
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run: gh auth login"
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $version = [string]$manifest.version
    $tag = "v$version"
    $headRevision = (& git rev-parse --verify HEAD).Trim().ToLowerInvariant()
    if ([string]$manifest.source_revision -ne $headRevision) {
        throw "Release manifest source revision does not match HEAD."
    }
    & git fetch origin main --tags
    if ($LASTEXITCODE -ne 0) {
        throw "Could not refresh origin/main and release tags."
    }
    $remoteRevision = (& git rev-parse --verify origin/main).Trim().ToLowerInvariant()
    if ($remoteRevision -ne $headRevision) {
        throw "Release source must be pushed first: HEAD does not match origin/main."
    }
    $assets = @($manifestPath)
    $remoteAssets = @{}
    foreach ($component in $manifest.components) {
        foreach ($artifact in $component.artifacts) {
            if (-not $artifact.url) {
                $assets += Join-Path $releaseDir $artifact.name
            }
            else {
                $url = [string]$artifact.url
                if ($url -notmatch '^https://github\.com/groun519/JJZ-Audio/releases/download/(?<tag>v\d+\.\d+\.\d+)/(?<asset>[^/?#]+)$') {
                    throw "Unsupported remote release asset URL: $url"
                }
                $remoteTag = $Matches.tag
                if (-not $remoteAssets.ContainsKey($remoteTag)) {
                    $remoteAssets[$remoteTag] = @()
                }
                $remoteAssets[$remoteTag] += [PSCustomObject]@{
                    Name = [Uri]::UnescapeDataString($Matches.asset)
                    Size = [Int64]$artifact.size
                    Sha256 = ([string]$artifact.sha256).ToLowerInvariant()
                }
            }
        }
    }
    $assets = $assets | Select-Object -Unique
    foreach ($asset in $assets) {
        if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
            throw "Release asset was not found: $asset"
        }
        if ((Get-Item -LiteralPath $asset).Length -ge 2GB) {
            throw "Release asset exceeds GitHub's 2 GiB limit: $asset"
        }
    }

    foreach ($remoteTag in $remoteAssets.Keys) {
        $remoteReleaseJson = & $gh.Source api "repos/groun519/JJZ-Audio/releases/tags/$remoteTag"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect reused runtime release: $remoteTag"
        }
        $remoteRelease = $remoteReleaseJson | ConvertFrom-Json
        foreach ($expected in $remoteAssets[$remoteTag]) {
            $published = @($remoteRelease.assets) | Where-Object {
                $_.name -eq $expected.Name -and [Int64]$_.size -eq $expected.Size
            } | Select-Object -First 1
            if (-not $published) {
                throw "Reused release asset is missing or has the wrong size: $remoteTag/$($expected.Name)"
            }
            $publishedDigest = ([string]$published.digest).ToLowerInvariant()
            if ($publishedDigest -ne "sha256:$($expected.Sha256)") {
                throw "Reused release asset digest does not match: $remoteTag/$($expected.Name)"
            }
        }
    }

    $existingTag = [string](& git rev-list -n 1 $tag 2>$null)
    $existingTag = $existingTag.Trim().ToLowerInvariant()
    if ($existingTag -and $existingTag -ne $headRevision) {
        throw "Existing release tag $tag does not point to current HEAD."
    }
    if (-not $existingTag) {
        git tag -a $tag -m "JJZero Audio $version"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create release tag: $tag"
        }
    }
    & $gh.Source release view $tag --json tagName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        throw "GitHub Release already exists and will not be overwritten: $tag"
    }
    git push origin $tag
    if ($LASTEXITCODE -ne 0) {
        throw "Could not push release tag: $tag"
    }

    $arguments = @(
        "release", "create", $tag,
        "--title", "JJZero Audio $version",
        "--latest"
    )
    $releaseNotes = Join-Path $projectRoot "docs\releases\$version.md"
    if (Test-Path -LiteralPath $releaseNotes -PathType Leaf) {
        $arguments += @("--notes-file", $releaseNotes)
    }
    else {
        $arguments += "--generate-notes"
    }
    if ($Draft) {
        $arguments += "--draft"
    }
    $arguments += $assets
    & $gh.Source @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub Release publishing failed with exit code $LASTEXITCODE"
    }

    $downloadRoot = Join-Path $env:TEMP ("jjzero-public-release-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $downloadRoot | Out-Null
    try {
        foreach ($asset in $assets) {
            $assetName = [IO.Path]::GetFileName($asset)
            & $gh.Source release download $tag --pattern $assetName --dir $downloadRoot
            if ($LASTEXITCODE -ne 0) {
                throw "Could not re-download published release asset: $assetName"
            }
            $downloaded = Join-Path $downloadRoot $assetName
            if (-not (Test-Path -LiteralPath $downloaded -PathType Leaf)) {
                throw "Published release asset was not downloaded: $assetName"
            }
            $local = (Resolve-Path -LiteralPath $asset).Path
            if ((Get-Item -LiteralPath $downloaded).Length -ne (Get-Item -LiteralPath $local).Length -or
                (Get-Sha256Hex $downloaded) -ne (Get-Sha256Hex $local)) {
                throw "Published release asset differs from the verified local artifact: $assetName"
            }
        }

        $downloadedInstaller = Join-Path $downloadRoot ([string]$installer.name)
        $downloadedSignature = Get-AuthenticodeSignature -LiteralPath $downloadedInstaller
        if ($downloadedSignature.Status -ne "Valid" -or -not $downloadedSignature.SignerCertificate) {
            throw "The re-downloaded installer has an invalid Authenticode signature."
        }
        if (-not $Draft) {
            $latestTag = (& $gh.Source api repos/groun519/JJZ-Audio/releases/latest --jq .tag_name).Trim()
            if ($LASTEXITCODE -ne 0 -or $latestTag -ne $tag) {
                throw "The public latest release does not point to $tag."
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $downloadRoot) {
            $resolvedDownloadRoot = [IO.Path]::GetFullPath($downloadRoot)
            $resolvedTemp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
            if (-not $resolvedDownloadRoot.StartsWith(
                "$resolvedTemp\jjzero-public-release-",
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Refusing to clean an unsafe release download path: $resolvedDownloadRoot"
            }
            Remove-Item -LiteralPath $resolvedDownloadRoot -Recurse -Force
        }
    }

    $remoteTagRevision = (& git ls-remote origin "refs/tags/$tag^{}" | ForEach-Object {
        ($_ -split "`t")[0]
    }).Trim().ToLowerInvariant()
    if ($remoteTagRevision -ne $headRevision) {
        throw "Published release tag does not resolve to the verified source revision."
    }
    Write-Output "GitHub Release published and independently re-downloaded: $tag"
}
finally {
    Pop-Location
}
