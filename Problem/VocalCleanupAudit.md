# Vocal Cleanup and Audio Pipeline Audit

## Session status

- Status: investigating
- Started: 2026-08-23 23:07 KST
- Scope: vocal cleanup, separation post-processing, managed model assets,
  preview/apply consistency, audio format preservation, and cleanup UX
- Main.md lock: not held

## Method

A confirmed finding must include a reproducible trigger, concrete code or runtime
evidence, user impact, and a verification result. Unverified concerns remain under
Candidates and are not copied to `Main.md`.

## Confirmed findings

### VC-01 - Existing cleanup regions cannot be edited or processed by another tool

- Severity: high
- Trigger: add a cleanup region, activate it in the timeline, then request a new
  preview for the same range (for example, apply noise removal after dereverb).
- Evidence:
  - `VocalCleanupWorkspace._on_region_activated()` only restores the range. The
    preview signal has no region identity or edit mode.
  - `MainWindow._start_vocal_cleanup_preview()` always passes every saved region
    to `preview_vocal_cleanup()`.
  - `preview_vocal_cleanup()` rejects any overlap before an effect renderer runs.
  - Direct reproduction returned `VocalCleanupError: The selected range overlaps
    another cleanup region.` before decoding the source audio.
  - Repository search found `replace_region_id` only in the store API and tests;
    the application flow never supplies it.
- Impact: a user cannot adjust the tool or strength of an accepted region and
  cannot chain dereverb, de-echo, and denoise on the same defective phrase. The
  only workaround is destructive delete-and-recreate, which also prevents a
  useful ordered cleanup workflow.
- Verification: reproduced with one synthetic `VocalCleanupRegion` covering
  `1000-2000 ms` and a denoise preview request for the same interval.
- Recommended direction: represent an explicit selected-region edit or an
  ordered operation chain. Exclude the edited region from overlap validation,
  pass its ID through preview/commit, and keep arbitrary overlapping regions
  prohibited unless they belong to a deterministic chain.

### VC-02 - A failed region replacement can destroy the previously committed audio

- Severity: critical latent data-loss bug
- Trigger: call `import_preview(..., replace_region_id=<existing>)` and let the
  manifest save fail after the replacement files have been copied.
- Evidence:
  - Replacement reuses the existing `region_id`, so `_copy_file()` replaces the
    currently committed `*-processed.wav` and `*-removed.wav` files in place.
  - The exception handler then unlinks those same targets.
  - The old manifest remains unchanged and still points to the deleted files.
  - A fault-injection reproduction reported one restored manifest region while
    both `processed_exists` and `removed_exists` were `False`.
- Impact: exposing the currently dormant edit API would make a transient disk,
  permission, serialization, or validation failure corrupt a valid cleanup
  project and lose the user's accepted segment audio.
- Verification: created a committed region, injected a `save()` failure during
  replacement, then reloaded the untouched manifest and checked both paths.
- Recommended direction: write replacement media to unique transaction paths,
  atomically commit the manifest, then remove the old media. Never overwrite or
  delete files referenced by the active manifest before commit succeeds.

### VC-03 - Truncated managed model files are displayed as ready

- Severity: high
- Trigger: leave a partial or corrupt managed RoFormer checkpoint at the expected
  filename, then open a model-backed cleanup tool.
- Evidence:
  - `separation_asset_status()` counts files using only `Path.is_file()` and does
    not compare the registered size or integrity metadata.
  - A one-byte file named as `UVR-De-Echo-Normal.pth` was reported as `ready=True`,
    `present_files=1`, and `missing_bytes=0`, despite its registered size being
    `127,139,365` bytes.
  - Preparation itself checks existing files with `_file_has_size()` only. A
    same-size corrupt checkpoint (`BADD` instead of registered `GOOD`) produced
    zero download calls and was returned as a prepared model despite a SHA-256
    mismatch.
- Impact: the inspector tells the user the model is ready even though the first
  operation must repair/download it or may fail in the runtime. This makes setup
  and failure diagnosis contradictory.
- Verification: reproduced against a temporary runtime root without changing the
  installed model cache.
