# JJZero Audio Remediation Ledger

This ledger tracks implementation against the evidence in `Main.md`. A finding is
marked resolved only after its original reproduction is inverted by a regression test.

## Range 1 - Persistence and process-concurrency foundation

### Plan

1. Serialize each managed target across threads and processes.
2. Give every write/copy/link/archive operation a unique staging path.
3. Flush completed staging data before one atomic publication step.
4. Keep read-modify-write under the same target lock where a store merges records.
5. Prevent a second application process from initializing shared storage.

### Implemented

- `managed_files.py` now provides reentrant `managed_path_lock()` and
  `atomic_output_path()`, backed by a stable cross-process OS lock.
- JSON/text writes, file copies, and hard-link publication use unique staging paths,
  flush file contents, retry Windows replacement locks, and remove only their own
  staging files on failure.
- Job diagnostics, training diagnostics, support ZIPs, and Studio gzip checkpoints no
  longer use shared deterministic `.tmp` paths.
- `DriveShareCatalog` holds the path lock across load/merge/save, preventing distinct
  concurrent share records from overwriting each other.
- Windows startup now checks `ERROR_ALREADY_EXISTS` and returns before importing Qt or
  opening shared application storage when another JJZero Audio process owns the mutex.

### Verification

- 32 focused tests passed on Windows, including two independent Python processes
  contending for one managed target, 24 concurrent JSON writers, 24 concurrent Drive
  catalog inserts, transient/permanent replace failures, nested lock re-entry, ZIP
  creation, training diagnostics, and Studio checkpoint recovery.
- `compileall` and `git diff --check` passed for the complete range.

### Finding status

- `RLA-001`: resolved by enforced second-instance rejection; full packaged-app smoke
  verification remains in the final integration gate.
- `RLA-012 / SOL-014`: shared temporary-file corruption is resolved. Remaining model
  catalog RMW integration is intentionally coupled to Range 2's directory transaction
  so metadata and artifacts commit as one unit.

## Range 2 - Song and model file transactions

### Plan

1. Move every destructive target into a same-volume quarantine before metadata changes.
2. Copy imports and replacements outside live package paths, then atomically promote them.
3. Stage canonical manifests/catalogs together with their files so rollback is complete.
4. Recover every incomplete journal before library migrations run at application startup.
5. Serialize full read-modify-write operations for song manifests and the model catalog.

### Implemented

- `ManagedPathTransaction` journals existing moves and newly promoted paths, restores in
  reverse order, rejects paths outside the managed root, and preserves unresolved
  recovery folders instead of guessing.
- Application bootstrap scans only the model root, song root, and direct song packages.
  Committed transactions are purged; incomplete transactions discard replacement
  generations and restore the exact previous files and metadata.
- Song import uses a hidden staging package and atomic promotion. Source attachment,
  whole-song deletion, video/output/take/file/Studio deletion, and bulk deletion stage
  both assets and affected metadata. Bulk removal is now all-or-nothing.
- Model import, artifact replacement, and model deletion stage `catalog.json`, the
  affected manifest, packages, work roots, and promoted artifacts as one transaction.
- Model-work ZIP import validates the copied dataset before catalog registration, so a
  failed validation leaves no ghost record and the same package can be retried.
- Song SHA identities, song manifests, model catalogs, and Drive share catalogs hold a
  cross-process lock for the complete read-modify-write operation.

### Verification

- 116 focused tests passed, including forced second-stage move failures, catalog and
  manifest write failures, same-name and different-name model replacement failures,
  model-work validation failure plus retry, and multi-asset partial-commit rollback.
- `SystemExit` probes bypassed normal exception handlers and left real journals behind;
  startup recovery restored complete song packages, model packages/work roots, catalog
  files, managed video, and video metadata on a fresh store instance.
- 16 concurrent song-output registrations, 16 concurrent same-source imports, and 16
  concurrent model links retained every distinct update without duplicate packages.
- AST parsing and `git diff --check` passed. Only the repository's existing LF-to-CRLF
  checkout warnings remain.

### Finding status

- `SOL-015`: resolved for single and bulk song asset deletion, including video, vocal
  output/take, Studio, and generic managed files.
- `SOL-019`: resolved; partial model deletion restores original package and work trees.
- `SOL-020`: resolved; dataset validation precedes model-work catalog registration.
- `SOL-021`: resolved; whole-song deletion stages all data and the tombstone manifest.
- `SOL-024`: resolved; failed song import leaves no invisible managed source package.
- `SOL-025`: resolved; failed model import restores the prior generation or removes the
  exact new package.
