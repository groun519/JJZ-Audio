# Sol Session Audit

## Session status

- Status: investigating
- Started: 2026-08-23 23:05 KST
- Scope: asynchronous task lifecycle, shared UI state, storage/data safety,
  runtime/update boundaries, and diagnostic observability
- Main.md lock: not held

## Method

Each finding must include concrete code evidence, user impact, a plausible trigger,
and a verification state. Suspicions remain in the candidate section until a second
code path, test, or executable check confirms them.

## Confirmed findings

### SOL-001 - A worker is recorded as completed before its success result is applied

- Severity: high
- Area: `MainWindow._run_worker()` / job diagnostics correctness
- Evidence:
  - `handle_success()` calls `processing_queue.complete(task_id)` before
    `on_success(result)`.
  - Exceptions raised by `on_success` are emitted from a Qt slot and never reach the
    worker's `failed` signal.
  - Several normal callbacks can explicitly discover failure only after this point:
    an empty update download calls `_set_update_download_failed()`, an invalid quick
    production result calls `_on_quick_creation_failed()`, and a cleanup result that
    cannot be registered calls `_on_vocal_cleanup_render_failed()`.
- Executable confirmation (2026-08-23): a real `TaskWorker` whose success callback
  raised `RuntimeError("finalization failed")` left both `ProcessingQueue` and the
  persisted `JobDiagnostics` record in `completed`; the exception was delivered only
  to `sys.excepthook` and no failed signal ran.
- Impact: the activity UI and support ZIP can claim success while catalog updates,
  manifest registration, output activation, or the visible operation itself failed.
  A later support report therefore hides the actual failing phase.
- Missing gate: worker tests cover background task exceptions, but not exceptions or
  rejected values in success finalization.
- Recommended direction: apply and validate the result before completing the queue,
  catch finalization exceptions into the same failure path, and require callbacks
  that reject a result to raise a typed error rather than only changing UI text.

### SOL-002 - One failing queue listener strands an unreturnable running job

- Severity: high
- Area: `ProcessingQueue._notify()` observer isolation
- Evidence:
  - `_notify()` invokes each listener directly without exception isolation.
  - `start()` writes the diagnostic and inserts the task before calling `_notify()`;
    a listener exception escapes before `start()` can return the new task ID.
  - The same ordering can interrupt progress/finalization notification and prevent
    later diagnostics persistence or success-result application.
- Executable confirmation (2026-08-23): a subscribed listener that raised only for a
  non-empty snapshot made `queue.start()` raise `RuntimeError("dead UI listener")`.
  The caller received no task ID, while both the in-memory task and persisted summary
  remained `running`.
- Impact: one stale/deleted UI subscriber or unrelated rendering bug can block every
  subsequent observer, abort the user's requested operation before its worker starts,
  and leave a permanent phantom running task that cannot be completed by its caller.
- Missing gate: the subscriber test checks normal snapshots only; there is no test
  proving one listener cannot affect queue state or other listeners.
- Recommended direction: isolate and log each listener exception, continue notifying
  the remaining listeners, and never let presentation observers alter queue mutation
  control flow. Add start/progress/finish tests with one throwing listener.

### SOL-003 - An in-flight Studio autosave recreates managed data after song deletion

- Severity: critical
- Area: `StudioSessionAutosave.discard()` / full-song deletion transaction
- Evidence:
  - `discard(song_id)` removes only `_pending`; it does not invalidate or wait for an
    `_inflight` save of the same song.
  - `MainWindow._remove_library_item()` calls `discard(song_id)` and immediately
    deletes managed package contents through `SongPackageStore.remove_managed_data()`.
  - A save that already passed `SongLibrary.save_studio_session()`'s
    `store.require(item_id)` retains the old `SongPackage` and can call
    `save_studio_session()` after deletion. That function creates the Studio project
    directory and commits files without rechecking the package tombstone.
- Executable confirmation (2026-08-23): a real package/autosave probe paused the save
  immediately after `store.require()`, removed managed data, called `discard()`, then
  released the save. The package directory changed from only `['song.json']` back to
  `['03_studio', 'song.json']`.
- Impact: full-song deletion or removal of a Studio session can leave managed files
  behind again, consume storage invisibly under a removed tombstone, and potentially
  resurrect stale edits if the song is later re-imported.
- Missing gate: the existing discard test covers only a pending debounce entry, not
  a save already running during package/session deletion.
- Recommended direction: assign per-song save generations/tombstones, invalidate both
  pending and inflight generations before deletion, wait for an acquired save or make
  its final commit reject a removed package, then perform deletion. Add deterministic
  in-flight deletion tests for both whole-song and Studio-session removal.

### SOL-004 - Closing the app leaves ordinary processing child processes unmanaged

- Severity: critical
- Area: `MainWindow.closeEvent()` / `TaskWorker` / command process ownership
- Evidence:
  - `MainWindow.closeEvent()` stops timers, Drive operations, playback, and model
    training, but never interrupts or joins the generic `self._workers` list.
  - Separation, RVC conversion, video render, YouTube download, vocal cleanup/split,
    export, runtime install, and update download all use those unmanaged workers.
  - Their pipeline commands use `run_command()` and `subprocess.run()` with no shared
    cancellation token or Windows job object tied to the app process.
- Executable confirmation (2026-08-23): a child launched through the real
  `jang_app.services.command.run_command()` from a worker thread remained alive after
  its parent process exited (`parent_exit=0`, `child_survived=True`). The probe child
  exited naturally after two seconds.
- Impact: closing JJZero Audio during a long operation can leave Python, FFmpeg,
  Demucs/RoFormer, RVC, or download processes consuming CPU/GPU and writing files.
  Reopening the app can then overlap a second operation with the orphan and expose
  partial outputs, locked files, misleading interrupted diagnostics, or corrupted
  multi-file state.
