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
    $assets = @($manifestPath, (Join-Path $releaseDir "runtime-packages.json"))
    $assets += Get-ChildItem -LiteralPath $releaseDir -Filter "rvc-runtime-*-packages.json" -File |
        Select-Object -ExpandProperty FullName
    foreach ($component in $manifest.components) {
        foreach ($artifact in $component.artifacts) {
            $assets += Join-Path $releaseDir $artifact.name
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
        "--generate-notes",
        "--latest"
    )
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