- Recommended direction: centralize one asset validation function used by both
  status reporting and preparation. At minimum validate exact registered size;
  verify the checksum already present in the registry, and report `damaged` separately
  from `not installed`.

### VC-04 - Render completion can silently discard cleanup edits made while it runs

- Severity: critical data-loss bug
- Trigger: start `Create Clean Vocal`, add another accepted cleanup region before
  rendering finishes, then let the original render complete.
- Evidence:
  - `_start_vocal_cleanup_render()` captures the entire `project` snapshot in the
    worker success lambda.
  - `_CleanupRenderBar.set_running()` disables only its own render button; the
    waveform, preview/commit controls, and region actions remain usable.
  - `_on_vocal_cleanup_render_succeeded()` calls `register_result()` with the
    captured snapshot instead of reloading the current manifest.
  - `register_result()` saves that stale project wholesale with the new result.
  - An executable interleaving reproduced a current project growing from one to
    two regions, followed by render registration shrinking the reloaded project
    back to one region. The dropped region file remained as an orphan.
- Impact: successful background work can silently remove a user's newly accepted
  cleanup decisions from the project and leak their generated files. The UI may
  appear to revert after a render finishes.
- Verification: used real store operations in a temporary job directory: capture
  project A, commit region B, then register a result with project A.
- Recommended direction: treat result registration as a narrow transactional
  mutation. Reload the current manifest under a per-job lock and append only the
  result, or use a revision/CAS check and retry. Never save an asynchronous
  operation's full stale aggregate snapshot.

### VC-05 - First-use model status remains stale after the model is installed

- Severity: medium
- Trigger: open a model-backed cleanup tool while its checkpoint is missing, then
  successfully create the first preview that downloads the model.
- Evidence:
  - Tool status labels query `separation_asset_status()` only from
    `VocalCleanupWorkspace.apply_language()`.
  - Preview success calls `set_preview_paths()`, progress/status setters, and queue
    refresh, but no asset-status refresh method exists on this workspace.
  - A widget-level probe constructed the workspace with a missing 121 MB model,
    then simulated a successful preview while the resolver reported ready. The
    success path made zero resolver calls and the label remained
    `First use downloads about 121 MB`.
- Impact: users receive contradictory setup information immediately after a long
  successful download and cannot tell whether another download will occur.
- Verification: offscreen Qt probe with a mocked status resolver and real preview
  path files.
- Recommended direction: extract `refresh_asset_status()` as done by the split and
  recipe workspaces, invoke it after model preparation succeeds and after runtime
  updates, and distinguish downloading, ready, and damaged states.

### VC-06 - Hidden model normalization can lower only the cleaned range

- Severity: high output-quality defect
- Trigger: process a range whose source/model peak exceeds `0.9` with dereverb or
  de-echo, especially at strong strength.
- Evidence:
  - `build_roformer_command()` does not pass `--normalization`; the bundled
    audio-separator CLI defaults it to `0.9` for both input and output.
  - The bundled `spec_utils.normalize()` lowers a waveform whenever its peak is
    above that threshold.
  - `_render_deecho_segment()` and `_render_dereverb_segment()` blend this
    independently level-limited output back into only the selected source range.
  - A pipeline-level probe used a model stub that returned the input unchanged
    except for the bundled normalization rule. Strong de-echo changed the selected
    range peak from `1.0` to `0.89999998` (`-0.915 dB`).
- Impact: even an otherwise identity-quality model can make accepted phrases
  locally quieter than adjacent audio. This is particularly audible when several
  short regions are cleaned and contradicts non-destructive preview expectations.
- Verification: exercised the real `_render_deecho_segment()` composition path,
  command shape, file I/O, and strength mix with only inference replaced by the
  exact bundled normalization formula.
- Recommended direction: make cleanup loudness policy explicit and separate from
  full-song stem normalization. For regional processing, use a source-relative
  level match or `--normalization 1.0`, then apply one documented anti-clipping
  policy after composing the complete result. Add boundary RMS/peak regression
  fixtures for all three strengths.

### VC-07 - Deleting a result can make later cleaned vocals share the same label