- Contract inconsistency: model training and Google Drive own explicit cancellation,
  while the generic worker path driving most other expensive operations does not.
- Missing gate: no main-window close test starts an ordinary worker/child and proves
  the entire process tree is stopped before shutdown returns.
- Recommended direction: give every long operation a cancellation token, track
  process trees in an app-owned registry/Windows Job Object, reject new tasks during
  shutdown, request cancellation for every worker, wait with a bounded deadline, and
  persist cancelled/interrupted status only after the process tree has ended.

### SOL-005 - A completed material-edit task can replace another model's visible dataset

- Severity: critical
- Area: `ModelDatasetPanel` asynchronous model identity
- Evidence:
  - `set_model()` can change `_model_id` while `_worker` is still running.
  - `_on_worker_succeeded()` calls the stored callback without the model ID that
    started the task, and `_apply_worker_dataset()` unconditionally assigns any
    `ModelDataset` to `self._dataset` and renders it.
  - Most task lambdas also read `self._model_id` inside the worker rather than capture
    the initiating ID (`add_sources`, clip update/split, denoise, accept region,
    undo/redo, reset). A switch before the thread evaluates the lambda can therefore
    redirect the mutation itself, not only its display result.
- Executable confirmation (2026-08-23): a deterministic worker for model A was held,
  the panel switched to model B, and then A was released. Final state was
  `selected_model=model-b`, `displayed_dataset=model-a`, with the success status for A.
- Impact: rapid model navigation during audio import/edit/denoise can show and operate
  on another model's materials, apply an action to the wrong model, and emit misleading
  `dataset_changed` events. Subsequent user edits can persist cross-model state.
- Missing gate: dataset worker tests do not switch models while an operation is in
  flight and assert both target identity and stale-result rejection.
- Recommended direction: capture an immutable model ID and operation generation before
  constructing every task, include it in result handling, reject stale progress and
  completion, and either lock model navigation or allow concurrent per-model workers
  with explicit ownership.

### SOL-006 - A background model task can recreate a model workspace after deletion

- Severity: high
- Area: model deletion vs panel/analysis workers
- Evidence:
  - `_model_has_active_task(model_id)` checks dataset/analysis/evaluation panel workers
    only when `model_id == _selected_model_id`.
  - Switching from model A to B does not stop A's analysis worker. Deleting row A while
    B is selected therefore passes the guard even though `analysis_panel._worker` is
    active for A.
  - `analyze_model_dataset()` writes its final cache to
    `<dataset-root>/<model-id>/analysis/dataset-analysis.json` and the atomic writer
    recreates missing parents.
- Executable confirmation (2026-08-23): a harness with an active analysis worker and
  selected model B returned `False` from `_model_has_active_task("model-a")`. A real
  analysis commit paused before write, followed by removal of model A's root, recreated
  the root and cache after release (`after_delete_exists=False`,
  `after_analysis_exists=True`).
- Impact: deleting a model can leave hidden workspace files behind and race with edits,
  analysis, or benchmark output. Re-importing the same model ID can then inherit stale
  cache/work data that the user explicitly deleted.
- Recommended direction: track task ownership by model ID independently of current
  selection; cancel/join or generation-invalidate every owned task before deleting;
  make final writers verify that the model is still registered.

### SOL-007 - Repeated integer progress values synchronously rewrite diagnostics and refresh the queue

- Severity: high
- Area: `ProcessingQueue.update_progress()` / `JobDiagnostics.update_progress()` /
  long-running training progress
- Evidence:
  - `_update_task()` replaces and notifies for every call without checking whether the
    clamped progress differs from the current task value.
  - Every accepted call then synchronously rewrites `summary.json` through an atomic
    JSON write and separately appends a `progress` record to `events.jsonl`.
  - RVC training reports progress for every epoch. The value is rounded to an integer,
    so a 20,000-epoch run can emit the same displayed percentage hundreds of times.
  - Qt delivers the training worker's progress signal to `_on_training_progress()` on
    the GUI thread; diagnostics writes and processing-queue subscriber rendering then
    execute on that thread.
- Executable confirmation (2026-08-23): 20,000 identical `32%` updates through the
  real queue and diagnostics classes produced 20,000 summary rewrites, 20,000 event
  appends, and 20,000 subscriber notifications. It took 21.577 seconds on this PC and
  created a 3,340,182-byte event log while the visible progress never changed.
- Impact: high-epoch training and file-heavy preprocessing can periodically stall the
  UI, waste SSD writes, inflate diagnostic ZIPs, and make the apparent training speed
  depend on UI/log persistence rather than model computation.
- Missing gate: no test asserts that an unchanged progress/detail update is a no-op or
  bounds persistence/render frequency for high-volume operations.
- Recommended direction: compare state before notification, coalesce GUI progress
  signals, persist only changed integer values (or throttle by time), and keep detailed
  epoch telemetry in its dedicated event stream rather than duplicate it as progress.

### SOL-008 - Model auxiliary workers remain alive after workspace shutdown

- Severity: high
- Area: `ModelWorkspacePage.shutdown_training()` / child panel worker ownership
- Evidence:
  - `shutdown_training()` waits only for the training worker, telemetry worker, and
    dataset-load worker.
  - Material editing, material analysis, and precise model evaluation each own a
    separate `_worker` on their child panel. They are neither cancelled nor joined by
    `shutdown_training()` or `closeEvent()`.
  - These workers can still be reading audio, running inference, or committing analysis
    and benchmark cache files while their parent widget tree is closing.
- Executable confirmation (2026-08-23): a real blocking `TaskWorker` assigned to the
  material panel was running before `shutdown_training()`. The shutdown returned in
  0.000005 seconds and the worker remained running afterward.
- Impact: closing the model workspace/app can destroy signal receivers while worker
  code continues, allow post-close writes, trigger `QThread: Destroyed while thread is
  still running`, or overlap the same model operation after restart.
