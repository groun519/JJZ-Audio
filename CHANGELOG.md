# Changelog

## 0.2.2 - 2026-08-06

### Added

- Added a non-blocking global update status button with active and inactive background polling.
- Added conditional GitHub Release manifest requests with ETag and Last-Modified caching, activation checks, and failure backoff without paid infrastructure.
- Added automatic NVIDIA generation detection and an independently downloadable Torch 2.7.1+cu128 RVC runtime profile for RTX 50-series GPUs.
- Added atomic profile installation, release manifest support, and package-content verification for the RTX 50-series runtime.
- Added vendor-neutral GPU inventory and runtime selection for NVIDIA CUDA, eligible AMD Windows ROCm candidates, AMD DirectML, and CPU systems.
- Added DirectML conversion support, CPU model-training fallback, and a separate Windows ROCm profile contract for AMD GPU training.
- Added versioned hardware diagnostics so existing installations revalidate once after an update without repeating media-storage setup.
- Added backend-aware training controls that expose CUDA or ROCm GPU selection and explicitly show CPU training on DirectML systems.
- Added a target-PC HIP/GPU forward activation probe and a single-process ROCm training compatibility layer without changing the source WebUI runtime.
- Opened experimental Windows ROCm model training after GPU forward validation so unsupported backward-pass failures produce complete task diagnostics instead of being hidden during setup.

### Fixed

- Detected RTX 50-series Blackwell GPUs before setup or update, installed the matching cu128 runtime, and blocked setup until its CUDA operation probe succeeds.
- Routed linked WebUI models, managed models, conversion, and training through the generation-matched JJZero runtime while retaining external model and index paths.
- Preserved the RVC child process output in conversion errors and copied its tail into diagnostic reports so GPU, model, and dependency failures no longer collapse into `UNEXPECTED_ERROR` without context.
- Classified unsupported CUDA architectures with the dedicated `CUDA_ARCHITECTURE_UNSUPPORTED` diagnostic code and applied the same compatibility gate to model training.
- Restored the configured workspace from first-run metadata when an update leaves `storage.json` missing or pointing at an empty location.
- Recovered legacy install-folder workspaces and settings in place so song packages and linked inference-only models remain visible after an update.
- Replaced persisted `cuda:0` preferences with backend-neutral `auto`, `gpu`, and `cpu` choices so imported models remain portable across GPU vendors.
- Removed the CUDA-only gate from RVC feature extraction and training; CPU runs disable half precision and GPU caching automatically.
- Attached GPU adapter, backend, desired profile, installed profile, and profile version to every structured task diagnostic report.
- Moved the reusable RVC device changes into a tracked, idempotent build overlay so release packages no longer depend on uncommitted `third_party` edits.
- Quarantined failed ROCm and DirectML profile versions until a newer runtime is published, with atomic fallback to DirectML or CPU and full activation details in diagnostics.

### Quality

- Added startup storage-origin logging and upgrade regression coverage with real song metadata, a model catalog, an external model link, and SHA-256 preservation checks through install, update, and uninstall.
- Added mocked NVIDIA, AMD ROCm, DirectML, CPU, profile migration, and CPU-training regression coverage; AMD GPU execution is validated on the target PC before profile activation.

## 0.2.1 - 2026-08-05

### Fixed

- Verified RVC CPU inference and FAISS independently from CUDA, with automatic CPU conversion fallback when CUDA is unavailable or fails its operation probe.
- Added actionable diagnostics for native Windows RVC crashes, including `0xC0000094` CPU runtime incompatibility.
- Repaired external RVC training script imports without modifying the source WebUI folder.
- Prevented incomplete checkpoint and spectrogram files from being treated as valid training artifacts.
- Reduced RVC training checkpoint and data-loader memory pressure and preserved the last valid model on stopped or failed runs.
- Kept the floating player and Vocal/Studio transport synchronized for every playback queue.
- Replaced the ambiguous video URL arrow with a state-aware link action and removed the empty original-URL control slot.
- Added explicit elapsed time, activity, stage, epoch, and queue updates while training.
- Added per-job diagnostic folders with structured events, command output, failure classification, and redacted copyable reports.
- Added session and task correlation to the rotating application log plus crash traces for unhandled native and thread failures.

### Quality

- Added regression coverage for CPU fallback, runtime diagnostics, training storage, spectrogram preparation, script launchers, playback navigation, training progress, and video URL controls.
- Isolated training tests from the host machine's current free-space level while retaining production disk preflight checks.
- Added automatic validation for every registered SVG application icon.
- Removed generated Python cache files from the Windows application payload and made installer verification support app-only updates, full runtime checks, and automatic temporary-file cleanup.
- Updated setup, runtime, feature, and Windows release documentation to match the current application.
- Verified the GitHub Releases update channel used by installed 0.2.0 clients and retained direct in-app download and hash verification for 0.2.1.