- `SOL-026`: resolved; managed artifact replacement never overwrites the referenced
  generation without a rollback journal.
- `RLA-012 / SOL-014`: model/song/Drive catalog lost-update paths covered in this range
  are resolved. Other store-specific RMW paths remain tracked in their owning ranges.

## Range 3 - Asynchronous ownership and shutdown safety

### Plan

1. Bind every asynchronous model operation to an immutable model ID and generation.
2. Bind song-mutating application workers to their song and reject deletion while owned.
3. Invalidate and join in-flight Studio saves before deleting their song or session.
4. Own every child command process and stop process trees before application shutdown.
5. Apply worker results before recording completion and isolate queue observers.
6. Coalesce unchanged progress and bound retained streaming command output.
7. Treat Studio persistence as a required barrier for navigation, switching, export, and close.

### Implemented

- Dataset editing captures its model ID before the thread starts. Dataset, analysis, and
  precise-evaluation panels reject stale progress, stage, detail, success, and failure
  signals by `(model_id, generation)` and hide old progress when selection changes.
- Model busy checks now use each child panel's actual task owner, independent of the
  selected row. Workspace shutdown requests cancellation and waits for dataset editing,
  analysis, and precise evaluation in addition to training and dataset loading.
- Generic workers expose resource ownership and a common cancel/wait contract. Every
  song-mutating import, render, separation, conversion, cleanup, split, quick-create,
  and export worker is owned by its song; song and asset deletion are rejected until
  that owner has fully left the worker registry.
- Studio autosave assigns per-song generations. `discard()` invalidates pending work,
  waits for an already-running save, and only then permits transactional deletion.
- All ordinary, binary, streaming, and cancellable commands are registered while alive.
  Application close stops accepting their results, requests worker interruption,
  terminates process trees, and waits with a bounded deadline before accepting close.
- Worker success finalization now runs before queue completion; a finalization exception
  is recorded through the original failure path. Queue listener exceptions are logged
  and isolated, and unchanged progress/detail updates perform no persistence or render.
- Streaming output is consumed in chunks with incremental decoding and a 256 KiB return
  tail instead of retaining one Python object per character for the full command.
- Studio flush failure now blocks leaving Studio, output switching, audio/video export,
  project history, and application close while keeping the current project visible.

### Verification

- 214 focused integration tests passed, including a held model-A edit released after
  selecting model B, stale analysis/evaluation failures, non-selected model ownership,
  in-flight Studio discard ordering, unchanged progress persistence, observer failure,
  result-finalization failure, carriage-return cancellation, and global termination of
  an ordinary uncancellable child command.
- Nine changed production modules parsed successfully and `git diff --check` passed.
  Only the repository's existing LF-to-CRLF checkout warnings remain.

### Finding status

- `SOL-001` and `SOL-002`: resolved by ordered result finalization and observer isolation.
- `SOL-003` and `SOL-010`: resolved by autosave generations plus song worker ownership.
- `SOL-004` and `SOL-008`: resolved in source; packaged close-during-Demucs/RVC/FFmpeg
  smoke coverage remains part of the final integration gate.
- `SOL-005`, `SOL-006`, and `SOL-009`: resolved by immutable model ownership and stale
  signal rejection across dataset, analysis, evaluation, deletion, and shutdown.
- `SOL-007`: resolved by state equality checks before queue notification or diagnostics.
- `SOL-011`: resolved by chunked streaming and a bounded return tail.
- `SOL-012`: resolved by a shared Studio durability barrier at every destructive boundary.

## Range 4 - Training checkpoint and finalization state machine

### Plan

1. Never remove a complete checkpoint pair before its replacement has loaded and trained.
2. Preserve a recoverable fallback while compacting successful resumed checkpoints.
3. Separate trained-model, index, and catalog-registration durability states.
4. Recover post-training artifacts by inspecting files, not by requiring one failure phase.
5. Keep recovery idempotent after interruption at every post-training boundary.

### Implemented

- Resume startup removes only unpaired partial files and keeps every complete G/D pair.
  Compaction begins only after the trainer has loaded a checkpoint and published a new
  complete pair; it retains the new pair and the latest fallback.