- Severity: medium
- Trigger: create cleaned vocals 1, 2, and 3, delete result 2, then render another
  cleaned vocal.
- Evidence:
  - `register_result()` names a new result with
    `Clean vocal {len(project.results) + 1}` rather than a monotonic sequence or
    unique descriptive label.
  - A real store reproduction produced
    `['Clean vocal 3', 'Clean vocal 3', 'Clean vocal 1']`.
  - `cleanup_vocal_choice()` forwards this label unchanged to the conversion input
    pool, so distinct files become visually indistinguishable there as well.
- Impact: users can select, delete, or convert the wrong cleanup revision because
  the UI exposes duplicate names with no effect snapshot or creation time.
- Verification: four result registrations and one supported removal in a temporary
  cleanup store.
- Recommended direction: persist a monotonic project counter or derive the next
  number from the maximum historical suffix. Prefer a descriptive immutable label
  that includes tool/revision or time, while retaining the result UUID internally.

### VC-08 - Effect removal sends the removed original-vocal effects into the backing track

- Severity: critical output-quality defect
- Trigger: run the `Precision Separation · Effect Removal` recipe, then mix its
  instrumental with an RVC-converted vocal.
- Evidence:
  - `RoFormerEngine` replaces the first-stage vocal with the protected dry vocal
    after effect removal, but retains the first-stage accompaniment.
  - The recipe has `mixture_consistency=True`, so `postprocess_stems()` next calls
    `enforce_mixture_consistency()`.
  - That function intentionally preserves the vocal estimate and adds the entire
    residual `source - vocal - backing` to the backing track.
  - Any echo/reverb removed from the vocal is therefore part of that residual and
    is moved into `no_vocals.wav`.
  - Synthetic verification used source `1.0`, cleaned vocal `0.4`, and original
    backing `0.4`. Consistency kept vocal at `0.4` and raised backing to `0.6`,
    transferring the removed `0.2` exactly while reporting zero final residual.
- Impact: the feature can produce a dry RVC input but preserve the original
  singer's echo, reverb, and other vocal residue in the accompaniment. The final
  cover then contains old-vocal artifacts even though the stem pair sums perfectly.
- Verification: exercised the real streaming mixture-consistency implementation
  with float WAV stems and measured the published files.
- Recommended direction: define separate policies for archival mix reconstruction
  and RVC-ready isolation. Effect-removal/RVC mode should not blindly force removed
  vocal energy into the instrumental; retain the trusted first-stage backing or
  route removed effects to an explicit optional stem. Report both isolation and
  reconstruction metrics instead of treating zero mixture residual as quality.

### VC-09 - Concurrent first-use model preparation loses registry entries

- Severity: high
- Trigger: start two tasks that prepare different managed RoFormer/VR models at
  the same time, such as precision separation and a cleanup tool on first use.
- Evidence:
  - `_update_model_registry()` performs an unlocked read-modify-write on the one
    shared `download_checks.json` file.
  - Model preparation always rewrites this registry, even when no files needed to
    be downloaded.
  - A synchronized two-thread reproduction forced both updates to read the same
    empty registry. After both atomic writes completed, only `Model A` remained;
    `Model B` was lost.
- Impact: one otherwise successful task can make the other model invisible to the
  bundled audio-separator runtime, causing intermittent first-use failures whose
  outcome depends on timing. A later use may repair it, making diagnostics harder.
- Verification: real `_update_model_registry()` calls with only its load boundary
  synchronized; no write implementation was mocked.
- Recommended direction: serialize model preparation and registry updates with a
  process-wide/per-root lock, then reload immediately before merging and writing.
  Prefer a registry rebuild derived from verified files over independent mutable
  read-modify-write calls. Add a concurrent two-model test.

### VC-10 - A missing cleaned-vocal file becomes invisible and blocks every later edit

- Severity: high recovery defect
- Trigger: delete, lose, quarantine, or fail to migrate one managed cleanup result
  WAV while its entry remains in `cleanup.json`.
