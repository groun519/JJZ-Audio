# JJZero Audio

JJZero Audio is a local Windows desktop workspace for managing songs and RVC voice models, separating and converting vocals, mixing audio, and pairing a finished mix with video.

## Features

- Library: import local media or YouTube audio, search and sort songs, edit metadata, preview waveforms, and keep one working song available across pages.
- Vocal: separate vocals and instrumental stems with Demucs, configure RVC conversion, and retain multiple converted vocal versions.
- Models: create managed model packages, link or copy existing RVC folders, prepare and review training clips, reduce noise and silence, train or resume RVC models, and register finished weights and indexes.
- Studio: play synchronized original, instrumental, and converted tracks; adjust mute and volume from 0% to 200%; mix selected tracks; and attach local or YouTube video.
- Export: review output media and create final audio or video files.
- System: Korean and English UI, light and dark themes, persistent playback, processing queue, log drawer, first-run storage setup, and runtime diagnostics.

User media and models are stored outside the installation directory. Settings, logs, and cache are under `%LOCALAPPDATA%\JJZero Audio`; the selected media location contains `workspace` and `output`.

## Development Setup

Python 3.11 is required. Double-click `setup_jang.bat` to create or update `.venv`, or install manually:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Prepare the private runtime from an existing RVC WebUI installation. The source folder is read-only; personal `weights` and `logs` are not copied into the bundled runtime.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_runtime.py "C:\path\to\RVC"
```

The expected local runtime layout is:

```text
third_party/
  ffmpeg/bin/ffmpeg.exe
  ffmpeg/bin/ffprobe.exe
  demucs/
  rvc/runtime/python.exe
```

Run without a console using `run_jang_hidden.vbs`. For debug output, use `run_jang.bat` or:

```powershell
.\.venv\Scripts\python.exe -m jang_app
```

Runtime logs are written to `%LOCALAPPDATA%\JJZero Audio\logs\jang.log`.

## Runtime Behavior

First launch asks for a media storage location, installs or locates the AI runtime, and verifies write access, FFmpeg, Demucs, RVC assets, CPU inference, FAISS, and CUDA. The same diagnostics are available from Settings.

RVC conversion uses the selected CUDA device when its operation probe succeeds. If CUDA is missing or unusable but CPU inference is valid, conversion automatically falls back to CPU. RVC model training still requires a compatible NVIDIA CUDA device.

Existing RVC WebUI model folders can be linked in place or copied into a managed JJZero package. Linked folders remain externally owned; managed copies support dataset editing, checkpoint maintenance, continued training, and artifact registration.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Run one source-separation smoke test with:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_separate.py "C:\path\to\audio.m4a"
```

## Windows Release

Install the pinned build tools and Inno Setup once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Build and verify the app-only distribution:

```powershell
.\build_windows.bat
```

Build the installer while reusing the existing versioned AI runtime packages:

```powershell
.\build_release.bat -SkipRuntimeBuild
```

Build new runtime packages only when the runtime contents or `AI_RUNTIME_VERSION` change:

```powershell
.\build_release.bat
```

The application installer is small and preserves an installed runtime during updates. A new PC downloads the bounded runtime ZIP parts listed in `latest.json`, verifies every SHA-256 hash, and installs them atomically. Each release asset remains below GitHub Releases' 2 GiB file limit.

Installed builds check the public GitHub Release channel at startup. When a newer `latest.json` is published, the app offers a direct download, verifies file size, SHA-256, and any required Authenticode publisher, then launches the installer without a console window. Per-job support data is stored under `logs\jobs`; the Activity drawer can copy a redacted diagnostic report or open the selected job folder.

Verify an unsigned local release and an in-place upgrade from 0.2.0:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1 -AllowUnsigned
powershell -ExecutionPolicy Bypass -File scripts\verify_installer.ps1 `
  -PreviousInstallerPath release\JJZero-Audio-0.2.0-Setup.exe `
  -InstallerPath release\JJZero-Audio-0.2.1-Setup.exe
```

Public releases should be Authenticode-signed. Configure `JJZERO_SIGN_CERT_THUMBPRINT` or `JJZERO_SIGN_CERT_PATH`, set `JJZERO_SIGNING_PUBLISHER`, and build with `-RequireCodeSigning`. Publishing uses GitHub Releases and requires GitHub CLI authentication:

```powershell
.\build_release.bat -SkipRuntimeBuild -RequireCodeSigning
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1
powershell -ExecutionPolicy Bypass -File scripts\publish_github_release.ps1
```

The single application version source is `src\jang_app\version.py`. Windows metadata, installer names, update manifests, and release verification all read that value.
