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

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Demucs requires FFmpeg tools to decode many audio formats. Put `ffmpeg.exe` and `ffprobe.exe` under `third_party\ffmpeg\bin`, install FFmpeg globally, or place them on `PATH` before running the app.

## Run

Double-click `run_jang_hidden.vbs` to start without showing a CMD window.

For setup/debug output, double-click `run_jang.bat`, or run manually:

```powershell
python -m jang_app
```

Or:

```powershell
jang-audio
```

Outputs are written under `output\separations` by default.

Runtime logs are written to `logs\jang.log`.
Local settings are written to `settings\app_settings.json`.

RVC settings are configured from the app settings dialog:

- `RVC root`: local RVC folder that contains `runtime\python.exe` and `infer_cli.py`.
- `Voice model`: `.pth` file under the RVC `weights` folder.
- `Index file`: optional `.index` file under the RVC `logs` folder.
- `F0 method`: fixed to `rmvpe`.

## Smoke Test

```powershell
python scripts\smoke_separate.py "C:\path\to\audio.m4a"
```
