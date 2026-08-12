# Windows Builds

[Back to README](../README.en.md) | [Development](DEVELOPMENT.md) | [Releasing](RELEASING.md)

## Build Tools

Prepare the development environment first, then install pinned Python build tools:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Install Inno Setup separately:

```powershell
winget install --id JRSoftware.InnoSetup --exact
```

The installer script accepts `ISCC.exe` from `PATH` or standard Inno Setup 6 and 7 installation locations.

## Application Distribution

Build and verify only the application distribution:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The PyInstaller output is written under `dist\JJZero Audio`.

## Full Component Build

After changing the managed audio runtime, RVC profiles, or packaged model assets, prepare the runtime sources and build every release component:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_runtime_profile.py
.\scripts\prepare_accelerator_profiles.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
```

The component build produces the application installer, runtime archives, acceleration profiles, and `release\latest.json`. Large assets are split below GitHub's 2 GiB per-file limit.

## Application-Only Build

Reuse compatible runtime assets from an existing GitHub release when only application code changed:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 `
  -SkipRuntimeBuild -RuntimeReleaseTag vX.Y.Z
```

The referenced release must contain every runtime component required by the generated manifest. Release verification checks component names, hashes, sizes, and profile coverage before publishing.

## Local Verification Build

Unsigned artifacts are acceptable for local verification only:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1 -AllowUnsigned
```

Public build requirements and publishing steps are documented in [Releasing](RELEASING.md).