- When RVC reports an explicit checkpoint-load failure, the failed latest pair is moved
  into `training/history/rejected-*` only if another complete pair exists. State refresh
  then selects that fallback, so the next retry cannot silently restart at epoch zero.
- `MODEL_READY` now means the inference PTH and resumable G/D pair are durable,
  `INDEX_READY` means the validated search index is durable, and `COMPLETE` is written
  only after model inspection and model-catalog registration succeed.
- Existing-artifact recovery accepts model-ready, index, complete, and registration-
  failure states. It rebuilds a missing index before idempotent finalization instead of
  requiring another training epoch.
- A process interruption recorded as `TRAIN`/`STOPPED` is also recoverable when the
  durable epoch reached its target and the model/checkpoint artifacts exist. Partial
  user-stopped runs remain normal resume candidates and are not falsely completed.
- The training panel renders the new model-ready state at the index boundary rather
  than presenting the entire operation as complete before registration.

### Verification

- 109 training and model-workspace tests passed, covering fresh training, resume,
  cancellation, preprocessing, extraction, spectrogram caching, index generation,
  finalization, UI state, a corrupt latest pair with a valid fallback, and a complete-
  phase model whose missing index is rebuilt and registered without retraining.
- Five changed production modules parsed successfully and `git diff --check` passed
  with only the repository's existing LF-to-CRLF checkout warnings.

### Finding status

- `SOL-022`: resolved; no complete pair is deleted before a successful resumed save,
  and an explicitly rejected candidate restores the previous pair as active state.
- `SOL-023`: resolved; `COMPLETE` is now the final catalog-registration commit, while
  every earlier durable artifact boundary can be resumed idempotently.

## Range 5 - Cleanup, diagnostics, Drive, and logging

### Plan

1. Redact common OAuth credentials at collection time and at the final ZIP boundary.
2. Invalidate cleanup plans on queue changes and serialize cleanup staging with task
   registration.
3. Restore failed cleanup candidates or expose their quarantine for a later retry.
4. Move Drive existing-share lookup, quota, and package-size preflight off the GUI thread.
5. Persist generic worker tracebacks in the application log with diagnostic context.
6. Reprobe startup hardware and never reuse a failed hardware diagnostic as ready.

### Implemented

- Credential redaction now covers access, refresh, and ID tokens, client secrets,
  quoted JSON assignments, URL queries, and complete Authorization bearer values.
  Support archives redact each generated report again immediately before packaging.
- Queue transitions invalidate cached cleanup plans. Confirmation rebuilds the plan,
  dispatch intersects it with the confirmed candidates, and each transient move runs
  under the queue lock together with the final idle check.
- Failed recursive cleanup restores the staged item to its original path. A failed
  restore leaves a discoverable quarantine candidate that is counted by storage scans
  and can be retried instead of becoming permanently invisible.
- Drive sharing emits its started state immediately, then resolves an existing share,
  fetches quota, estimates package size, packages, and uploads entirely in the worker.
- Every uncaught `TaskWorker` exception writes its full traceback to the rotating app
  log while the diagnostic task context is still active.
- Startup hardware requirements always compare a fresh process probe with the stored
  fingerprint, and any stored `ready=false` result requires another diagnostic run.

### Verification

- 116 focused and adjacent tests passed across support ZIPs, job diagnostics, cleanup,
  queue ownership, Environment & Management UI, Drive sharing, generic workers,
  hardware state, initial setup, runtime display, and model/application integration.
- The final support-ZIP byte probe rejects six distinct OAuth credential forms.
- Stale cleanup, deletion failure, failed restore, and atomic queue-registration probes
  invert the original cleanup reproductions.
- Nine changed production modules parsed successfully. `git diff --check` passed with
  only the repository's existing LF-to-CRLF checkout warnings.

### Finding status

- `SOL-013`: resolved at both collection and final support-archive boundaries.
- `SOL-016`: resolved by plan invalidation, reconfirmation, and atomic idle staging.
- `SOL-017`: resolved by original-path restoration plus quarantine rediscovery.
- `SOL-018`: resolved; network and package-size preflight no longer runs on the GUI thread.
- `ATLAS-06`: resolved; generic worker tracebacks are present in the app log.
- `RLA-005` and `RLA-006`: resolved by live startup comparison and failed-state rejection.

## Remediation range 6A - Vocal cleanup integrity and provenance