- Relationship: this is distinct from SOL-004's unmanaged subprocess trees; these are
  in-process Qt workers omitted even from the model page's explicit shutdown routine.
- Recommended direction: expose a common `cancel_and_wait(deadline)` contract on every
  worker-owning panel, call all of them before widget destruction, reject late signals
  by generation, and add a close test that holds each worker in flight.

### SOL-009 - Stale model analysis/evaluation signals overwrite the newly selected model UI

- Severity: high
- Area: material analysis and precise evaluation panel result ownership
- Evidence:
  - Precise evaluation captures `_active_model_id`, and its success handler rejects a
    report whose model ID differs from the currently selected record.
  - Progress, stage, detail, and failure handlers perform no equivalent identity check;
    they always mutate the panel currently shown by `set_model()`.
  - Material analysis likewise guards successful reports by `result.model_id` but wires
    progress directly to the shared progress bar and always applies failure text.
  - Model navigation remains enabled while both workers run.
- Executable confirmation (2026-08-23): while an A evaluation was represented as
  active, the panel was switched to model B. Delivering A's late signals set B's bar to
  `73`, changed its stage, and replaced B's status/headline with A's failure message.
- Impact: users can interpret another model's failure or progress as belonging to the
  selected model, rerun or edit the wrong model, and lose confidence in cached results.
  Queue diagnostics retain A's identity, so the visible page and diagnostic history can
  directly contradict each other.
- Recommended direction: capture an operation token `(model_id, generation)` in every
  progress/completion/failure signal, reject stale UI mutations uniformly, and render a
  per-model background-operation indicator rather than reusing the selected panel.

### SOL-010 - Deleting a song during an owned task recreates hidden package data

- Severity: critical
- Area: library deletion vs song-scoped background task ownership
- Evidence:
  - `_remove_library_item()` checks playback and Studio autosave but never checks the
    processing queue or maps workers to the song they mutate.
  - Users can return to Library and delete a song while separation, conversion, media
    import/download/render, cleanup, split, quick creation, or export is still running.
  - Separation captures a newly created package-internal run directory before starting
    its worker. The external process can recreate that directory after
    `remove_managed_data()` has deleted it.
  - `_on_separation_succeeded()` then unconditionally calls `register_output()` for the
    removed song. `SongPackageStore.require()` rejects the tombstone, but no cleanup of
    the late output is performed.
- Executable confirmation (2026-08-23): a real `SongLibrary` created a separation run,
  removed the song, and then simulated the already-running separator's late write. The
  package changed from only `song.json` back to `02_vocal/song.../vocals.wav`; output
  registration raised `KeyError`, the late file survived, and the song remained absent
  from the visible library.
- Impact: deleting a busy song does not actually reclaim its data, can leave large
  model/media outputs inaccessible, and may produce an uncaught completion exception.
  Through SOL-001 the same operation can be persisted and shown as completed before
  result registration raises.
- Relationship: SOL-003 proves the same invariant violation for in-flight Studio
  autosave; this finding covers the general song-task lifecycle and external writers.
- Recommended direction: assign every worker a resource owner (`song_id`, output path),
  block deletion or cancel-and-join all owned workers and process trees first, tombstone
  generations before filesystem deletion, and make late registration atomically reject
  and quarantine/remove abandoned outputs.

### SOL-011 - Streaming commands retain output one character at a time with ~9.5x memory amplification

- Severity: high
- Area: command streaming used by RVC training and long external tools
- Evidence:
  - `_read_streaming_output()` calls `process.stdout.read(1)` and appends every character
    to `output_parts` for the lifetime of the command, even when an output callback and
    durable diagnostic log already consume each line.
  - It then joins the full list into another complete output string returned in
    `CommandResult`. Training later combines that string with `train.log` and calls
    `casefold()`, producing further full-size copies.
  - There is no byte/line cap, rolling tail, or option for callback-only streaming.
- Executable confirmation (2026-08-23): the real reader consumed synthetic 1, 5, and
  10 MiB streams. Traced peak memory was 9.1, 46.9, and 95.0 MiB respectively
  (9.1-9.5x input size), before downstream training copies. The 10 MiB stream also
  required 1.141 seconds solely for per-character Python handling.
- Impact: verbose or long RVC/FFmpeg/Python commands can progressively slow down,
  consume hundreds of MiB, and fail late despite command output already being written
  to diagnostics. Failure risk scales with log volume rather than model/audio memory.
- Recommended direction: read fixed-size chunks or iterate lines, send callbacks
  incrementally, retain only a bounded diagnostic tail for the returned result, and
  use explicit completion markers collected during streaming instead of rescanning a
  complete in-memory transcript.

### SOL-012 - Studio save failures are ignored by navigation, export, output switching, and app close

- Severity: critical
- Area: Studio autosave durability barrier
- Evidence:
  - `StudioSessionAutosave.flush()` returns `False` when persistence fails and retains
    the pending session for a possible retry.
  - Only the project-history action checks that return value.
  - `MainWindow.closeEvent()`, leaving Studio, `_apply_output_set()`, audio export, and
    video render all call `flush()` and unconditionally continue.
  - The failure signal writes a small status label, but app close immediately destroys
    the UI; it neither rejects the close nor offers retry/recovery.
- Executable/static confirmation (2026-08-23): existing autosave tests prove a failed
  save returns `False` and remains pending, while direct call-site inspection found five
  production durability barriers that discard the return value. An independent harness
  already confirmed audio export dispatches when `flush()` returns `False` (Architecture
  A-004 cross-check).
- Impact: exports and renders can silently use stale Studio state; switching outputs can
  hide unsaved edits; closing after disk-full, permission, or transient I/O failure loses
  the pending project state entirely.
- Recommended direction: centralize a `flush_or_block(action)` durability gate, keep the
  current page/window open on failure, expose Retry / Export saved version / Discard,
  and persist an emergency recovery journal outside the song package before allowing
  application shutdown.