- Evidence:
  - `VocalCleanupStore.load()` reconstructs result records without checking that
    their files exist.
  - `VocalCleanupResultPool.set_results()` silently filters every missing result, so
    the only UI path that emits `result_remove_requested` is no longer available.
  - Every later store mutation calls `_validate_project()`, which rejects the same
    hidden record with `Cleanup result is missing.`
  - A real temporary-store reproduction registered one result, deleted only its WAV,
    and reloaded the project. The manifest still contained one result while the pool
    selected and displayed none. Importing a valid non-overlapping denoise preview
    then failed with `VocalCleanupStoreError: Cleanup result is missing.`
  - `remove_result()` can recover the project only when called directly with the
    hidden result ID; the normal UI cannot obtain or submit that item.
- Impact: a single absent derived file can deadlock the entire cleanup workspace.
  Users cannot see or remove the cause and cannot commit new regions or render a
  replacement, even though the original vocal and all other managed data are valid.
- Verification: exercised the real store and the real offscreen Qt result pool; no
  filesystem or validation method was mocked.
- Recommended direction: load and display damaged entries explicitly with a repair
  or forget action, or reconcile missing derived results transactionally on load.
  Validation errors must identify the affected result and must not hide the only
  recovery control. Add a missing-result restart test followed by a supported repair
  and successful new cleanup commit.

### VC-11 - Selecting an old result after preview makes playback and Apply refer to different audio

- Severity: high wrong-result defect
- Trigger: create a cleanup preview, then click any previously rendered cleaned-vocal
  card before pressing `Apply to This Range`.
- Evidence:
  - `set_preview_paths()` points the processed comparison mode at the new preview and
    marks `_preview_available=True`.
  - `VocalCleanupWorkspace._on_result_selected()` then replaces only the processed
    playback path with the old result and switches playback to it. It does not emit
    `preview_invalidated`, clear the pending preview, or disable the Apply action.
  - `MainWindow._commit_vocal_cleanup_preview()` ignores the selected result and
    commits the still-retained `self._vocal_cleanup_preview`.
  - An offscreen real-widget reproduction changed the audible processed path from
    `current-preview.wav` to `old.wav` while the Apply button remained visible and
    enabled and `preview_available()` remained true.
- Impact: the user can compare and approve one audio file but permanently apply a
  different cleanup operation. The mismatch is silent because both are presented as
  the same `Processed` mode and no preview identity is shown at commit time.
- Verification: real `VocalCleanupWorkspace`, valid float WAV files, and normal
  result-selection state transitions; the Apply target was independently traced
  through the connected main-window commit handler.
- Recommended direction: make pending-preview ownership explicit. Selecting a saved
  result must either invalidate/cancel the pending preview or leave preview playback
  and Apply bound to the same immutable preview ID. Add a UI test that changes result
  selection after preview and asserts `heard_path == committed_preview_path`.

### VC-12 - Noise removal irreversibly quantizes float vocal audio to 16-bit

- Severity: medium audio-quality defect
- Trigger: apply Noise Removal to a separated vocal or denoise model-training audio.
- Evidence:
  - `audio_denoise._render_denoised_audio()` always encodes FFmpeg output as
    `pcm_s16le`, regardless of the input subtype or downstream use.
  - Vocal cleanup starts from and publishes 32-bit float audio, but reads that
    16-bit intermediate and writes it back as float. The second write cannot restore
    samples already rounded to the 16-bit grid, and only the selected range receives
    this extra quantization.
  - The same shared service is also called by `model_dataset.py`, so training-source
    denoise has the same hidden precision reduction.
  - Running the exact production `afftdn` filter twice on one float source, changing
    only the output codec, measured `73.27 dB` overall SNR between float and PCM16
    results and `59.20 dB` in the quieter tail. The quiet section retained 43,934
    distinct float values but only 1,072 PCM16 values.
- Impact: quiet breaths, consonant tails, and low-level details acquire avoidable
  quantization noise or collapse before RVC conversion/training. Region-only cleanup
  can also introduce a precision/noise-floor discontinuity at its boundaries.
- Verification: bundled FFmpeg, the production filter expression, valid float stereo
  WAV input, and `soundfile` subtype/sample comparison.
