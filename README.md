# JJZero Audio

JJZero Audio is a local Windows desktop workspace for managing songs and RVC voice models, separating and converting vocals, mixing audio, and pairing a finished mix with video.

## Features

- Library: import local media or YouTube audio, search and sort songs, edit metadata, preview waveforms, and keep one working song available across pages.
- Separation: choose Standard, High Quality, or a sequential `htdemucs_ft + htdemucs` Maximum ensemble, retain multiple separation runs, and compare synchronized original-vocal and instrumental stems.
- Conversion: select an active separation result, configure RVC conversion, choose a converted take by model, pitch, and creation time, and compare it directly with the original vocal.
- Models: create managed model packages, link or copy existing RVC folders, prepare and review training clips, reduce noise and silence, train or resume RVC models, and register finished weights and indexes.
- Studio: play synchronized original, instrumental, and converted tracks; adjust mute and volume from 0% to 200%; mix selected tracks; and attach local or YouTube video.
- Export: review output media and create final audio or video files.
- System: Korean and English UI, light and dark themes, a shared transport that preserves position while changing workspace playback scope, processing queue, log drawer, first-run storage setup, and runtime diagnostics.

New installations keep large mutable content under one user-selected storage root: `Data`, `Output`, `Runtime`, and `Cache`. Small bootstrap settings and logs remain under `%LOCALAPPDATA%\JJZero Audio` so the app can locate that root.
Existing 0.2.x layouts remain readable in place. Choosing a storage location in Settings copies and verifies the old data before switching paths, keeps the source files as a recovery copy, and rebuilds the SQLite search catalog from package manifests.

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

First launch asks for a storage location, installs the audio engine there, and verifies write access, FFmpeg, Demucs, RVC assets, CPU inference, FAISS, and the selected GPU backend. The same diagnostics are available from Settings. Existing installations rerun only the system-check page when the diagnostics schema, GPU fingerprint, or installed runtime profile changes.

JJZero detects installed display adapters before runtime setup and updates. RTX 50-series Blackwell systems receive the Torch 2.7.1+cu128 profile, older NVIDIA systems use cu118, AMD cards in the pinned Windows ROCm compatibility matrix try `rocm-win`, and other AMD cards use DirectML for RVC inference. CPU remains available on every profile. DirectML systems train on CPU; ROCm candidates use the HIP-backed `torch.cuda` path after a target-PC GPU operation probe succeeds. Experimental ROCm training then runs normally so a backward-pass limitation is captured in the task diagnostics. A failed profile activation falls back atomically instead of replacing the working runtime. New preferences use `auto`, `gpu`, and `cpu` rather than storing a vendor-specific CUDA device.

Existing RVC WebUI model folders can be linked in place or copied into a managed JJZero package. Linked folders remain externally owned; managed copies support dataset editing, checkpoint maintenance, continued training, and artifact registration. Model and index files retain their original locations, but conversion and training always execute with JJZero's generation-matched managed runtime.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Run one source-separation smoke test with:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_separate.py "C:\path\to\audio.m4a"
```

Compare a separation result with known reference stems:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_separation.py reference-vocals.wav reference-instrumental.wav estimated-vocals.wav estimated-instrumental.wav --output separation-quality.json
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

When the RTX 50-series profile changes, prepare it from the unmodified base RVC runtime before building the release:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_runtime_profile.py
.\build_release.bat
```

Prepare the DirectML profile from the bundled Python 3.9 RVC runtime. Prepare the Windows ROCm profile from a complete Python 3.12 / PyTorch 2.9.1 / ROCm 7.2.1 runtime. Windows ROCm training remains experimental because AMD does not officially support ML training on Windows; JJZero intentionally allows the attempt after HIP/GPU forward validation and records the full failure if backward propagation is unavailable.

The DirectML profile owns `onnxruntime-directml` and `rmvpe.onnx`; these are excluded from the shared base runtime so non-AMD installations do not download the additional RMVPE model. Profile preparation fails if either the DirectML execution provider or model asset is missing.

Build both release profiles on the packaging PC with:

```powershell
.\scripts\prepare_accelerator_profiles.ps1
```

The ROCm builder creates its own Python 3.12 runtime from the pinned official Python and AMD wheels, so an AMD GPU is not required on the packaging PC. Release readiness requires `cu128`, `directml`, and `rocm-win` package components.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rvc_accelerator_profile.py directml third_party\rvc\runtime
.\.venv\Scripts\python.exe scripts\bootstrap_rvc_rocm_windows_runtime.py
.\build_release.bat
```

The ROCm builder cross-builds from pinned official packages and marks the result `required_on_install`. JJZero validates HIP, Torch, FAISS, Fairseq, Torchaudio, matrix multiplication, and 1D/2D convolutions on the target AMD PC before activation. Training is then available and any unsupported backward-pass failure is retained in the structured task log. A failed ROCm activation falls back to DirectML and then CPU without replacing user media or model data. The same failed profile version is not retried on every launch; publishing a newer profile version re-enables validation automatically.

`build_runtime_packages.ps1` applies the tracked device adapter in `src\jang_app\rvc_tools` to the project-owned RVC copy before packaging. It never edits an external WebUI installation, and it stops the release if the upstream RVC scripts no longer match the expected patch points.

The application installer is small and preserves an installed runtime during updates. A new PC downloads the bounded base runtime ZIP parts listed in `latest.json` plus the matching `cu128`, `directml`, or `rocm-win` profile when required. Every SHA-256 hash is verified and each runtime tree is installed atomically. Each release asset remains below GitHub Releases' 2 GiB file limit. The Windows ROCm profile is a complete Python 3.12 runtime; target-PC activation is mandatory and model training remains experimental on Windows.

Installed builds check the public GitHub Release channel at startup and continue with conditional background checks while the app is open. A newer release appears as a non-blocking lower-left update action; the app then offers a direct download, verifies file size, SHA-256, and any required Authenticode publisher, and launches the installer without a console window. Per-job support data is stored under `logs\jobs`; the Activity drawer can copy a redacted diagnostic report or open the selected job folder.

Verify an unsigned local release and an in-place upgrade from 0.2.1:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1 -AllowUnsigned
powershell -ExecutionPolicy Bypass -File scripts\verify_installer.ps1 `
  -PreviousInstallerPath release\JJZero-Audio-0.2.2-Setup.exe `
  -InstallerPath release\JJZero-Audio-0.2.5-Setup.exe `
  -RuntimePackageIndex release\runtime-packages.json
```

Public releases should be Authenticode-signed. Configure `JJZERO_SIGN_CERT_THUMBPRINT` or `JJZERO_SIGN_CERT_PATH`, set `JJZERO_SIGNING_PUBLISHER`, and build with `-RequireCodeSigning`. Publishing uses GitHub Releases and requires GitHub CLI authentication:

```powershell
.\scripts\build_release.ps1 -SkipRuntimeBuild -RequireCodeSigning `
  -RuntimeReleaseTag v0.2.2
powershell -ExecutionPolicy Bypass -File scripts\verify_release_readiness.ps1
powershell -ExecutionPolicy Bypass -File scripts\publish_github_release.ps1
```

`RuntimeReleaseTag` keeps unchanged runtime components linked to their original GitHub Release while publishing only the new application installer and manifest.

The single application version source is `src\jang_app\version.py`. Windows metadata, installer names, update manifests, and release verification all read that value.