### SOL-013 - Support diagnostics redaction leaks common OAuth credential formats

- Severity: high (security/privacy)
- Area: `redact_text()` and whole-app diagnostics ZIP
- Evidence:
  - `_SENSITIVE_ASSIGNMENT` recognizes only exact bare keys such as `token=...`.
  - It misses prefixed keys (`access_token`, `refresh_token`, `client_secret`), quoted
    JSON keys, and bearer credentials after the first word of an Authorization value.
  - `build_support_archive()` includes up to 1.5 MB from each application log and relies
    on this redactor before packaging files intended to be sent to support/testers.
  - The current security test covers only `token=private-value`, which is the one form
    the expression handles correctly.
- Executable confirmation (2026-08-23): a real support ZIP built from a log containing
  all common forms removed the plain `token=` value but retained six secrets from
  `access_token=`, `refresh_token=`, `client_secret=`, quoted JSON access/client keys,
  and `Authorization: Bearer bearer-secret`.
- Impact: if an HTTP/OAuth library, exception, debug statement, or pasted diagnostic
  logs a structured credential, the user can unknowingly send a reusable Google token
  or OAuth client secret in the one-click diagnostics archive.
- Recommended direction: redact structured JSON/form/header data before formatting,
  match sensitive key suffixes with quotes and underscores, consume the entire bearer
  credential, add entropy-aware token fallback where appropriate, and test every common
  OAuth/header/JSON/query representation against the final ZIP bytes.

### SOL-014 - Shared fixed temporary filenames make "atomic" writes concurrency-unsafe

- Severity: critical
- Area: managed file writes and all JSON/text/catalog/package persistence
- Evidence:
  - `write_json_atomic()` and `write_text_atomic()` always use `<target>.tmp`;
    `copy_file_atomic()` and `link_or_copy_file()` likewise use fixed `.copying` and
    `.linking` names.
  - There is no per-path lock, unique process/thread suffix, or interprocess ownership.
  - Multiple stores perform read-modify-write without locks, and workers can update song
    package state while UI actions rename/delete the same song. RLA-001 independently
    proves multiple app processes are currently allowed to use these helpers at once.
- Executable confirmation (2026-08-23): two real `write_json_atomic()` calls were
  synchronized after both wrote the same temporary file. Writer A moved the temp first,
  but committed writer B's overwritten payload; writer B then raised
  `FileNotFoundError` because A had removed the shared temp. Thus even the reported
  successful writer did not persist its own data.
- Impact: concurrent settings, catalog, song manifest, model dataset/state, Studio,
  update, hardware, and registry saves can fail or silently commit the wrong caller's
  snapshot. Atomic replacement prevents partial bytes but does not prevent lost updates
  or cross-writer payload substitution.
- Relationship: RuntimeLogicAudit's VC-09 cross-check found a concrete multi-process
  lost-update path in the RoFormer registry; this finding is the shared primitive defect
  underneath many additional stores.
- Recommended direction: use unique same-directory temporary names, serialize each
  logical document with an in-process lock, add an interprocess lock/CAS revision for
  shared state, fsync where durability is required, and test two writers plus crash
  recovery. Unique temps alone do not solve read-modify-write loss.

### SOL-015 - Asset deletion failures commit contradictory partial state

- Severity: high
- Area: `SongAssetRemovalService` single and bulk deletion transactions
- Evidence:
  - Managed vocal-output removal detaches the output from `song.json` before deleting
    its directory. If `shutil.rmtree()` fails, the service raises after the result has
    already disappeared from the library manifest.
  - Managed video removal performs the inverse unsafe ordering: it unlinks the media
    file before clearing `video_source.json`. A state-save failure leaves durable
    metadata pointing at a path that no longer exists.
  - `remove_many()` runs these operations sequentially with no preflight, transaction,
    undo log, or aggregate partial-success result. The UI catches one exception, shows
    only `Remove failed`, and refreshes after earlier selected assets may have committed.
- Executable confirmation (2026-08-24): faulting vocal `rmtree()` produced
  `SongAssetRemovalError` while the reloaded package had zero outputs and the complete
  output directory still survived. Faulting `VideoSourceStore.clear()` produced an
  error after the video file was gone while `video_source.json` still existed and
  referenced that deleted managed path.
- Impact: a user retry cannot reason about what remains; outputs can become invisible
  protected orphans, video configuration can silently reset on load, and a bulk delete
  can remove an arbitrary prefix while claiming the whole operation failed. Storage
  recovery and support diagnostics then see metadata and files that disagree.
- Relationship: VC-14 confirms the same commit-before-unlink defect for cleanup-result
  deletion. The issue is therefore a shared deletion-transaction design problem, not
  one cleanup implementation bug.
- Recommended direction: represent deletion as a plan, atomically move managed assets
  into a same-volume quarantine, commit all metadata with revision checks, restore on
  commit failure, and delete quarantine asynchronously only after success. Bulk delete
  must return explicit per-unit outcomes or be all-or-nothing.

### SOL-016 - A stale Safe Cleanup plan can delete files owned by a newly started job

- Severity: critical
- Area: Environment & Management storage cleanup vs processing queue lifecycle
- Evidence:
  - `_refresh_storage()` builds a cleanup plan using `_has_active_jobs()` only when the
    scan worker completes. The resulting plan is cached in `DiagnosticsPage`.
  - Queue notifications refresh job history but neither invalidate nor rebuild that
    cached plan when a job starts.
  - `_confirm_cleanup()` checks only whether the plan has candidates and whether a
    cleanup worker already exists. It does not recheck active jobs before confirmation
    or worker dispatch.
  - Candidate paths include every child of `Cache/jobs`, the shared tool workspace used
    by separation/conversion and other active pipelines.