This range fixes the confirmed findings in `Problem/VocalCleanupAudit.md` without
closing the packaged and live-model integration gates listed below.

### Plan

1. Put cleanup edits and model-asset registration behind transactional ownership.
2. Preserve source/result identity across replacement, deletion, preview, and RVC use.
3. Fail closed on malformed audio, model-integrity, and effect-protection errors.
4. Remove hidden normalization and precision loss from the audio path.
5. Cover interruption, concurrency, stale result, and provenance transitions.

### Implemented

- Cleanup edits now use a per-project lock, current-manifest reload, unique media
  generations, and recoverable quarantine transactions. Region replacement and
  deletion cannot destroy the committed media before the manifest commits.
- Existing regions can be selected, previewed with another tool or strength, and
  atomically replaced. A stale render is rejected instead of overwriting newer
  region edits.
- Result numbering is monotonic. Missing result files remain visible and removable,
  while selecting an older result invalidates any pending preview so playback and
  Apply cannot refer to different audio.
- Source identity uses size plus SHA-256 rather than timestamp. A metadata-only touch
  retains the project; a real content change is reported without replacing its
  manifest with an empty project.
- Accepted segments are checked for sample rate, channels, duration, readability,
  and finite samples. Composition permits only a small rounding tolerance instead
  of silently padding a truncated segment.
- RoFormer preparation validates size plus SHA-256 and records the verified file
  identity. UI status reads that record without hashing up to 0.9 GB on the GUI
  thread, and concurrent integrity/registry updates are serialized. Existing
  unstamped files are verified in the background without forced redownload.
- Regional RoFormer processing disables hidden 0.9 normalization. De-echo uses the
  same vocal-collapse protection as dereverb, denoise intermediates stay 32-bit
  float, and effect-removal protection failure now fails instead of publishing the
  untreated wet vocal.
- Effect-removal separation no longer transfers removed vocal ambience into the
  backing track through mixture consistency.
- Interrupted cleanup previews and current-format manifestless separation runs are
  exposed to Safe Cleanup only while no jobs are active. Normal worker and late
  registration failures also discard their uncommitted run folder.
- Every newly registered RVC take retains input kind, managed relative path, stable
  source ID, and source label. Result summaries and tooltips expose that provenance.

### Verification

- 158 focused service, pipeline, Qt offscreen, migration, concurrency, and
  fault-injection tests passed in one run.
- AST parsing passed for every modified production module.
- `git diff --check` passed with only the repository's existing LF-to-CRLF checkout
  warnings.

### Finding status

- `VC-01`, `VC-02`, `VC-03`, `VC-04`, `VC-05`, `VC-06`, `VC-07`, `VC-08`,
  `VC-09`, `VC-10`, `VC-11`, `VC-12`, `VC-13`, `VC-14`, `VC-15`, `VC-16`,
  `VC-17`, `VC-18`, `VC-19`, and `VC-20`: resolved by source-level regression and
  fault tests.

## Completed source remediation and deferred verification

All confirmed source findings are remediated below. Live, packaged, and hardware gates
that were not executed remain explicitly open and must not be inferred from source tests.

### Range 6 - Runtime, updater, and release trust

#### Plan

1. Verify complete partials locally and strictly validate every resumed response.
2. Preflight peak storage and make runtime swaps recoverable across process exit.
3. Bind app/runtime versions, source revision, remote digest, and signer identity.
4. Preserve external custom roots and verify install/update/uninstall scripts.

Source-level verification is complete for `RLA-002`, `RLA-003`, `RLA-004`,
`RLA-007`, `RLA-008`, `RLA-009`, `RLA-010`, `RLA-011`, `ATLAS-01`, `ATLAS-02`,
`ATLAS-03`, `ATLAS-04`, `ATLAS-05`, `ATLAS-07`, `ATLAS-08`, `ATLAS-09`,
`ATLAS-10`, `ATLAS-11`, `ATLAS-12`, `ATLAS-13`, `ATLAS-14`, and `ATLAS-15`.
Complete partial downloads are verified before promotion, archive paths and sizes are
bounded, runtime swaps recover after interruption, stale manifests cannot downgrade
components, and application upgrades require a pinned Authenticode signer certificate.

- 77 runtime/download/transaction tests and 65 updater/release/bootstrap tests passed.
- PowerShell parser validation passed for the modified build and release scripts.
- `ATLAS-06` remains covered by Range 5's generic worker logging regression.

