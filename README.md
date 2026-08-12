# JJZero Audio

JJZero Audio is a local-first Windows production app for the complete RVC cover workflow. It keeps songs, voice models, separation results, conversions, timeline edits, and exports in one managed workspace.

## Workflow

- **Library** imports local media or YouTube audio, searches and sorts songs, edits metadata, previews audio, and selects the active work song.
- **Models** links or copies existing RVC models, manages training material, reviews clips, analyzes datasets, trains or resumes models, and registers finished weights and indexes.
- **Separation** offers Fast, Precision, and Custom workflows, retains multiple runs, and previews synchronized vocal and instrumental stems.
- **Conversion** converts the active vocal stem with a selected RVC model and A/B compares multiple takes against the original vocal over the same instrumental.
- **Studio** provides audio and video pools plus a nondestructive timeline for arranging, splitting, trimming, moving, muting, and mixing clips.
- **Export** creates final audio or video files and keeps generated outputs attached to the source song.

The UI supports Korean and English, light and dark themes, background processing, structured diagnostics, and in-app updates.

## Platform And Acceleration

JJZero Audio targets Windows 10/11 x64. The installer does not require a separate Python installation.

| Hardware | RVC profile | Training |
| --- | --- | --- |
| NVIDIA RTX 50 series | CUDA 12.8 (`cu128`) | GPU |
| Other supported NVIDIA GPUs | CUDA 11.8 (`cu118`) | GPU |
| Supported AMD Windows ROCm systems | `rocm-win` | Experimental GPU |
| Other AMD GPUs | DirectML inference | CPU |
| No supported GPU | CPU fallback | CPU |

The first-run setup detects the display adapter and installs only the matching profile. Profile activation is validated before it replaces a working runtime; failed GPU activation falls back without changing user media or model data.

## Storage And Safety

The first-run setup asks for one storage root and creates:

```text
JJZero storage root/
  Data/       songs, model packages, manifests, and catalogs
  Output/     rendered audio and video
  Runtime/    FFmpeg, Demucs, RVC, and accelerator profiles
  Cache/      downloaded packages and regenerable data
```

Small bootstrap settings and logs remain under `%LOCALAPPDATA%\JJZero Audio` so the app can locate the selected root. Processing is nondestructive: imported source files and linked external RVC folders are not edited in place.

Existing 0.2.x storage layouts remain readable. Moving storage from Settings copies and verifies data before switching paths and leaves the previous data as a recovery copy.

## Download, Update, And Removal

### Download And Install

1. Open the [latest GitHub Release](https://github.com/groun519/JJZ-Audio/releases/latest).
2. Download `JJZero-Audio-X.Y.Z-Setup.exe`. The ZIP parts and `latest.json` on the same page are runtime/update assets, not manual installers.
3. Run the installer and launch JJZero Audio.
4. Choose a storage location during first-run setup and wait for the system check and matching AI runtime installation to finish.

### Update

JJZero Audio checks the public release channel after startup and periodically while it remains open. When an update is available:

1. Select the update button that appears in the lower-left corner.
2. Select **Download Update** and wait for the download and verification to finish.
3. Select **Restart and Install**. The app closes and starts the verified installer.

Application and runtime updates are versioned separately. A normal application update keeps an existing compatible runtime; only changed runtime components are downloaded. Song, model, Studio, and export data are migrated in place and do not require an intermediate app version.

If in-app updating is unavailable, download the latest setup executable from GitHub Releases and run it over the existing installation. Do not uninstall the previous version first.

### Remove The App

Open **Windows Settings > Apps > Installed apps** (**Apps & features** on older Windows 10), find **JJZero Audio**, and select **Uninstall**. If the Windows entry is unavailable, run `unins000.exe` from the JJZero Audio installation folder.

The normal uninstaller removes the application, generated AI runtime, and cache. It intentionally keeps:

- songs, managed models, Studio projects, and exports under the selected `Data` and `Output` locations;
- bootstrap settings and diagnostic logs under `%LOCALAPPDATA%\JJZero Audio`;
- personal RVC `weights` and `logs`, which are moved to `%LOCALAPPDATA%\JJZero Audio\preserved-runtime\<timestamp>` before a managed runtime is removed.

For a complete reset, uninstall first, back up anything needed, and then manually remove both the selected JJZero storage root and `%LOCALAPPDATA%\JJZero Audio`. This permanently deletes the remaining songs, models, exports, settings, logs, and preserved RVC files.

Runtime logs are stored under `%LOCALAPPDATA%\JJZero Audio\logs`. The Activity drawer can copy a redacted job report or open the detailed job folder.

## Developer Setup

Python 3.11 is required for source development. On the current NVIDIA-oriented development setup, run:

```powershell
.\setup_jang.bat
```

Manual equivalent:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-nvidia.txt
python -m pip install -r requirements.txt
```

Prepare the project-owned runtime from an existing RVC WebUI installation. The source folder is read-only; personal `weights` and `logs` are not copied.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_runtime.py "C:\path\to\RVC"
```

Expected local runtime layout:

```text
third_party/
  ffmpeg/bin/ffmpeg.exe
  ffmpeg/bin/ffprobe.exe
  demucs/
  rvc/runtime/python.exe
  rvc_profiles/
```

Run without a console using `run_jang_hidden.vbs`. Use `run_jang.bat` or the command below when debugging:

```powershell
.\.venv\Scripts\python.exe -m jang_app
```

## Verification

Run the complete test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Run one separation smoke test or compare estimated stems with references:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_separate.py "C:\path\to\audio.m4a"
.\.venv\Scripts\python.exe scripts\benchmark_separation.py `
  reference-vocals.wav reference-instrumental.wav `
  estimated-vocals.wav estimated-instrumental.wav `
  --output separation-quality.json
```

## Windows Release

Install pinned build tools and [Inno Setup](https://jrsoftware.org/isinfo.php) once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Build and verify only the application distribution:

```powershell
.\build_windows.bat
```

Build the installer and every runtime component after a runtime change:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_runtime_profile.py
.\scripts\prepare_accelerator_profiles.ps1
.\build_release.bat
```

Reuse runtime assets from an existing GitHub release for an application-only release:

```powershell
.\build_release.bat -SkipRuntimeBuild -RuntimeReleaseTag vX.Y.Z
```

Verify a local unsigned build, or require valid Authenticode signatures for a public build:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1 -AllowUnsigned
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1
```

Public releases should configure `JJZERO_SIGN_CERT_THUMBPRINT` or `JJZERO_SIGN_CERT_PATH` together with `JJZERO_SIGNING_PUBLISHER`, then build with `-RequireCodeSigning`. Publishing requires an authenticated GitHub CLI and a clean worktree:

```powershell
.\scripts\build_release.ps1 -SkipRuntimeBuild -RequireCodeSigning `
  -RuntimeReleaseTag vX.Y.Z
.\scripts\publish_github_release.ps1
```

Release assets are split below GitHub's 2 GiB limit and recorded in `release\latest.json`. The installer, updater, and verification scripts all use `src\jang_app\version.py` as the application version source.

## Project Layout

```text
src/jang_app/qt_app/     Qt UI and interaction controllers
src/jang_app/pipeline/   separation and conversion execution
src/jang_app/services/   reusable domain, storage, runtime, and media services
src/jang_app/rvc_tools/  scripts copied into managed RVC runtimes
scripts/                 development, verification, packaging, and release tools
packaging/               PyInstaller, Inno Setup, and MSIX definitions
tests/                   unit and UI regression tests
```
