# Releasing

[Back to README](../README.en.md) | [Windows Builds](BUILDING.md)

## Release Sources

- `src/jang_app/version.py` is the application version source.
- `src/jang_app/runtime_version.py` and the generated component metadata control runtime compatibility.
- `release/latest.json` is the update manifest consumed by the installer, updater, and verification tools.

Application and runtime components are versioned independently. An application-only release should reuse an existing compatible runtime instead of rebuilding and re-uploading unchanged large assets.

## Before Building

1. Set the intended application version.
2. Update `CHANGELOG.md`.
3. Run the complete test suite.
4. Confirm that every required runtime profile is available.
5. Commit source changes before publishing.

Publishing refuses to continue from a dirty worktree.

## Code Signing

Public releases must configure either a certificate thumbprint or a certificate file:

```powershell
$env:JJZERO_SIGN_CERT_THUMBPRINT = "CERTIFICATE_THUMBPRINT"
$env:JJZERO_SIGNING_PUBLISHER = "EXPECTED PUBLISHER"
```

Or:

```powershell
$env:JJZERO_SIGN_CERT_PATH = "C:\path\to\certificate.pfx"
$env:JJZERO_SIGN_CERT_PASSWORD = "certificate password"
$env:JJZERO_SIGNING_PUBLISHER = "EXPECTED PUBLISHER"
```

Do not commit certificate files, passwords, tokens, or generated signing material.

## Build

Build every runtime component after a runtime change:

```powershell
.\scripts\build_release.ps1 -RequireCodeSigning
```

Reuse runtime components from an existing release for an application-only update:

```powershell
.\scripts\build_release.ps1 -SkipRuntimeBuild -RequireCodeSigning `
  -RuntimeReleaseTag vX.Y.Z `
  -RuntimeManifestPath release\vX.Y.Z-latest.json
```

The reused manifest must be the published `latest.json` from the referenced release. Its component versions, artifact names, sizes, hashes, and release URLs are validated without downloading the multi-gigabyte archives again.

When the base RVC runtime changed but acceleration-profile dependencies did not, increment `AI_RUNTIME_VERSION`, build the base runtime, and reuse the unchanged profiles:

```powershell
.\scripts\build_release.ps1 -SkipRuntimeProfileBuild -RequireCodeSigning `
  -RuntimeManifestPath release\vPREVIOUS-latest.json
```

The prior manifest's immutable URLs are preserved. Within the changed base runtime,
archives with identical size, unpacked size, file count, and SHA-256 are also reused;
only changed archives are uploaded under the new release. `-RuntimeReleaseTag` is a
fallback for legacy manifests without artifact URLs, not the new release tag.

The installer and manifest are locked to their build source revision. A later release
finalization commit may change only `docs/releases/<version>-preflight.md` and
`docs/plans/<version>.md`; the publisher rejects any other post-build source change.

## Verify

Require valid Authenticode metadata and signatures for a public release:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1 `
  -PreviousInstallerPath release\JJZero-Audio-PREVIOUS-Setup.exe `
  -SystemFootprintEvidencePath build\verification\system-footprint.json
```

There is no unsigned public-release bypass. Readiness verification checks the test
suite, distribution contents, component manifest, required acceleration profiles,
artifact hashes, source provenance, and the pinned signing-certificate SHA-256.

## Publish

Install and authenticate GitHub CLI once:

```powershell
winget install --id GitHub.cli --exact
gh auth login
```

Publish a verified release:

```powershell
.\scripts\publish_github_release.ps1 `
  -PreviousInstallerPath release\JJZero-Audio-PREVIOUS-Setup.exe `
  -SystemFootprintEvidencePath build\verification\system-footprint.json
```

Use `-Draft` when the uploaded release requires manual inspection before becoming public. The publisher requires `HEAD` to match `origin/main`, creates and pushes the version tag without replacing an existing release, uploads the installer, update manifest, and changed component archives, then downloads every uploaded asset again and verifies its size, SHA-256, installer signature, tag revision, and latest-release status.

## Post-Release Check

1. Confirm that the setup executable and `latest.json` are attached to the release.
2. Install on a clean Windows user profile.
3. Verify first-run storage selection and runtime installation.
4. Verify in-app update discovery from the previous supported release.
5. Confirm that songs, models, projects, and outputs remain available after update.
6. Run uninstall verification and confirm that user data is retained as documented.