### Range 7 - Studio session, preview, and export integrity

#### Plan

1. Distinguish auto-seeded tracks from tracks intentionally emptied by the user.
2. Preserve unresolved timeline references and fail closed instead of partial export.
3. Execute one ordered audio graph for realtime preview and offline rendering.
4. Align video capability, media-audio mix state, silence, and project duration.
5. Treat the asset manifest as a derived cache of the committed session revision.

Source-level verification is complete for `A-001`, `A-002`, `A-003`, and `A-005`
through `A-011`. `A-004` remains covered by Range 3's autosave durability barrier.

- Auto-seeded empty required tracks accept later outputs without repopulating tracks
  the user intentionally emptied.
- Missing audio or visual references fail the whole export instead of producing a
  partial result, and edited media tracks survive unavailable assets unchanged.
- Realtime preview and export share pre-FX volume, ordered effects, fades, and post-FX
  pan. Video-source audio follows the media track's mute, solo, volume, and pan.
- Video duration follows the longer of audio and visuals, and a media-only timeline
  renders with generated silence.
- Session commits precede the derived asset manifest, and loading refreshes that cache
  from the recovered current session.
- 359 service, playback, export, and Qt offscreen regressions passed in one run.

### Range 8 - Google Drive remote ownership

#### Plan

1. Journal each uploaded remote ID before permission or local publication.
2. Atomically promote the new catalog record and queue a replaced remote for deletion.
3. Compensate failed publication and retain failed cleanup for later retry.
4. Reconcile retained cleanup records before later share and delete operations.

Source-level verification is complete for `RLA-013`.

- Every completed upload is recorded as an uncommitted remote before public-link and
  local-catalog publication.
- Permission or catalog failure compensates with remote deletion. Failed deletion
  remains in a persistent retry list.
- Replacing a share atomically promotes the new record and schedules the previous
  public file for deletion, so an old public link is not silently orphaned.
- 30 Drive client, catalog, service, and controller tests passed, including permission,
  disk, replacement, and cleanup-retry fault injection.

### Range 9 - Conversion result selection state

#### Plan

1. Represent an explicit cleared selection separately from uninitialized state.
2. Prevent result refresh and browser fallback from restoring a stale RVC take.
3. Keep the visible conversion input and timeline result synchronized across refresh.

Source-level verification is complete for `UI-STATE-01`.

- `WorkConvertSession` retains an explicit cleared converted-result selection instead
  of treating `None` as an uninitialized value.
- Result-browser refresh and main-window timeline synchronization do not restore an
  old or fallback RVC take after the user changes the conversion input.
- 28 focused conversion session, browser, refresh, and main-window tests passed in
  the current completion audit.

### Range 10 - Shared model ZIP import boundary

#### Plan

1. Validate every ZIP member and Windows extraction target before reading metadata.
2. Enforce duplicate, link, encryption, size, count, and compression-ratio limits.
3. Match manifest sizes to ZIP metadata and cap actual streamed extraction bytes.
4. Preflight workspace space before extraction and final package installation.

Source-level verification is complete for the shared model import boundary.

- Model and model-work imports share one archive safety service that rejects mixed
  separators, drive/UNC/device paths, duplicate and case-equivalent destinations,
  symbolic links, encrypted members, and unlisted JJZero package files.
- Per-file, total expanded-size, member-count, manifest-size, and compression-ratio
  limits are checked before extraction. Streamed bytes are checked again while files
  are written.
- Both import paths reserve space for temporary extraction and managed installation.
  Model-work identity is one safe path component and imported records use only their
  managed runtime path rather than an untrusted sender path.
- 35 archive, model/model-work share, and Google Drive controller regressions passed,
  including executable Windows traversal, collision, compression, size, and disk
  fault probes.

### Range 11 - Song and model commit interruption recovery

#### Plan

1. Journal new catalog/package paths before their first write or copy.
2. Keep partial song, model, and model-work imports inside recoverable transactions.
3. Restore previous catalogs and remove promoted data after pre-commit termination.
4. Reconcile deferred per-model manifests from the authoritative catalog on restart.

Source-level verification is complete for song and model commit boundaries.

- `ManagedPathTransaction` can persist an empty prepared journal and register a path
  that a later metadata write is expected to create.
- New-model creation, ordinary model import, model-work extraction/import, and song
  import now stage partial data inside the transaction folder from the first copy.