- Recommended direction: preserve float processing with `pcm_f32le` for managed
  intermediates and quantize only at an explicit user export boundary. Add an
  identity/low-strength precision test that compares float input and output noise
  floor and verifies the cleanup and training paths remain float.

### VC-13 - Interrupted cleanup previews accumulate large invisible files outside safe cleanup

- Severity: high storage-leak defect
- Trigger: crash, force-close, lose power, or close while a cleanup preview worker is
  still producing/holding its files.
- Evidence:
  - Every preview owns `processed-segment.wav`, `removed-segment.wav`, and two
    full-duration FLOAT files (`preview.wav` and `removed.wav`) under the managed
    separation directory's `cleanup/.preview/<preview-id>` folder.
  - Normal in-memory cancellation removes only the currently known preview. There is
    no startup scan or age-based recovery for orphaned `.preview` directories.
  - `build_safe_cleanup_plan()` cleans global job, playback, and preview caches but
    deliberately excludes the protected library tree where these temporary files
    live.
  - A real temporary `AppPaths` layout containing a stale cleanup preview produced
    zero cleanup candidates. Neither the stale directory nor any ancestor was
    scheduled.
  - At 44.1 kHz stereo FLOAT, the two full-song files alone consume about 161.5 MiB
    for a four-minute song, before segment files and repeated attempts.
  - Sol independently confirmed that closing the app does not cancel/join ordinary
    preview command workers, making this reachable beyond hard process crashes.
- Impact: repeated interrupted previews can silently consume gigabytes inside song
  packages. The app's advertised safe cleanup reports nothing, and users cannot
  distinguish these files from protected library data.
- Verification: real storage-layout discovery and `build_safe_cleanup_plan()` with a
  managed stale preview tree; size computed from the actual FLOAT/channel/rate
  contract used by `_compose_audio()`.
- Recommended direction: create previews in the transient preview/cache root or add
  a manifest-aware stale-preview collector that never removes the active preview.
  Record preview ownership/generation, clean abandoned generations on startup and in
  Safe Cleanup, and test interrupted-worker recovery with active-task exclusion.

### VC-14 - Cleanup deletion can commit successfully, report failure, and leave an orphan file

- Severity: medium transaction/UX defect
- Trigger: delete a cleaned result or accepted region while one of its WAV files
  cannot be unlinked, for example because a Windows media handle, scanner, or sync
  process temporarily locks it.
- Evidence:
  - `remove_result()` and `remove_region()` first save the updated manifest and only
    then call `Path.unlink()` on the derived media.
  - The unlink exceptions are not isolated or converted into a committed-with-cleanup-
    pending outcome. Main-window handlers catch them as operation failures and do not
    refresh the workspace with the already committed project.
  - Fault-injecting a `PermissionError` only for the result WAV made
    `remove_result()` raise. Reloading showed zero manifest results while the file
    still existed and the caller's displayed snapshot still contained one result.
- Impact: the UI tells the user deletion failed and keeps showing the item, but a
  refresh makes it disappear. The orphan still consumes storage and is not covered
  by Safe Cleanup because it lives under the protected library tree.
- Verification: real store/manifest write with only the final media unlink faulted;
  the post-error manifest and filesystem were reloaded independently.
- Recommended direction: make deletion a recoverable transaction: stop playback,
  rename media into a same-volume quarantine, commit the manifest, restore on commit
  failure, then delete quarantine best-effort and register any deferred cleanup.
  Return an explicit committed/deferred-cleanup result instead of raising failure
  after the authoritative state has changed.

### VC-15 - Failed separation runs can leave large invisible stems in protected library storage

- Severity: high storage and recovery defect
- Trigger: a separation engine publishes one or both final stem files, then fails
  before `save_separation_run()` and `SongLibrary.register_output()` complete. A
  manifest write error, second-file publish error, or late callback/register error
  can reach this boundary.
