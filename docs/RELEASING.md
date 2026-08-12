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

Public releases should configure either a certificate thumbprint or a certificate file:

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
  -RuntimeReleaseTag vX.Y.Z
```

## Verify

Require valid Authenticode metadata and signatures for a public release:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1
```

Use `-AllowUnsigned` only for local verification builds. Readiness verification checks the test suite, distribution contents, component manifest, required acceleration profiles, artifact hashes, and signatures.

## Publish

Install and authenticate GitHub CLI once:

```powershell
winget install --id GitHub.cli --exact
gh auth login
```

Publish a verified release:

```powershell
.\scripts\publish_github_release.ps1
```

Use `-Draft` when the uploaded release requires manual inspection before becoming public. The publisher creates and pushes the version tag, uploads the installer, update manifest, and component archives, and marks the release as latest.

## Post-Release Check

1. Confirm that the setup executable and `latest.json` are attached to the release.
2. Install on a clean Windows user profile.
3. Verify first-run storage selection and runtime installation.
4. Verify in-app update discovery from the previous supported release.
5. Confirm that songs, models, projects, and outputs remain available after update.
6. Run uninstall verification and confirm that user data is retained as documented.