- Startup recovery removes partial or promoted new data and restores the previous
  catalog after forced termination before commit. A deferred `model.json` write is
  repaired from the authoritative model catalog on the next load.
- 111 startup, transaction, song/model package, asset-removal, shared ZIP, and Drive
  controller regressions passed, including forced termination during first copy,
  extraction, catalog replacement, and final commit.

### Range 12 - RVC checkpoint pair selection and recovery

#### Plan

1. Use one numeric G/D pair selector across training state, cleanup, and work import.
2. Reject incomplete and similarly named checkpoint files from resume selection.
3. Quarantine a checkpoint pair that fails to load without treating it as user cancel.
4. Retry the previous complete pair in the same task when one is available.

Source-level verification is complete for checkpoint pair compatibility and recovery.

- Training state, checkpoint cleanup, model-work export/import, and workspace discovery
  now share one exact `G_<step>.pth` / `D_<step>.pth` pair implementation.
- Pair generations are compared numerically, and an incomplete G or D generation is
  never combined with a checkpoint from another step.
- A load failure quarantines the failed pair even when it is the only saved pair, so
  later resume attempts cannot repeat the same permanent failure indefinitely.
- When an older complete pair remains, training records a separate diagnostic attempt
  and automatically retries that pair without requiring the user to restart the job.
- 207 training pipeline, finalization, recovery, diagnostics, workspace, import, and
  Qt offscreen regressions passed in one run.

### Range 13 - Google Drive cancellation ownership

#### Plan

1. Retain controller ownership until each active share/delete callback completes.
2. Recheck cancellation after remote upload and publication commit boundaries.
3. Compensate a committed upload or retain its remote ID when deletion is unavailable.
4. Retry retained remote cleanup immediately after account reconnection.

Source-level verification is complete for Drive cancellation and disconnect recovery.

- Cancelling or disconnecting no longer removes active controller records before the
  worker reports whether the remote operation committed, failed, or was cancelled.
- The share service checks cancellation after upload and after public permission
  creation. A remotely committed file is deleted before cancellation is returned.
- If disconnect removed credentials before compensation can finish, the pending
  remote ID remains in the persistent cleanup journal and is retried on reconnect.
- 62 Drive client, OAuth, catalog, controller, model-share, and model-work-share
  regressions passed, including cancellation after publication and reconnect cleanup.

### Range 14 - Release platform compatibility contract

#### Plan

1. Preserve release architecture and minimum Windows metadata in the parsed model.
2. Reject malformed or unsupported platform declarations before download starts.
3. Check both fetched manifests and manually constructed runtime-only update plans.
4. Keep legacy manifests without platform metadata compatible.

Source-level verification is complete for release platform constraints.

- `architecture` and `minimum_windows` are no longer discarded by the release parser.
- A release for another host architecture or a newer Windows build fails before any
  application or multi-gigabyte runtime artifact is selected for download.
- The compatibility gate also runs in `create_update_plan()`, preventing internal or
  runtime-only callers from bypassing the parsed-manifest check.
- 91 updater, component validation, runtime bootstrap/installation, transaction,
  release-manifest, and distribution verification regressions passed in one run.

### Range 15 - Canonical library and SQLite reconciliation

#### Plan

1. Serialize shared SQLite schema and read-modify-write operations across processes.
2. Detect canonical song/model manifest changes during a catalog rebuild snapshot.
3. Never mark a stale rebuilt index with the latest source signature.
4. Preserve automatic rebuild after an interrupted manifest-to-index update.

Source-level verification is complete for the canonical library catalog boundary.

- Library catalog and virtual-group SQLite transactions now share the same
  interprocess path lock, including first-run schema migration.
- Rebuild captures a source signature before reading song/model records, rejects a
  changing snapshot, and verifies the signature again after commit.
- If sources continue changing, the fallback snapshot records its earlier signature
  rather than falsely claiming the current files, preserving next-start reconciliation.
- 104 managed-file, library/group, song/model package, import/share, deletion, and
  work-song regressions passed, including a manifest mutation during rebuild.

### Range 16 - Environment-management worker shutdown ownership

#### Plan

1. Re-audit direct `TaskWorker`, model worker, command, and executor creation sites.
2. Preserve background work while the reusable management window is merely hidden.
3. Cancel and join page-owned workers only when the application actually exits.
4. Block late worker signals before the Qt object tree is destroyed.