- Evidence:
  - `_start_separation()` creates the managed run directory before starting its
    worker, but `_on_separation_failed()` only changes UI status and never removes
    or quarantines the run.
  - Demucs and RoFormer publish `vocals.wav` and `no_vocals.wav` into that managed
    directory before writing `separation.json`. The two publishes and manifest
    commit are not transactional.
  - The song package does not register the run until the worker has returned a
    complete `SeparationResult`, so a late failure leaves no library/output record
    through which the user can inspect or delete the files.
  - The managed `workspace/library` tree is explicitly protected from
    `build_safe_cleanup_plan()`, and the plan has no collector for unregistered
    separation run directories.
  - An executable fault reproduction used the real `DemucsEngine`, real
    `ToolWorkspace.publish_file()`, and real safe-cleanup planner while faulting only
    `save_separation_run()` with `PermissionError`. Both 32 MiB stems remained in the
    run, no manifest existed, and Safe Cleanup returned zero candidates.
- Impact: failed or interrupted separation attempts can silently consume hundreds
  of megabytes per full-length float run while appearing only as a failed task.
  Repeated retries accumulate protected, UI-invisible data that the user-facing
  cleanup action cannot reclaim.
- Verification: real managed path shape and publication code; only external model
  execution and the final manifest failure were controlled. Post-failure filesystem
  and cleanup-plan state were inspected independently.
- Recommended direction: give every run a staged/committed lifecycle. Produce into
  transient storage, atomically publish a complete run directory plus manifest,
  then register it; on any failure quarantine/delete the staging generation. Add a
  startup and Safe Cleanup collector for unregistered/manifestless runs with active-
  task exclusion, and fault tests at first publish, second publish, manifest write,
  and library registration.

### VC-16 - Effect Removal can silently return the original wet vocal as a successful result

- Severity: high wrong-result defect
- Trigger: the secondary effect-removal model succeeds, but
  `protect_effect_removed_vocals()` fails while validating or writing its protected
  output, for example because of an I/O, alignment, or runtime error.
- Evidence:
  - `RoFormerEngine.separate()` catches `VocalEffectProtectionError`, records only a
    detail string, and deliberately leaves `staged_vocals` as the first-stage wet
    vocal instead of failing or publishing the effect-reduced vocal.
  - The run still completes, writes the recipe as `Effect Removal`, and can store
    `postprocess_status="applied"` from the unrelated mixture-consistency step.
  - `SongVocalVersion` retains `separation_postprocess_status` but discards
    `postprocess_detail`; the results UI therefore cannot expose the saved
    `vocal protection skipped` explanation. Its tooltip can say only that mix
    consistency was applied.
  - An executable engine reproduction generated wet vocals at amplitude `0.4` and
    effect-reduced vocals at `0.1`, then faulted only the protection call. The task
    succeeded, the published vocal mean was `0.4`, the manifest status was
    `applied`, and the skipped-protection explanation existed only in its hidden
    detail field.
- Impact: a user can wait for a costly Effect Removal pass, select a result labeled
  as effect-reduced, and feed completely untreated wet vocals into RVC without any
  visible warning. Comparisons and later quality decisions are then based on false
  provenance.
- Verification: real `RoFormerEngine` orchestration, normalization, publication,
  manifest write/load, and float WAVs; model command output and the one protection
  exception were controlled.
- Recommended direction: define this as a degraded result, not success. Either fail
  the task and preserve the previous result, or publish an explicitly labeled
  fallback with a warning that survives into `SongVocalVersion` and the primary
  result UI. Keep effect-removal status separate from mixture-consistency status and
  add a protection-failure contract test.

### VC-17 - De-echo has no vocal-collapse protection and can erase a selected phrase

- Severity: medium output-quality defect
- Trigger: the UVR de-echo model returns a severely attenuated `No Echo` stem for a
  phrase, especially with `Strong` cleanup strength.
- Evidence:
  - `_render_dereverb_segment()` aligns its dry output and passes it through
    `protect_effect_removed_vocals()` before blending. `_render_deecho_segment()`
    reads the no-echo stem and blends it directly, with no activity/level collapse
    test or protected fallback.
  - At strong strength the blend is `1.0`, so an empty or collapsed no-echo estimate
    replaces the selected source phrase completely.
  - An executable pipeline reproduction used a valid stereo 220 Hz vocal tone and
    a de-echo result of zeros. Selected-range RMS changed from `0.282843` to `0.0`,
    retaining `0%` of the vocal while the operation completed successfully.
  - The existing `test_echo_removal_uses_managed_short_path_workspace` also feeds a
    zero no-echo stem and asserts only that output files exist, so the current test
    suite treats complete vocal loss as success.