- Executable confirmation (2026-08-24): a real `DiagnosticsPage` received an idle-time
  plan for `Cache/jobs/active-run`, then its real queue started an `Active conversion`
  task. Confirmation still dispatched the stale plan while `_has_active_jobs()` was
  true; real `execute_cleanup()` removed the in-flight file with zero failures and the
  queue task remained `running`.
- Impact: opening Storage Management before starting work can make a later click delete
  an operation's input/output workspace mid-command, causing corrupt or inexplicable
  separation, conversion, sharing, analysis, or export failures. The UI explicitly
  labels this cleanup safe even though its safety decision is stale.
- Recommended direction: include resource leases in cleanup candidates, invalidate the
  plan on every queue transition, rebuild after the confirmation pause, and atomically
  acquire cleanup leases before renaming any candidate. A boolean active-job snapshot
  alone cannot close the race between the final check and `os.replace()`.

### SOL-017 - Failed Safe Cleanup strands data in an invisible permanent quarantine

- Severity: high
- Area: `execute_cleanup()` failure recovery and cleanup-plan discovery
- Evidence:
  - Cleanup first moves each candidate into a sibling `.jjzero-cleanup` directory and
    then recursively deletes the staged path.
  - If recursive deletion fails, the exception path records a failure but never moves
    the staged data back to its original location.
  - `_child_candidates()` explicitly skips `.jjzero-cleanup`, and there is no startup
    recovery/collector for abandoned staged entries.
- Executable confirmation (2026-08-24): faulting `_remove_path()` after a real atomic
  move removed the original `abandoned-run`, preserved its payload under a UUID-named
  quarantine entry, and reported that staged path as failed. A fresh
  `build_safe_cleanup_plan()` returned zero candidates and could not recover or retry
  the quarantine.
- Impact: locked files, antivirus interference, crashes, or permission faults can make
  cache data disappear from normal views without reclaiming one byte. Repeated cleanup
  attempts can accumulate unaccounted storage that the feature can never clean.
- Recommended direction: restore the original path when deletion fails; if restoration
  also fails, persist a recovery manifest and always scan quarantine entries first on
  startup/cleanup. Inventory should report quarantined bytes separately until resolved.

### SOL-018 - Google Drive share preflight performs network and filesystem work on the GUI thread

- Severity: high
- Area: `GoogleDriveController._request_share()` responsiveness
- Evidence:
  - Export/model share button handlers call `_request_share()` directly on the Qt GUI
    thread.
  - Before emitting `share_started` or constructing a `TaskWorker`, `_request_share()`
    calls `_preflight_share_error()`.
  - For a restored connected account with no cached quota, preflight synchronously calls
    `service.quota()`, which performs a Google Drive HTTP request with the client's
    default 90-second timeout.
  - Model-work preflight can then synchronously enumerate package entries and `stat()`
    every dataset/model file to estimate size before any busy/progress signal exists.
- Executable confirmation (2026-08-24): a real offscreen controller with a 350 ms quota
  service made `open_export_share()` block for 0.352 seconds. A Qt timer scheduled for
  10 ms had not fired when the call returned; only afterward did `share_started` emit,
  the upload worker register, and event processing resume.
- Impact: a slow/offline Drive endpoint, credential refresh, network drive model path,
  or very large training workspace can make the whole app appear hung before the share
  progress UI becomes visible. Repeated clicks cannot be processed during the stall and
  Windows may mark the window unresponsive.
- Recommended direction: make quota/size preflight the first cancellable worker phase,
  emit busy state before dispatch, cache quota only as an optimization, and return a
  typed preflight result that transitions into packaging/upload without returning to a
  second synchronous GUI-thread scan.

### SOL-019 - A partially failed managed-model deletion destroys model artifacts during rollback

- Severity: critical
- Area: `RvcModelWorkspace.remove_model()` multi-directory deletion transaction
- Evidence:
  - Managed deletion first removes the catalog record, then deletes the owned library
    package followed by the separate model work directory.
  - If any later deletion raises, the handler restores catalog visibility by calling
    `_save_records(..., record)` but does not restore already deleted directories.
  - `_save_records()` runs `_ensure_managed_package()` for the restored record. When
    the library package was already deleted, it recreates an empty RVC directory tree
    and retains artifact paths that now point to missing files.
- Executable confirmation (2026-08-24): a real created model was populated with an
  inference PTH, index, and matching G/D checkpoints. Deleting its package succeeded,
  deletion of the work directory was faulted as locked, and `remove_model()` raised.
  The catalog record and an empty package directory were recreated with status
  `missing`; the inference model and both checkpoints were permanently gone while the
  later work directory survived.
- Impact: a Windows lock, antivirus scan, active analysis, or worker holding only the
  second directory can turn a user-visible failed delete into irreversible loss of a
  trained model. The attempted rollback makes the model look recoverable but preserves
  only broken references.
- Relationship: SOL-015 proves the same false rollback contract for song assets, while
  SOL-006 proves model workers can be the lock/write source during deletion.
- Recommended direction: pre-acquire model task/resource leases, atomically rename all
  owned roots into a common transaction quarantine before removing the catalog record,
  restore every renamed root on any failure, and delete the quarantine only after the
  catalog commit. Never reconstruct deleted packages as rollback.

### SOL-020 - Failed model-work import leaves a ghost catalog record that blocks retry

- Severity: high
- Area: `model_work_share_package._install_imported_package()` rollback
- Evidence:
  - Import copies model and dataset trees, registers the managed model in the workspace
    catalog, and only then validates the imported dataset by loading it.
  - If that final validation fails, the exception handler deletes both copied trees but
    never removes the record already committed by `register_imported_managed_record()`.
  - A new `RvcModelWorkspace` instance subsequently runs managed-package migration for
    the orphan record and recreates an empty package with `model.json`.
