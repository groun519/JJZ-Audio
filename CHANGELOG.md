# Changelog

## Unreleased

## 0.3.7 - 2026-08-16

### Fixed

- Fixed single-device RVC training that could stall before the first batch when the training compatibility layer replaced DataLoader worker processes.
- Limited inline execution to the RVC rank process while preserving real windowless multiprocessing for DataLoader workers.

### Quality

- Added a bundled-runtime integration test that starts parallel DataLoader workers and verifies that a real first batch and worker diagnostics are produced.

## 0.3.6 - 2026-08-15

### Added

- Added safe import support for ordinary RVC ZIP packages containing inference `.pth` and optional `.index` files.
- Added a dedicated diagnostic classification for invalid or incomplete shared model packages.

### Changed

- Added the RVC root to child-process `PYTHONPATH` and ran the DirectML RMVPE probe from its prepared working directory.
- Required the DirectML runtime files used by RMVPE before accepting an AMD inference profile.

### Fixed

- Fixed in-app updates that closed JJZero Audio before the installer could replace the previous version.
- Allowed the verified internal `/RUN` update path to proceed while preserving running-app protection for manual installation and uninstall.
- Released and restored the Windows application mutex safely around installer startup failures.
- Accepted plain RVC model archives without weakening manifest validation, checksum checks, or archive path safety.
- Fixed AMD DirectML RMVPE imports when the probe workspace differs from the bundled RVC directory.

### Quality

- Added installer verification while the application mutex is active and regression coverage for update recovery, plain RVC ZIP import, and DirectML RMVPE bootstrapping.

## 0.3.5 - 2026-08-15

### Added

- Added a live RVC training monitor for GPU, VRAM, CPU, system-memory, worker, and throughput activity.
- Added a searchable live training log and one-click diagnostic archives for failed jobs.
- Added editable Studio Delay and Doubler effects with presets, real-time playback, saved sessions, and matching exports.
- Added a Karaoke vocal-effect chain that combines editable ambience and echo settings.

### Changed

- Reused cached song, model, output, Studio, and waveform metadata while still detecting files changed outside the app.
- Reused one Studio asset snapshot across loading, editing, autosave, playback, and export to avoid repeated output scans.
- Preserved registered RVC takes with custom filenames and recovered compatible legacy takes when metadata is missing or damaged.

### Fixed

- Retried RVC training with safe single-process data loading when parallel workers fail or time out before the first batch.
- Added structured worker and first-batch diagnostics so stalled training is distinguished from import, memory, and runtime failures.
- Staged the DirectML RMVPE probe model in its actual working directory before validating AMD conversion support.
- Preserved Delay and Doubler tails in real-time preview and final audio or video exports.
- Retried transient Windows file locks during atomic metadata saves.

### Quality

- Added regression coverage for training telemetry and diagnostics, Delay and Doubler processing, effect persistence, Studio asset reuse, output recovery, shared waveform caching, and Windows-safe metadata writes.

## 0.3.4 - 2026-08-14

### Added

- Added Quick Create to run Fast Separation and balanced RVC conversion from the Library, then open the completed result in Studio.
- Added non-destructive clip pitch controls in Studio with matching real-time playback, saved sessions, and exported audio.
- Added live training-performance details so CPU, CUDA, and AMD execution activity can be inspected while long jobs are running.

### Changed

- Kept Quick Create model and pitch choices compact while reusing existing separation results when they are already available.
- Improved RVC device probing and profile activation for DirectML, ROCm, CUDA, and CPU environments without replacing a known working profile prematurely.
- Moved long-running RVC and training subprocesses onto hidden, captured execution paths so background work does not flash command windows.

### Fixed

- Prevented stale update metadata from rejecting compatible application-only releases that reuse the existing AI runtime.
- Improved AMD and DirectML failure reporting so unavailable acceleration is distinguished from a conversion or training failure.
- Stabilized long-waveform rendering, Studio pitch playback, exported naming, and transient child-window ownership.

