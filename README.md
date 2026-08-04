# Jang

Local desktop tool for audio processing workflows.

## Current Scope

The app currently provides a minimal desktop interface for audio source separation and first-pass RVC vocal conversion:

1. Select one local audio file.
2. Run Demucs two-stem separation.
3. Produce `vocals.wav` and `no_vocals.wav`.
4. Convert `vocals.wav` through an RVC voice model with `rmvpe`.

Mixing, video replacement, packaging, and link downloading are intentionally out of scope for this step.

## Setup

Python 3.11 is recommended.

The current Windows build targets NVIDIA GPUs and installs the CUDA 12.6
PyTorch runtime pinned in `requirements-nvidia.txt`.

Double-click `setup_jang.bat` to create or update the development environment. Setup is separate from normal app startup, so dependencies are not checked and installed on every launch.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Demucs requires FFmpeg tools to decode many audio formats. Put `ffmpeg.exe` and `ffprobe.exe` under `third_party\ffmpeg\bin`, install FFmpeg globally, or place them on `PATH` before running the app.

## Run

Double-click `run_jang_hidden.vbs` to start without showing a CMD window.

For debug output, double-click `run_jang.bat`, or run manually:

```powershell
python -m jang_app
```

Or:

```powershell
jang-audio
```

## Windows Build

Install the pinned build tools once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Prepare a private runtime copy from an existing RVC WebUI installation. This
copies the inference engine only; it never edits the source folder and does not
copy personal `weights` or `logs` model data.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_runtime.py "C:\path\to\RVC"
```

Build and verify the `onedir` distribution:

```powershell
.\build_windows.bat
```

The verified application is created under `dist\JJZero Audio`. FFmpeg, the
Demucs model, and the shared CUDA RVC/Demucs runtime are bundled under its
`runtime` folder without duplicating PyTorch.

Build the versioned Windows installer after installing Inno Setup:

```powershell
.\build_installer.bat -SkipAppBuild
```

Installer files and their SHA-256 update manifest are created under `release`.

Verify clean install, in-place update, and uninstall data preservation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_installer.ps1 `
  -InstallerPath release\JJZero-Audio-0.1.0-Setup.exe
```

Outputs are written under `output\separations` by default.

Runtime logs are written to `%LOCALAPPDATA%\JJZero Audio\logs\jang.log`.
Each launch writes cumulative startup timing marks to the runtime log.
Local settings are written under `%LOCALAPPDATA%\JJZero Audio\settings`.
Existing development workspaces are linked in place during the first migration and are not moved or deleted.

Installed builds use the bundled RVC runtime by default. An existing WebUI root
can still be selected or imported when its own runtime and models should be used:

- `RVC root`: local RVC folder that contains `runtime\python.exe` and `infer_cli.py`.
- `Voice model`: `.pth` file under the RVC `weights` folder.
- `Index file`: optional `.index` file under the RVC `logs` folder.
- `F0 method`: fixed to `rmvpe`.

## Smoke Test

```powershell
python scripts\smoke_separate.py "C:\path\to\audio.m4a"
```
