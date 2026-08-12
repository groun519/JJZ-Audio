# Changelog

## Unreleased

## 0.3.1 - 2026-08-12

### Added

- Added clip-level Studio reverb with drag-and-drop assignment, reusable effect cards, non-destructive settings, and export rendering.
- Added real-time Studio effect processing so reverb, clip levels, and track levels can be heard immediately during playback.
- Added an update-center flow with release-note access, staged status feedback, and safe cleanup of completed update downloads.

### Changed

- Prepared Studio playback in the background and crossfaded structural timeline changes without resetting the playhead.
- Kept Library waveforms fixed while the work-song action reveals, and clarified first-run storage-location choices.
- Embedded the base RVC profile in the shared audio engine package to keep upgrades from older installations compatible.

### Fixed

- Repaired 0.2.x-to-0.3.x runtime upgrades that could fail while replacing the managed audio engine.
- Restored Precision Separation readiness checks when `audio_separator` is installed in either supported runtime location.
- Prevented repeated reverb editor tabs and removed playback stalls when effect parameters or clip positions change.
- Preserved reverb tails in exported mixes and kept Studio effect state compatible with existing project files.

### Quality

- Added regression coverage for real-time reverb, Studio playback preparation, effect persistence, update cleanup, runtime compatibility, and Library layout stability.

## 0.3.0 - 2026-08-12

### Added

- Added Fast, Precision, and Custom vocal-separation workflows, including independent vocal and instrumental model selection.
- Added reusable vocal and instrumental result pools with linked-pair and free-selection comparison modes.
- Added dedicated conversion input and RVC result pools with synchronized Original Vocal, Instrumental, and Converted Vocal monitoring.
- Added a Studio sound pool and non-destructive timeline for arranging, moving, splitting, trimming, muting, and mixing audio and video clips.
- Added a workspace-wide Space shortcut for play and pause while preserving text, numeric, combo, popup, and dialog input behavior.

### Changed

- Reorganized the production workflow into dedicated Separation, Conversion, Studio, and Export pages around one persistent work song.
- Upgraded the managed AI runtime for RoFormer separation assets and the refreshed CUDA 11.8 RVC profile.

### Fixed

- Preserved the separated vocal estimate during quality-mode mixture correction so residual accompaniment is not injected back into vocals.
- Prevented long Windows media paths from blocking RVC conversion by staging runtime work under a short managed path.
- Refreshed converted-vocal discovery so newly created takes appear in Conversion, Studio, and Library views without restarting the app.
- Scoped playback to the visible workspace while preserving the shared playhead when navigating between production pages.

## 0.2.8 - 2026-08-09

### Added

- Added a title-bar processing status button with task count and aggregate progress, plus an explicit right-side task drawer.
- Split the former Vocal workspace into dedicated Separation and Conversion pages while preserving one active work song and shared playback.
- Added Standard, High Quality, and Maximum Demucs recipes with explicit model, shift, overlap, float32, and post-processing settings.
- Upgraded Maximum separation to a sequential `htdemucs_ft` plus `htdemucs` ensemble with reproducible weights, float32 stem blending, and final mixture correction.
- Added persistent separation run metadata, active-run selection, legacy-result inference, optional model readiness and download-size feedback.
- Added reference-stem quality measurement for SI-SDR, clipping, and mixture residual so future engines and ensembles can be selected by repeatable evidence.
- Added synchronized per-track mute and 0-200% level controls to Separation and Conversion results using the same playback state as Studio.
- Added page-scoped playback: Separation monitors original vocal plus instrumental, Conversion compares original plus the selected converted take, and Studio plays the full sound pool without losing position during page changes.
- Added an always-visible converted-vocal selector with take, model, pitch, and creation-time context.
- Replaced the separation preset dropdown with an equal-width three-method selector and a stable detail panel for quality behavior, model requirements, and first-use download size.
- Added reusable saved-video selection in Studio and versioned application-session headers in diagnostic logs.

### Fixed

- Prevented the processing queue from opening automatically over workspace controls and kept it mutually exclusive with the log drawer.
- Preserved float32 stems in quality modes and optionally projected vocal and instrumental outputs back to the source mixture without changing their alignment.
- Moved Demucs execution, progress parsing, output discovery, and quality normalization behind a reusable separation-engine boundary.
- Aggregated Demucs bag-model and shift progress monotonically, retained only the final ensemble stems, and kept model downloads in the project-owned cache.
- Kept separation available after previous runs and let legacy output-only songs reconnect their original audio without losing existing results.
- Kept the active separation result selectable in a dedicated row, including a fallback when older library metadata omits the currently loaded result.
- Restored playback for 32-bit float separation stems, added assigned-source fallback playback, and removed premature child-widget shows that hid result selectors.
- Recovered RVC preprocessing when only a valid subset of training clips completes and recorded rejected inputs for diagnosis.
- Added compressed-audio waveform fallback decoding and stabilized hidden model-share slots and title-bar action sizing.