### Quality

- Added regression coverage for Quick Create, Studio pitch, hidden subprocess execution, AMD/DirectML probing, training performance, waveform rendering, and update compatibility.

## 0.3.3 - 2026-08-13

### Added

- Added precise model evaluation with a bundled reference vocal, pitch-shift analysis from -24 to +24 semitones, cached results, and recommended, clean, and usable ranges.
- Added complete model-work Google Drive packages that preserve training material, edited clips, analysis results, checkpoints, and inference artifacts.
- Added explicit work-conversion and work-output sessions so conversion inputs, generated takes, and output selection have stable owners.

### Changed

- Expanded model training status with live activity details, elapsed and remaining time, resume or restart recovery, and low-memory retry guidance.
- Kept the processing queue available when empty, expanded its active-task summary, and added direct navigation between queue and diagnostic logs.
- Added hover model deletion with confirmation and safe cleanup of JJZero-owned model files and training work.
- Checked Google Drive capacity before packaging and uploading, while reusing existing shares without duplicate work.

### Fixed

- Stabilized long-track RVC conversion with overlapping chunks, compact managed work paths, and collision-safe output names.
- Prevented inactive conversion jobs from replacing the current song's playback or selected take.
- Recovered missing feature-extraction outputs on CPU, preserved valid previous outputs, and retried CUDA out-of-memory training with a smaller batch.
- Kept ROCm training on the supported single-device path and prevented explicit DirectML requests from silently falling back to CPU.
- Corrected waveform remainder sampling so long waveforms and clip positions remain aligned with playback duration.
- Prevented dynamic queue and log widgets from appearing as unintended top-level windows.

### Quality

- Added regression coverage for model evaluation, training activity and recovery, model-work sharing, complete model deletion, long conversion, AMD device selection, queue navigation, waveform alignment, and output ownership.

## 0.3.2 - 2026-08-13

### Added

- Added a Studio media foundation that accepts images and video, places reusable media in the timeline, keeps preview playback synchronized, and renders the arranged result through FFmpeg.
- Added dedicated playback and work-song sessions so queue state, playhead position, resume positions, and the active production song have explicit owners outside the main window.
- Added Studio character effects for radio tone, ring modulation, bit reduction, distortion, and reusable multi-effect voice presets.
- Added Level Match so a converted vocal can follow the loudness movement of its original reference without replacing the converted tone.
- Added audio delivery presets for master WAV, lossless FLAC, high-quality MP3, Discord-sized Opus, and custom output settings.
- Added video delivery presets with explicit resolution, frame rate, quality, encoding-speed, and audio-bitrate controls.
- Added reusable RVC inference presets and controls for index rate, median filtering, envelope mix, and consonant protection.

### Changed

- Made the Studio sound pool more compact and added direct removal of managed sound assets without leaving the workspace.
- Centralized work-song routing and capability decisions so Separation, Conversion, Studio, and Export resolve the same active song consistently.
- Reorganized Export into dedicated audio and video workflows with one direct export action and inline output preview, rename, folder, and Drive-sharing actions.
- Expanded Studio effect editing with presets, plain-language control help, real-time parameter updates, and matching offline export processing.
- Clarified system diagnostics by reporting voice-conversion acceleration and model-training devices separately, including AMD DirectML conversion with CPU training.

### Fixed

- Prevented Studio sound cards and other composite widgets from briefly appearing as separate windows while pages are being constructed.
- Reused unchanged Studio sound cards instead of rebuilding every waveform card during page entry, removing the visible black-frame transition.
- Kept draggable Studio playheads, clips, splitters, and transport controls visually and behaviorally consistent across workspace layouts.
- Preserved shared-file state and progress directly on export rows and improved error details for Drive sharing and RVC conversion.

### Quality

- Documented the project responsibility model and added regression coverage for playback ownership, work-song restoration, Studio media, effects, level matching, sound-pool reuse, export formats, diagnostics, and video compatibility.

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