- Executable confirmation (2026-08-24): a real model-work ZIP was created and imported
  while only the post-registration dataset load was faulted. Import raised, yet the
  target catalog retained one record while model/dataset directories were absent. On
  simulated restart, the workspace recreated a package containing only `model.json`;
  retrying the original valid ZIP failed with `A model with this work package already
  exists`, and the dataset remained absent.
- Impact: transient validation/I/O failure produces a model the user never successfully
  imported, prevents one-click retry, and can be mistaken for a corrupt shared model.
  Automated import retries cannot self-heal and repeated cleanup may interact with the
  destructive rollback defect in SOL-019.
- Recommended direction: validate the extracted dataset before catalog registration,
  stage both roots under unique temporary IDs, then commit roots and catalog as one
  revisioned transaction. If registration must occur first, explicitly remove the exact
  generation on rollback and verify rollback before deleting staged data.

### SOL-021 - A failed whole-song deletion can destroy source audio while leaving the song active

- Severity: critical
- Area: `SongPackageStore.remove_managed_data()` destructive transaction
- Evidence:
  - Full deletion constructs a tombstone in memory but first iterates every package
    entry and permanently unlinks/rmtrees it; `song.json` is saved as removed only after
    all destructive operations finish.
  - There is no quarantine, rollback, deletion journal, or per-entry outcome if one
    later stage is locked.
  - `SongLibrary.remove_item()` catches only `KeyError`; MainWindow catches the escaping
    I/O error and displays `Delete failed`, leaving the unchanged active manifest to be
    loaded normally.
- Executable confirmation (2026-08-24): a real imported song was deleted while only
  `02_vocal` was faulted as locked. Removal raised `OSError`, but the preceding
  `01_source` tree and managed source WAV were already gone. A fresh store still loaded
  `removed=false` with the deleted source path, and a fresh library displayed one song
  whose item path did not exist.
- Impact: a failed delete can irreversibly destroy original managed audio and an
  arbitrary prefix of outputs while telling the user nothing was deleted. The broken
  visible song can then fail playback, separation, conversion, Studio restoration, and
  later deletion in different ways.
- Relationship: SOL-003/SOL-010 cover late writers recreating a successfully deleted
  package; SOL-021 is the opposite failure where deletion itself only partially commits.
- Recommended direction: stop and lease all song-owned work, atomically rename all
  managed stages into a transaction quarantine, commit the tombstone, then purge. On
  any failure restore every staged root before reporting failure, with a persistent
  recovery journal for crash/interruption.

### SOL-022 - Resume startup deletes the last known-good checkpoint before validating its replacement

- Severity: critical
- Area: `rvc_training_train._keep_latest_checkpoint_pair()` resume compaction
- Evidence:
  - Every training start calls `_keep_latest_checkpoint_pair()` before the selected
    checkpoint is loaded by RVC.
  - The function treats matching `G_<step>.pth` and `D_<step>.pth` filenames as proof
    of validity, chooses the numerically largest shared step, and permanently unlinks
    every older generator and discriminator checkpoint.
  - Checkpoint structure, readability, paired epoch metadata, and model compatibility
    are not inspected until the external trainer later attempts to load the retained
    files. A partial/corrupt but atomically named latest pair therefore destroys the
    only loadable fallback before its own validation can fail.
- Executable confirmation (2026-08-24): an experiment containing a known-good
  `G_100/D_100` pair and a simulated corrupt `G_200/D_200` pair was compacted to only
  step 200. State selected step 200 and both step-100 files no longer existed before
  any trainer/checkpoint loader ran.
- Impact: disk corruption, an incompatible update, or semantically incomplete latest
  pair can make resume fail and simultaneously erase earlier recoverable training
  progress. The explicit checkpoint-load failure guard prevents a silent epoch-zero
  restart, but cannot recover because the good fallback was already deleted.
- Recommended direction: retain at least the latest two complete pairs, validate a
  candidate in an isolated worker before promotion, persist a known-good checkpoint
  pointer, and move superseded pairs to recoverable history only after a successful
  resumed batch/checkpoint commit.

### SOL-023 - Training can be durably marked complete before its index and catalog registration exist

- Severity: high
- Area: training pipeline/finalization commit boundary
- Evidence:
  - `train_rvc_model()` records the target epoch and writes phase `COMPLETE` as soon as
    the RVC trainer produced its PTH and G/D pair.
  - `run_rvc_training_pipeline()` builds the search index only afterward, and
    `ModelWorkspacePage._run_training_job()` registers artifacts in the model catalog
    after the pipeline returns.
  - Ordinary Qt worker failures are later repaired to `FAILED` by the GUI failure
    callback, but the service pipeline itself has no general-exception state rollback.
    Process termination, power loss, page destruction, or a non-UI caller between
    these commits leaves the durable phase at `COMPLETE` with no index/registration.
  - `recover_existing_rvc_training_artifacts()` accepts only phase `FAILED`; the next
    run therefore skips recovery. Training with the same target is then rejected
    because `target_epoch <= current_epoch`.
- Executable confirmation (2026-08-24): a real managed state with epoch 20, valid model
  and G/D files, phase `COMPLETE`, and no index returned no recovery result; target 20
  was no longer a legal next training target.
- Impact: a crash in the short post-training window can strand expensive completed
  training in a state where the advertised checkpoint recovery button cannot finish
  registration. Users must train extra epochs or manually alter state even though the
  trained model already exists.
- Recommended direction: introduce explicit `MODEL_READY`, `INDEX_READY`, and
  `REGISTERED/COMPLETE` phases; make finalization idempotent for every post-training
  phase; commit `COMPLETE` only after model inspection, index validation, and catalog
  registration all succeed. Recovery should inspect artifacts rather than require the
  exact `FAILED` phase.

### SOL-024 - Failed song import leaves an invisible protected source copy