### Quality

- Added regression coverage for recipes, model assets, run manifests, quality metrics, stem consistency, float-WAV playback, result history, navigation, and legacy compatibility.

## 0.2.7 - 2026-08-08

### Fixed

- Improved Google OAuth compatibility and surfaced actionable authorization diagnostics in user job reports.
- Added application version, runtime profile, and hardware context to diagnostic bundles for remote issue analysis.

## 0.2.6 - 2026-08-07

### Added

- Added Google Drive account connection, model sharing, export sharing, shared-model import, and managed share deletion.
- Added NVIDIA CUDA, AMD ROCm/DirectML, and CPU runtime profiles with update-aware accelerator selection.
- Expanded model-material review with clip editing, denoising, keyboard decisions, and persistent review state.

### Fixed

- Hardened managed-storage migration, installer upgrades, uninstallation, path-length handling, and windowless helper execution.
- Removed stale playback surfaces and aligned Library, Model, Vocal, Studio, and Export workflow state.

## 0.2.5 - 2026-08-07

### Added

- Added guided model-training presets, inline setting explanations, dataset preflight checks, and failure recovery actions.
- Added clearer training activity, elapsed-time, stage, epoch, checkpoint, and remaining-time feedback with background task completion attention.
- Added reusable model-choice discovery so newly created or imported inference models become available for conversion without manual activation.
- Added keyboard-driven material review, persistent review decisions, safer zoom controls, and improved audio-preview preparation.
- Added generation-aware NVIDIA, AMD, and CPU runtime diagnostics with richer task reports for conversion and training failures.

### Fixed

- Prevented metadata, audio-preview, and RVC diagnostic helpers from flashing console windows when opening model and material pages.
- Preserved model-training artifacts and exposed resume or restart choices after interrupted and failed runs.
- Kept application playback controls synchronized while navigating between floating, Vocal, and Studio players.
- Replaced timestamp-only export names with song-based audio, video, and individual-track names while retaining collision-safe numbering.
- Prevented mouse-wheel changes on numeric controls and corrected shared button, slider, keyboard, and training-status interactions.

### Quality

- Added regression coverage for training presets, preflight, recovery, model discovery, task attention, preview conversion, export naming, windowless commands, and synchronized transport controls.
- Extended runtime and hardware diagnostics coverage across current and legacy NVIDIA GPUs, AMD backends, and CPU fallback.

## 0.2.4 - 2026-08-06

### Added

- Added one user-selected managed storage root containing `Data`, `Output`, `Runtime`, and `Cache`.
- Added verified storage migration with free-space checks, staged copies, path rebasing, and restart-safe activation.
- Added schema-based data migrations and a rebuildable shared catalog for song and model metadata.
- Added training-material analysis with pitch distribution, reference vocal ranges, usable range estimates, and conversion-pitch guidance.

### Fixed

- Preserved song packages, linked models, rendered output, downloaded runtimes, and cache when changing storage locations.
- Rebased legacy `@project/workspace` and `@project/output` references to the managed `Data` and `Output` layout.
- Prevented helper subprocesses from flashing console windows during metadata and model analysis.
- Reduced repeated audio metadata probing and simplified redundant Vocal result controls.

### Quality

- Added C-to-D managed-storage regression coverage including restart discovery and source-data preservation.
- Extended installer verification from `0.2.1` through managed-storage migration, packaged startup, and uninstall.

## 0.2.3 - 2026-08-06

### Added

- Added persistent conversion-take metadata for model, index, pitch, requested and effective device, F0 method, and creation time.
- Added synchronized original-versus-converted monitoring that changes live playback volumes without restarting the three-track queue or modifying the Studio mix.
- Added readable result names with rename, remove, reconvert, and file-location actions in the Vocal workspace.
- Added staged first-run diagnostics with explicit pending, running, install-required, skipped, warning, and failure states.
- Added byte-accurate download and expanded-install progress for audio engine provisioning.
- Added a five-stage model-training workflow, material readiness summary, resume/start-over controls, and epoch-based remaining-time feedback.

### Fixed

- Migrated existing vocal-project manifests without losing legacy results or user edits.
- Removed stale take records when converted files are deleted outside the application.
- Renamed first-run AI runtime language to audio engine terminology and skipped redundant GPU checks when the base runtime is unavailable.
- Reweighted model-training progress so the long-running epoch stage represents most of the visible completion range.
- Removed downloaded audio-engine files during uninstall while preserving legacy RVC weights and logs in the application data recovery folder.
- Blocked install or uninstall while JJZero Audio is running to prevent partially removed application files.
- Repaired missing JJZero RVC device adapters from the application bundle before diagnostics or training, without redownloading the multi-gigabyte audio engine.

### Quality

- Extended installer verification through a real uninstall with managed-runtime removal and model, log, settings, and library preservation checks.
- Reused unchanged runtime assets from the prior GitHub release so application-only updates do not republish multi-gigabyte packages.

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
