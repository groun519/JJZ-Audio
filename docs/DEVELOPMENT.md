# Development

[한국어 README](../README.md) | [English README](../README.en.md)

## Prerequisites

- Windows 10 or 11 x64
- Python 3.11
- An existing RVC WebUI installation when preparing a local RVC development runtime

## Environment Setup

The NVIDIA-oriented development setup can be prepared with:

```powershell
.\scripts\commands\setup_jang.bat
```

Manual equivalent:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-nvidia.txt
python -m pip install -r requirements.txt
```

Prepare the project-owned runtime from an existing RVC WebUI installation. The source directory is treated as read-only, and personal `weights` and `logs` are not copied.

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

Generated runtimes, downloaded models, caches, and personal media must remain outside version control.

## Running the App

Run without a console using:

```powershell
.\scripts\commands\run_jang_hidden.vbs
```

Use the console launcher or Python module when debugging:

```powershell
.\scripts\commands\run_jang.bat
.\.venv\Scripts\python.exe -m jang_app
```

## Verification

Run the complete test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Run a separation smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_separate.py "C:\path\to\audio.m4a"
```

Compare estimated stems with references:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_separation.py `
  reference-vocals.wav reference-instrumental.wav `
  estimated-vocals.wav estimated-instrumental.wav `
  --output separation-quality.json
```

## Project Layout

```text
src/jang_app/qt_app/     Qt UI and interaction controllers
src/jang_app/pipeline/   separation and conversion execution
src/jang_app/services/   reusable domain, storage, runtime, and media services
src/jang_app/rvc_tools/  scripts copied into managed RVC runtimes
scripts/                 development, verification, packaging, and release tools
packaging/               PyInstaller, Inno Setup, and MSIX definitions
tests/                   unit and UI regression tests
docs/                    user, development, release, and research documents
```

Keep reusable behavior in `services` or a focused shared widget instead of duplicating it in page controllers. UI modules should coordinate interactions; subprocess, storage, media, and model logic should remain independently testable.