- Severity: high
- Area: `SongPackageStore.import_audio()` create transaction
- Evidence:
  - A new import creates all stage directories and atomically copies the source audio
    before writing `song.json`.
  - If manifest persistence fails, there is no exception cleanup or import journal;
    package discovery is manifest-only and therefore cannot expose the copied file.
  - The entire library category is intentionally `protected`, so Safe Cleanup never
    proposes manifestless song package directories.
- Executable confirmation (2026-08-24): faulting only `_save()` after a real source
  copy raised `OSError`. A fresh package scan returned zero songs and no `song.json`,
  while `01_source/audio/source.wav` remained under the managed song root.
- Impact: disk-full/permission/atomic-write failure can consume another full source
  copy without any library row or cleanup entry. Large repeated imports can exhaust the
  selected data drive, and support diagnostics cannot associate the orphan with a song.
- Recommended direction: copy into a uniquely named import staging root, write and
  validate the manifest there, atomically promote the complete package, and collect
  stale staging roots on startup. At minimum delete the exact new package on save
  failure while preserving a failed-cleanup diagnostic.

### SOL-025 - Failed model import leaves an invisible protected model package

- Severity: high
- Area: `RvcModelWorkspace._import_discovered()` create transaction
- Evidence:
  - Managed package directories are created and all selected PTH/index/checkpoint files
    are copied before the model catalog is saved.
  - Neither copy failure nor catalog-write failure removes newly created package roots;
    `records()` discovers models only through the catalog, not package contents.
  - Models/training work is a protected storage category and Safe Cleanup excludes it.
- Executable confirmation (2026-08-24): faulting `_save_records()` after a real PTH
  import left `library/managed-*/rvc/weights/Voice.pth`, but a new workspace returned
  zero records and no catalog file.
- Impact: inference models and especially multi-gigabyte checkpoint workspaces can be
  duplicated invisibly after disk-full, concurrent catalog failure, or interrupted
  import. Retry may reuse the deterministic directory, but abandonment and changed
  source identity leave no in-app recovery/removal path.
- Recommended direction: stage each package with a transaction ID, validate complete
  copies before a single catalog commit, atomically promote only committed packages,
  and surface/recover unregistered packages at startup rather than silently protecting
  them forever.

### SOL-026 - A failed managed-model artifact replacement may already overwrite the active model

- Severity: high
- Area: `RvcModelWorkspace.replace_artifact()` mutation ordering
- Evidence:
  - Managed replacement copies the selected artifact directly into the live package
    before `_replace_record()` commits the new record.
  - There is no backup, staging generation, or cleanup if the catalog/manifest commit
    fails after that copy.
  - If the replacement has the same filename as the current artifact, atomic copy
    replaces the bytes at the path already referenced by the old catalog. If it has a
    different name, the old record remains while an unreferenced copy is retained.
- Executable confirmation (2026-08-24): faulting `_replace_record()` after copy with a
  same-name `Voice.pth` raised `OSError`, but a fresh workspace's still-old record read
  `REPLACED` bytes. Repeating with `Other.pth` retained both files while the catalog
  continued to point only to `Voice.pth`.
- Impact: the UI can say replacement failed while conversion silently starts using a
  different model, invalidating reproducibility and potentially pairing it with the
  old index. Different-name failures leak potentially large model/checkpoint files in
  protected storage.
- Recommended direction: copy and validate into a generation-specific staged path,
  commit the catalog pointer atomically, then retire the prior generation. Same-name
  replacements must never write the currently referenced inode/path before metadata
  commit, and rollback must be independently verified.

## Deferred verification backlog

These are explicitly **not confirmed findings**. They were not fully exercised before
the first remediation pass began. Revisit them after the confirmed critical/high
findings are fixed, and promote only with an executable reproduction.

### P0 - Security and irreversible-state boundaries

1. **Shared ZIP import containment and resource limits**
   - Files: `model_share_package.py`, `model_work_share_package.py`.
   - Verify mixed `/` and `\\` traversal on Windows, drive/UNC/device names, duplicate
     ZIP members, case-equivalent targets, manifest-size versus `ZipInfo.file_size`,
     extreme compression ratio, total extracted-byte limits, and free-space preflight.
   - The interrupted audit specifically reached `extraction_root /
     PurePosixPath(archive_path)` in model-work import; backslashes are not rejected by
     that validator and require a real Windows escape-path probe.
2. **Crash recovery and startup reconciliation**
   - Kill the process after every file copy, rename, manifest write, catalog write, and
     SQLite update for song/model create, import, replace, delete, and finalization.
   - Define recovery for manifestless packages, catalog-only records, quarantines,
     run backups, staging directories, and files referenced by only one metadata store.
3. **Checkpoint semantic validation and recovery generations**
   - Exercise unreadable G/D files, internally mismatched epochs despite matching
     filenames, model-version mismatch, one corrupt latest pair with an older valid
     pair, interruption after first resumed batch, and every model/index/registration
     commit boundary.
4. **Cleanup time-of-check/time-of-use safety**
   - Swap candidates with files, symlinks, and Windows junctions after planning and
     after `_candidate_is_safe()` but before rename/removal.
   - Verify startup restoration of `.jjzero-cleanup`, task-resource leases at execute
     time, and cancellation/power-loss behavior during recursive removal.
   - Source-level reparse-point and execute-time revalidation is now covered by
     Range 18; live Windows junction and power-loss probes remain open.
5. **Application shutdown ownership**
   - Close during each generic command, training stage, telemetry, model analysis,
     Drive upload/download, storage scan/cleanup, waveform generation, and success
     callback. Assert no process/thread survives and no post-close write occurs.

### P1 - Consistency and responsiveness

6. **Catalog/manifest/SQLite reconciliation under concurrent processes**
   - After fixing shared atomic writers, run two app processes through song/model/group
     mutations and inject corruption or stale revisions into each persistence layer.
   - Verify deterministic conflict resolution instead of silent record loss or
     resurrection.
