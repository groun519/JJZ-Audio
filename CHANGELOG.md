# Changelog

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
