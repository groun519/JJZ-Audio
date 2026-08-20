param(
    [switch]$Draft,
    [switch]$AllowUnsigned,
    [switch]$SkipTests
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

Push-Location $projectRoot
try {
    if (git status --porcelain) {
        throw "Commit all source changes before publishing a release."
    }
    & $readinessScript -AllowUnsigned:$AllowUnsigned -SkipTests:$SkipTests
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
        }
    }

    git rev-parse --verify --quiet "refs/tags/$tag" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        git tag -a $tag -m "JJZero Audio $version"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create release tag: $tag"
        }
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
}
finally {
    Pop-Location
}