- Impact: difficult, quiet, or effect-heavy phrases can disappear rather than merely
  losing echo. Manual preview reduces but does not eliminate the risk, particularly
  for short background syllables and users comparing at low monitoring levels.
- Verification: real de-echo segment extraction, strength blend, frame/channel
  matching, and FLOAT publication; only the external model command was replaced by
  a deterministic collapsed stem.
- Recommended direction: reuse a generalized vocal-preservation stage for de-echo
  and dereverb, with tool-specific thresholds if needed. Flag severe collapse as a
  warning or failed preview instead of silently producing it, and add minimum
  activity-retention tests for conservative, standard, and strong settings.

### VC-18 - Touching an unchanged source file silently hides the whole cleanup project

- Severity: high recovery and latent data-loss defect
- Trigger: preserve a vocal file's exact bytes and size but change only its modified
  timestamp, as can occur after backup restore, cloud synchronization, metadata
  repair, or an external editor rewriting identical audio.
- Evidence:
  - `_source_fingerprint()` returns `size:mtime_ns:sha256`. Although SHA-256 already
    establishes content identity, a timestamp change makes the complete fingerprint
    unequal.
  - `VocalCleanupStore.load()` handles any fingerprint mismatch by returning a new
    empty project. It does not warn, expose the old project, or distinguish changed
    content from changed metadata.
  - A real store reproduction committed one region, advanced only the source mtime
    by one second, and verified identical SHA-256 before and after. Reload changed
    the visible region count from `1` to `0` while the old manifest and both segment
    files remained on disk.
  - Saving the new empty lineage through a later preview replaces `cleanup.json`
    without including the old regions, converting those still-valid files into
    protected orphans.
  - The supported storage-migration implementation was separately checked: it
    rebases JSON paths and preserves timestamps, so this finding does not claim that
    the official migration flow triggers the defect.
- Impact: valid cleanup decisions and rendered results can disappear after a
  metadata-only file event. The user receives no recovery choice and can unknowingly
  overwrite the last manifest that references the hidden work.
- Verification: real SHA-256, stat mutation, manifest, segment files, and store load;
  no fingerprint or storage method was mocked.
- Recommended direction: use content hash (plus size as a fast guard) as identity and
  treat mtime only as a hash-cache invalidation input. If content truly changes,
  retain the old lineage as a visible incompatible revision requiring explicit
  rebase/archive/reset rather than silently returning a blank project. Add unchanged-
  content mtime and true-content-change recovery tests.

### VC-19 - Malformed cleanup segments are accepted and rendered as silence or NaN audio

- Severity: high output-integrity defect
- Trigger: a preview/model produces a truncated, wrong-duration, or non-finite
  processed segment, or a previously accepted segment is partially corrupted.
- Evidence:
  - `import_preview()` and `_validate_project()` verify only that managed segment
    paths exist. They do not validate decodability, sample rate, channels, expected
    frame count, finite samples, or checksums before committing the manifest.
  - `_compose_audio()` calls `_match_audio_format()`, whose unlimited length policy
    truncates long files and zero-pads short files. It contains no tolerance or error
    path for a materially incomplete segment.
  - A real store/render reproduction registered a 100-frame segment for a 1,000-
    frame region. Rendering succeeded; the padded middle of the selected vocal had
    RMS `0.0` instead of the source RMS `0.5`.
  - A second real reproduction registered a correctly sized FLOAT segment containing
    one NaN sample. Import and render both succeeded and the final clean-vocal WAV
    retained NaN audio.
- Impact: numerical model failure, interrupted files, or corrupted derived media can
  silently erase phrases or poison a complete result that is then offered to RVC.
  The task can report success and no supported UI identifies the damaged region.
- Verification: real store import, manifest validation, format matching, composition,
  FLOAT publication, and SoundFile reload; no audio-validation behavior was mocked.