Source-level verification is complete for the remaining management-page worker gap.

- Main-window direct workers remain registered in its shared shutdown list, and model
  dataset, analysis, evaluation, training, and telemetry workers retain page ownership.
- Diagnostics ZIP, PC/RVC checks, storage scan, and cleanup workers are now collected
  by `DiagnosticsPage.shutdown()` on `aboutToQuit`.
- Shutdown blocks late UI callbacks, terminates tracked child commands, and waits for
  every page-owned thread before clearing references.
- 33 diagnostics, environment panel, storage, support archive, generic worker, and
  window-lifecycle regressions passed with RuntimeWarnings promoted to errors.

### Range 17 - Waveform request cancellation under rapid navigation

#### Plan

1. Keep ownership of every deferred waveform `Future` at its widget or timeline.
2. Cancel a request when its path, session, or owning widget is replaced or closed.
3. Ignore late results from canceled or obsolete requests.
4. Reuse one completed waveform for every timeline asset with the same cache key.

Source-level verification is complete for the waveform executor backlog in the
interactive waveform surfaces.

- Dataset-editor, shared playback, thumbnail, and Studio timeline waveforms now retain
  their submitted futures and cancel obsolete work on path/session changes and close.
- Studio timeline requests are canceled when their asset or level-match key leaves the
  current session, while late callbacks remain harmless through cache-key checks.
- Duplicate Studio assets sharing one source key receive the completed peaks together,
  avoiding redundant visible loads.
- 74 waveform, Studio, and request-lifecycle regressions passed, including blocked
  future cancellation for all four widget/timeline paths.

### Range 18 - Safe Cleanup reparse-point boundary

#### Plan

1. Revalidate a cleanup candidate immediately before moving it into quarantine.
2. Reject reparse points on the candidate, its allowed root, and their path chain.
3. Refuse a pre-existing or newly created quarantine directory that is not a plain
   child directory of the candidate's managed parent.
4. Serialize each cleanup target while its move and removal are in progress.

Source-level verification is complete for the Safe Cleanup reparse-point boundary.

- Cleanup now rechecks the candidate and quarantine path after any idle-queue guard
  and immediately before `os.replace`, so a changed path is reported as failed rather
  than deleted.
- Existing `.jjzero-cleanup` symlinks, junctions, and other reparse points are
  rejected, and reparse points anywhere between a candidate and its allowed root are
  not accepted as safe targets.
- Cleanup target moves and removals now use the same managed path lock as other
  destructive storage operations.
- 12 storage-management regressions passed, including the reparse-quarantine guard,
  stale idle candidates, failed deletion restoration, and quarantine rediscovery.

### Deferred investigation backlog

These are recorded candidates, not confirmed defects. They require executable
reproduction before promotion into a remediation range:

- Analysis executor backlog under rapid navigation.
- Environment and diagnostics worker lifecycle while pages close or switch.
- Storage relocation interruption, locked files, insufficient space, and skipped-
  version legacy layouts.
- Group/filter/active-song state under deletion, refresh, drag/drop, and two processes.
- Large-library, long-log, preview-cache, signal, memory, and UI-starvation benchmarks.
- `RLA-C01`: attribute main-window import cost and measure the frozen build before
  changing startup module boundaries.

### Deferred live and packaged verification

These gates were not executed and remain intentionally open:

- Clean install, retained-data update, signed installer launch, runtime activation,
  committed-update restart recovery, uninstall, and re-downloaded public artifact.
- Packaged second-instance rejection and packaged close-during-Demucs/RVC/FFmpeg.
- Actual bundled-FFmpeg renders for missing media, visual-longer-than-audio, silent
  media-only timelines, and media source-audio mix controls.
- Real Google Drive permission failure, replacement cleanup, application restart with
  a retained cleanup record, and quota/account behavior.
- Packaged real-model dereverb, de-echo, and denoise; forced termination during cleanup;
  Safe Cleanup with a genuinely active job; and RVC provenance after restart.
- Training resume/finalization on supported NVIDIA generations and the pending AMD
  runtime evidence still require tester hardware.

### Final integration gate

- `RLA-001`: source regression is complete; packaged second-instance behavior remains
  unverified.
- `SOL-004` and `SOL-008`: source regressions are complete; packaged close-during-
  Demucs/RVC/FFmpeg behavior remains unverified.
- The deferred live and packaged verification list above remains mandatory before
  release closure.