7. **Waveform and analysis executor backlog**
   - Rapidly switch many songs/models while old analysis is blocked. Measure whether
     stale uncancellable jobs occupy all global executor slots and delay the newest
     visible result; verify deduplication and generation cancellation.
   - Waveform requests are now owned and cancelable across the four interactive
     waveform surfaces in Range 17; analysis-executor measurement remains open.
8. **Diagnostics/environment page worker lifecycle**
   - Close or switch pages during PC/RVC/storage scans, cleanup, and ZIP generation;
     verify stale signals cannot update destroyed/new widgets and workers are joined.
9. **Google Drive partial remote state**
   - Cancel or disconnect during resumable upload, permission creation, metadata save,
     replacement, and remote delete. Reconcile uploaded files whose local share record
     was never committed and local records whose Drive object no longer exists.
10. **Storage relocation and migration interruption**
    - Fault cross-volume copy, verification, settings commit, and old-root cleanup at
      every step. Test legacy layouts and skipped-version upgrades with locked files and
      insufficient space, preserving one authoritative root after restart.

### P2 - Product-state and scale coverage

11. **Library grouping/filter/active-song state**
    - Group storage received static review and no finding was promoted. Still test
      deleting parent/selected groups, stale memberships, drag/drop during refresh,
      active songs hidden by filters, and two-window/process edits.
12. **Large-library and long-session resource behavior**
    - Benchmark tens of thousands of songs/results, large model workspaces, multi-hour
      logs, repeated page navigation, preview caches, and signal/subscriber growth for
      memory, startup latency, and UI starvation.

## Candidates under verification

- Dataset-load stale-result handling was inspected and currently rejects results whose
  model ID is no longer selected; no issue promoted.
- Mixed-separator traversal in shared model-work ZIP extraction was identified by
  static inspection but intentionally left unconfirmed and belongs to P0 item 1.

## Cross-check log

- 2026-08-23 23:05 KST: `Problem/Main.md` was empty and no other session file was
  present. No shared lock was held.
- 2026-08-23 23:16 KST: found conflicting lock declarations in `Main.md`; no shared
  edit attempted. Narrowed this session to asynchronous lifecycle and diagnostic
  state consistency to avoid the runtime/update and architecture sessions.
- 2026-08-23 23:18 KST: executable probes confirmed SOL-001 and SOL-002.
- 2026-08-23 23:21 KST: a real package deletion/autosave race confirmed SOL-003.
- 2026-08-23 23:24 KST: actual `run_command()` process ownership probe confirmed
  SOL-004 on Windows.
- 2026-08-23 23:27 KST: deterministic model-switch and post-delete cache probes
  confirmed SOL-005 and SOL-006.
- 2026-08-23 23:41 KST: independently cross-checked Architecture A-004. A harness whose
  Studio autosave `flush()` returned `False` still dispatched `Export Mix`, confirming
  that export proceeds from stale persisted state after a flush failure.
- 2026-08-23 23:45 KST: real queue/diagnostics and Qt worker probes confirmed SOL-007
  and SOL-008.
- 2026-08-23 23:49 KST: a real offscreen precise-evaluation panel probe confirmed
  SOL-009; static inspection found the same asymmetric guard in material analysis.
- 2026-08-23 23:55 KST: a real song-package deletion/late-separation-write probe
  confirmed SOL-010.
- 2026-08-24 00:02 KST: streaming-output memory probes confirmed SOL-011; Studio flush
  call-site audit and the earlier export harness confirmed SOL-012.
- 2026-08-24 00:07 KST: final support-ZIP inspection confirmed SOL-013 with six leaked
  OAuth credential representations.
- 2026-08-24 00:11 KST: an ordered two-writer probe confirmed SOL-014, including both
  payload substitution and a failing second writer.
- 2026-08-24 00:20 KST: merged SOL-001 through SOL-014 into `Main.md`; overlapping
  root causes were consolidated with A-004 and RLA-012, then the shared lock was
  released.
- 2026-08-24 00:27 KST: real vocal-output and video fault probes confirmed SOL-015's
  opposite mutation-order failures and persistent metadata/file disagreement.
- 2026-08-24 00:34 KST: real DiagnosticsPage/queue and quarantine fault probes confirmed
  SOL-016 and SOL-017, including deletion of a running task's file and a zero-candidate
  follow-up scan for stranded quarantine data.
- 2026-08-24 00:39 KST: a Qt timer/slow-quota probe confirmed SOL-018's GUI-thread
  network block occurs before share-start feedback or worker dispatch.
- 2026-08-24 00:46 KST: a real managed model with inference/index/G/D artifacts confirmed
  SOL-019; faulting only the second directory deletion left the operation failed but
  destroyed all trained artifacts and recreated an empty `missing` package.
- 2026-08-24 00:52 KST: a real model-work round trip with a faulted final validation
  confirmed SOL-020; restart recreated a manifest-only ghost and the valid ZIP could no
  longer be retried because its ID was already catalogued.
- 2026-08-24 00:57 KST: a real song-package deletion with only the second stage locked
  confirmed SOL-021; the source WAV was destroyed while the active manifest and visible
  library row survived with a missing path.
- 2026-08-24 01:10 KST: checkpoint-compaction and interrupted-finalization probes
  confirmed SOL-022 and SOL-023. Resume deleted a known-good older pair before loading
  its corrupt successor, while a model/checkpoint set durably marked `COMPLETE` without
  an index was neither recoverable nor eligible for a same-target retry.
- 2026-08-24 01:19 KST: post-copy persistence fault probes confirmed SOL-024 and
  SOL-025. Both song and model import left complete managed source copies in protected
  storage while fresh discovery returned zero visible records.
- 2026-08-24 01:23 KST: managed artifact replacement probes confirmed SOL-026. A
  reported catalog failure still changed the bytes at the active inference path for a
  same-name replacement; a different-name replacement leaked an unreferenced PTH.