- Recommended direction: define and enforce a segment contract at preview completion
  and import: decodable FLOAT/PCM, expected rate/channels, frame error within a small
  documented tolerance, all samples finite, and sane peak/energy limits. Reject or
  quarantine invalid previews before manifest commit, validate existing assets on
  load, and reserve zero-padding for tiny resampler rounding differences only.

### VC-20 - RVC takes do not retain which vocal cleanup result was converted

- Severity: high provenance and quality-comparison defect
- Trigger: convert two different vocal inputs from the same separation job with the
  same model, pitch, index, device, and inference settings. This includes comparing
  an original separated vocal against one or more dereverb/de-echo cleanup results.
- Evidence:
  - `VocalInputChoice` correctly identifies the selected source path and
    `_conversion_input_sound_set()` passes that path into conversion, but
    `_on_rvc_succeeded()` discards the input choice when registering the result.
  - `VocalConversionSettings` and its JSON serializer retain model, index, pitch,
    device, F0 method, and inference values only. `VocalTake` has no input path,
    cleanup result ID, source kind, or source label.
  - `vocal_take_label()` and `vocal_take_summary()` present model/pitch/time rather
    than the input vocal. `ConversionResultBrowser` prefixes only the parent
    separation recipe, so takes produced from different cleanup results under that
    recipe remain visually identical apart from their timestamps.
  - The output filename normally embeds the source stem, but the Windows path-length
    fallback deliberately reduces it to `rvc_<pitch>_<hash>.wav`. At that point even
    the tooltip path cannot recover human-readable provenance.
  - An executable serialization/label reproduction created two takes with identical
    conversion settings and distinct shortened outputs. Both labels were
    `pq-a / Pitch -12`; the serialized take keys were only `take_id`, `label`,
    `output`, `created_at`, and `conversion`, and neither the take nor conversion
    object contained any input/source field.
- Impact: users cannot reliably compare whether original, dereverbed, de-echoed, or
  another cleaned vocal produced the better RVC take. A later session cannot prove
  which input generated a result, so quality experiments are not reproducible and a
  visually identical stale take can be selected for Studio/export.
- Verification: real production dataclasses, JSON serializer, path-shortening naming
  contract, and result-label functions; no source/provenance behavior was mocked.
- Recommended direction: persist immutable conversion-input provenance in every take
  (source kind, managed relative path, stable cleanup/split result ID, and snapshot
  label), include it in the output card and tooltip, and preserve it across schema
  migrations. Treat the output filename as a convenience only, never as the source
  of truth. Add a test converting two cleanup results with identical RVC settings
  and require distinct, recoverable result identities after restart.

## Candidates under verification

None at this checkpoint.

## Cross-check log

- 2026-08-23 23:07 KST: `Problem/Main.md` was empty. `Sol.md` was investigating
  asynchronous lifecycle, storage safety, update boundaries, and diagnostics, so
  this session selected a non-overlapping audio-processing scope.
- 2026-08-23 23:08 KST: a simultaneous initialization race occurred. This session
  wrote a `VocalCleanupAudit` lock block while `Session-Architecture-Audit` added
  the shared protocol and then claimed the lock. This session stopped editing
  `Main.md` immediately. The duplicated initial heading/lock block must be cleaned
  by the current lock owner or by a later owner after the lock is released.
- 2026-08-23 23:13 KST: the existing `unittest` suites for cleanup store,
  cleanup workspace, and separation assets all passed (19 tests). The confirmed
  failures are uncovered transition/fault cases rather than regressions already
  caught by the suite.
- 2026-08-23 23:27 KST: cross-read the five other session reports. No existing
  finding covered VC-10. Sol's independent stale-result and post-delete worker races
  strengthen VC-04's diagnosis that task completion needs immutable ownership and a
  commit-time revision check rather than only a current-page guard.
- 2026-08-23 23:44 KST: 45 cleanup, denoise, effect-protection, postprocess,
  separation-recipe, RoFormer, and composite-engine `unittest` cases all passed.
  VC-12 through VC-15 remain uncovered precision, fault-ordering, and interrupted-
  task cases rather than failures represented by the current regression suite.
