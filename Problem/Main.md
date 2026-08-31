# JJZero Audio Problem Audit

## Main.md edit lock

- Status: unlocked
- Owner: none
- Since: 2026-08-27 17:07 KST
- Rule: only the owner may edit `Main.md` while this status is `locked`.

## Collaboration protocol

1. Each session records investigation details in its own Markdown file.
2. Before editing `Main.md`, confirm the lock is `unlocked`, then set it to `locked`
   with the session name and timestamp.
3. Only evidence-backed findings are merged here. Candidates stay in session files.
4. Release the lock immediately after merging by setting its status to `unlocked`.
5. Never rewrite or remove another session's findings without recording the reason.

## Session index

- `Sol.md`: asynchronous lifecycle, shared UI state, storage/data safety,
  runtime/update boundaries, diagnostics.
- `Session-Architecture-Audit.md`: domain boundaries, persistence invariants,
  service/API contracts, and structural duplication.
- `VocalCleanupAudit.md`: vocal cleanup, separation post-processing, managed
  model assets, preview/apply consistency, and audio quality invariants.
- `RuntimeLogicAudit.md`: startup ownership, hardware diagnostics caching,
  runtime installation safety, disk usage, and update lifecycle.
- `Atlas.md`: release manifests, component/package identity, public asset
  integrity, updater recovery, and startup observability.
- `Session-External-Input-Audit.md`: external input boundaries and conversion
  result state consistency.

## Confirmed findings

### Critical

- **RLA-010 - Auto-update executable trust is optional and weakly matched.** The
  current 0.3.10 installer is unsigned and its manifest does not require a
  signature. Even when enabled, publisher verification accepts any valid subject
  containing the configured text, including misleading prefixed/suffixed names.
- **ATLAS-14 - Uninstall can recursively erase unrelated files in custom Runtime
  and Cache roots.** Custom category paths are accepted without an ownership
  marker, then the uninstaller recursively deletes each configured root after only
  a broad path check. Unknown user files added after setup are neither preserved nor
  covered by the uninstall regression tests.
- **ATLAS-01 - Runtime upgrades can report a new version while retaining stale
  RVC executables.** The base installer preserves all of `rvc/runtime` over newly
  extracted files. Two independent probes installed version 2 while the old
  `python.exe` bytes remained active.
- **VC-02 - Failed cleanup-region replacement can destroy committed audio.**
  Replacement overwrites the files referenced by the active manifest before save;
  the rollback deletes those targets while the old manifest remains. Fault
  injection restored one manifest region with both media files missing.
- **VC-04 - Cleanup render completion can discard edits made while rendering.**
  The asynchronous success callback saves its captured aggregate snapshot. A
  reproduced interleaving added a second region, then result registration shrank
  the manifest back to one and orphaned the new segment file.
- **VC-08 - Effect removal moves removed original-vocal effects into the backing.**
  Vocal-preserving mixture consistency sends `source - cleaned vocal - backing`
  entirely to the backing. A synthetic run transferred the removed `0.2` echo/
  reverb component into `no_vocals.wav` while reporting zero residual.
- **A-002 - One missing media asset replaces the entire edited video track.**
  Restoration preserves a media track only when every reference resolves. A
  two-clip probe lost both clip identities, valid timing edits, and track volume
  after one reference became unavailable.
- **A-003 - Export silently omits unavailable audible clips.** A real package with
  two audible clips and one missing file returned one mix source without error;
  both audio and video export can report a partial soundtrack as complete.
- **A-004 / SOL-012 - Studio durability failures do not block destructive or
  stale-state actions.** Both export paths dispatch after `flush() == False`, and
  navigation, output switching, video render, and app close ignore the same failure.
  A fault probe still dispatched export from the previous disk session; disk-full or
  permission failures can therefore lose edits or produce stale successful outputs.
- **A-007 - Video export silently omits missing visual clips.** With two imported
  PNG timeline clips and one managed file deleted, render capability stayed enabled
  and the bundled FFmpeg successfully produced a one-clip MP4.
- **A-009 - Video export truncates visuals to the audio-mix duration.** A real
  package with a one-second audible clip and a three-second imported PNG rendered
  a 1,000 ms MP4 with the bundled FFmpeg, silently deleting the final two seconds
  of the visual timeline.
- **SOL-003 - In-flight Studio autosave can recreate data after song deletion.** A
  paused real save that had already acquired the package recreated `03_studio` after
  managed deletion because `discard()` invalidates pending work but not in-flight
  generations.
- **SOL-004 - App close leaves ordinary worker process trees alive.** Generic
  separation, conversion, FFmpeg, download, cleanup, export, and update workers are
  neither cancelled nor joined. A real `run_command()` child survived its parent app
  process, so it can keep using GPU/CPU and writing after the user closes the app.
- **SOL-005 - Late material-edit results can replace another model's visible
  dataset.** Switching from model A to B while A's worker was held ended with B
  selected but A's dataset rendered; several worker lambdas also read the live model
  ID and can redirect the underlying mutation to the wrong model.
- **SOL-010 - Deleting a song during an owned task recreates hidden package data.**
  Song deletion has no task-ownership barrier. A late separation write recreated
  `02_vocal` under the deleted package, registration failed, and the inaccessible
  output survived while the song remained absent from the library.
- **SOL-016 - A stale Safe Cleanup plan can delete files of a newly running job.**
  Storage scan snapshots active-job state once, queue changes do not invalidate the
  plan, and confirmation does not recheck. An offscreen probe built an idle plan,
  started a job, then deleted that job's live cache file through the stale plan.
- **SOL-019 - Partial model deletion can destroy all trained artifacts while
  reporting failure.** The package is deleted before the work root; faulting only
  the latter restored the catalog but recreated an empty `missing` package after
  inference, index, and G/D artifacts were permanently removed.
- **SOL-021 - Failed whole-song deletion can destroy the source while leaving the
  song active.** Package stages are permanently deleted before the tombstone is
  saved. Faulting only the vocal-stage deletion removed the managed source WAV but
  left an active visible manifest pointing at the missing file.
- **SOL-022 - Resume deletes the last known-good checkpoint before validating its
  replacement.** Startup keeps only the numerically newest filename-matched G/D
  pair before loading it. A corrupt step-200 pair caused valid step-100 files to be
  permanently deleted before the trainer had a chance to reject step 200.

### High

- **RLA-001 - The named mutex does not enforce a single app instance.** Windows
  reports `ERROR_ALREADY_EXISTS`, but startup ignores it and continues. Two app
  processes can concurrently mutate JSON, SQLite, runtime, and update state.
- **ATLAS-02 / RLA-002 - A complete `.part` download can enter a permanent retry
  failure.** Exact-size partials are not verified locally; they request an EOF
  range and can repeat HTTP 416 or offline failure until cache removal.
- **RLA-003 - Runtime installation has no free-space preflight.** Multi-gigabyte
  archives, staging extraction, and the previous runtime can coexist, so users can
  fail only after long downloads with peak use far above the displayed size.
- **ATLAS-03 - Artifact identity is lost when components reuse a filename.** The
  manifest accepts different hashes under the same name and the installer maps by
  basename, causing both components to receive the last path.
- **ATLAS-04 / RLA-007 - One discovered update freezes future manifest polling.**
  A pending plan stops all periodic checks, so corrected URLs, newer releases, and
  remote feature policy are not observed until app restart.
- **RLA-005 - Recent diagnostics suppress live GPU-change detection.** For seven
  days startup returns before hardware probing; a reproduced CPU-to-AMD change
  made zero detection calls and retained the old selection.
- **RLA-006 - Failed diagnostics are cached as if recheck were unnecessary.** A
  recorded `ready=False` result immediately returned `recheck_required=False`, so
  closing a failed repair flow can suppress it for seven days.
- **RLA-008 - App and runtime updates are not one compatibility transaction.** A
  real combined-plan probe committed runtime version 2, then failed installer
  launch; the old app stayed open on the new runtime with no rollback path.
- **RLA-011 - A forced exit during runtime swap strands a complete rollback.** A
  complete version-1 tree left in `.runtime.previous` was ignored by normal startup
  repair while the live root stayed absent, forcing a multi-gigabyte reinstall
  instead of an atomic local restore.
- **RLA-012 / SOL-014 - Shared atomic writers are unsafe under concurrency.** All 76
  JSON call sites share one deterministic `.tmp` path per target, and text/copy/link
  helpers repeat the pattern. Concurrent probes produced malformed/lost registry
  state; an ordered two-writer probe also made a successful writer commit the other
  caller's payload before the second failed with `FileNotFoundError`.
- **ATLAS-08 - Runtime backup cleanup can report failure after the new runtime is
  already committed.** A post-swap deletion fault left the new active runtime and
  old backup in place while installation returned an error, so retry begins from a
  state that contradicts the UI and may consume several extra GB.
- **ATLAS-10 - The release version is not bound to the application component.** A
  manifest with root `9.0.0` and application `1.0.0` passed parsing and selected the
  `1.0.0` installer for an `8.0.0` client, allowing downgrade and a repeated update
  loop if a release manifest is assembled incorrectly.
- **ATLAS-11 - A stale manifest can downgrade runtimes beneath a newer app.** An app
  `0.3.10` probe with runtime/profile `4`/`2` accepted a release `0.3.0` manifest and
  selected runtime/profile `3`/`1`; only the application version uses monotonic
  comparison, while engine components treat every inequality as an update.
- **ATLAS-12 - Release artifacts are not bound to the tagged source revision.** The
  ignored `dist/` tree can be reused with `-SkipAppBuild`, publication only checks the
  current worktree is clean, and no binary or manifest records the build commit. A
  tag and patch notes can therefore claim fixes absent from the shipped executable.
- **VC-01 - Accepted cleanup regions cannot be edited or chained.** Activating a
  saved region restores only its time range; every preview includes that same
  region in an unconditional overlap rejection. The dormant replacement ID is not
  connected to the application flow.
- **VC-03 - Managed model readiness/integrity checks are inconsistent and weak.**
  A one-byte 127 MB model was displayed as ready. Preparation also accepted a
  same-size checksum-corrupt checkpoint without downloading or rejecting it.
- **VC-06 - Hidden 0.9 model normalization can lower only cleaned ranges.** The
  real de-echo composition path with an identity model rule changed a selected
  peak from `1.0` to `0.9` (`-0.915 dB`).
- **VC-09 - Concurrent first-use model preparation loses registry entries.** Two
  synchronized model registrations both succeeded, but the unlocked shared
  read-modify-write left only one model in `download_checks.json`.
- **VC-10 - A missing cleaned-vocal file becomes invisible and blocks later
  edits.** The store reloads the missing result, the UI filters it out, and every
  later mutation rejects the hidden record. A real store/widget probe showed no
  removable card and then failed a valid new preview import with
  `Cleanup result is missing.`
- **VC-11 - Cleanup playback and Apply can silently target different audio.**
  Selecting a saved result after creating a preview changes the audible processed
  path but leaves the pending preview and Apply button active. The user can approve
  an old result while the application commits the unheard new preview.
- **VC-13 - Interrupted cleanup previews accumulate large invisible protected
  files.** Each preview creates two full-duration FLOAT WAVs inside the song's
  managed `cleanup/.preview` tree. Orphaned preview generations have no startup
  collector and are excluded from Safe Cleanup; a four-minute stereo preview pair
  alone is about 161.5 MiB.
- **VC-15 - Failed separation runs leave invisible stems in protected library
  storage.** Engines publish final stems before the run manifest and library record
  are committed, while failure handling performs no cleanup. A real late-manifest-
  fault probe left both 32 MiB stems with no manifest and zero Safe Cleanup
  candidates.
- **A-001 - An existing empty required track is never populated by a later RVC
  result.** Role-only reconciliation sees the empty converted-vocal track as
  complete and discards the newly populated default, leaving the result only in the
  pool after reload.
- **A-005 - Realtime preview and export order gain around nonlinear FX
  differently.** An overdrive probe at 10% volume measured preview/export RMS of
  `0.074738`/`0.342997` (4.589x), so monitoring cannot predict the rendered tone or
  loudness.
- **A-006 - Video source audio ignores the media track mix state.** Muted 0% hard-
  left and normal 100% media tracks generated identical visual inputs and FFmpeg
  filters; a visibly silent track can reappear at unity gain in the final video.
- **A-008 - Studio session and asset manifest do not share a revision.** A commit
  failure and a normal history restore both produced a session that referenced a
  missing clip while `missing_asset_ids` was empty, suppressing the safety warning.
- **A-010 - Video export is enabled for projects the renderer always rejects.** A
  valid imported PNG plus a valid but muted vocal returned `can_render=True`, then
  failed immediately because the video renderer unconditionally requires at least
  one audible mix source. Capability and execution use contradictory validation.
- **A-011 - Realtime preview reorders reverb ahead of nonlinear FX.** Preview
  globally bakes all reverbs and leaves all other effects live, discarding declared
  chain order. `(distortion, reverb)` and `(reverb, distortion)` produced identical
  preview tracks/chains, while offline output differed by up to `0.9387` with RMS
  `0.3592` versus `0.6097`.
- **SOL-001 - Jobs are persisted as completed before success finalization.** A real
  `TaskWorker` whose result callback raised left both queue and diagnostics completed;
  catalog/manifest registration and result validation can fail after the only durable
  status has already claimed success.
- **SOL-002 - One throwing queue listener can strand an unreturnable running job.**
  A subscriber exception escaped `start()` after the task and diagnostics record were
  created, so the caller received no task ID while a permanent running task remained
  and later listeners were skipped.
- **SOL-006 - Background model analysis can recreate a deleted workspace.** Task
  ownership is checked only for the selected model. Switching away from model A,
  deleting it, and releasing A's analysis recreated its root and cache despite the
  successful deletion.
- **SOL-007 - Repeated identical progress values amplify synchronous writes and UI
  refreshes.** Twenty thousand `32%` updates caused 20,000 summary replacements,
  event appends, and subscriber notifications, taking 21.577 seconds and growing the
  event log to 3.34 MB without changing visible progress.
- **SOL-008 - Model auxiliary workers survive workspace shutdown.** The shutdown
  routine waits for training, telemetry, and dataset loading only. A real material
  worker remained running after shutdown returned, allowing post-close writes and
  `QThread` destruction races.
- **SOL-009 - Stale analysis/evaluation signals overwrite the newly selected model
  UI.** Success has a model-identity guard but progress, stage, detail, and failure do
  not. Late A signals changed B's progress to 73 and displayed A's failure on B.
- **SOL-011 - Streaming commands retain output one character at a time.** The real
  reader used about 95 MiB peak memory for a 10 MiB stream before downstream copies;
  verbose RVC/FFmpeg commands scale memory and Python overhead with lifetime log size.
- **SOL-013 - Diagnostics ZIP redaction leaks common OAuth credentials.** A final ZIP
  probe retained six secrets represented as access/refresh tokens, client secrets,
  quoted JSON keys, and a bearer header while only the exact bare `token=` form was
  removed.
- **SOL-015 - Song asset deletion failures commit contradictory partial state.**
  Vocal removal detaches metadata before deleting media, while video removal deletes
  media before clearing metadata. Fault probes respectively left invisible protected
  audio and a persistent video record pointing to a deleted file.
- **SOL-017 - Failed Safe Cleanup strands invisible quarantine data.** Cleanup first
  moves candidates into `.jjzero-cleanup`, but a deletion failure neither restores
  nor rediscoveres them. The next scan returned zero candidates while the payload
  remained hidden in protected storage.
- **SOL-018 - Google Drive share preflight blocks the Qt GUI thread.** Quota HTTP
  access and full model-work size enumeration occur before busy state or worker
  dispatch. A 350 ms fake quota call blocked a 10 ms Qt timer until the share method
  returned; the real network timeout is 90 seconds.
- **SOL-020 - Failed model-work import leaves a ghost record that blocks retry.**
  Registration precedes final dataset validation, but rollback deletes only copied
  roots. A faulted validation left a catalog entry that restart converted into a
  manifest-only model, after which the original valid ZIP was rejected as duplicate.
- **SOL-023 - Training can be durably marked complete before index and catalog
  registration exist.** The training function commits `COMPLETE` before index build
  and final registration. A complete-phase model/G-D set without an index was neither
  accepted by artifact recovery nor eligible for a same-target retry.
- **SOL-024 - Failed song import leaves an invisible protected source copy.** Source
  audio is copied before `song.json` is committed. A faulted manifest save left zero
  visible songs but retained the managed WAV in a library category excluded from Safe
  Cleanup.
- **SOL-025 - Failed model import leaves an invisible protected model package.** PTH,
  index, and checkpoint copies precede catalog commit with no rollback. A faulted
  catalog save left zero model records while the managed PTH survived in protected
  storage.
- **SOL-026 - Failed model artifact replacement may already overwrite the active
  model.** Copy precedes record commit. A same-name replacement changed the bytes at
  the still-referenced inference path despite a reported catalog failure; a different
  name leaked an unreferenced PTH.

### Medium

- **UI-STATE-01 - Cleared RVC result selection was restored by refreshes.**
  Session, result-pool, and timeline layers each treated an intentional `None`
  selection as uninitialized and independently restored an old, active, or first
  take. Input and audible result could disagree. Fixed in `f54e78a` with durable
  cleared state and one selection owner.
- **UI-STATE-02 - A late conversion from a previous input could replace the current
  preview.** Completion ownership checked only the song ID, so changing from the
  original vocal to a cleanup/split vocal while conversion ran still allowed the
  old input's result to auto-select. The current worktree now verifies choice ID,
  source path, and source result before monitoring while still registering the file.
- **RLA-004 - Runtime ZIP validation ignores Windows-equivalent paths.** Archive
  members differing only by case passed duplicate checks although they overwrite
  the same Windows destination; trailing-dot/space and device aliases are likewise
  outside the current normalization contract.
- **ATLAS-05 - Release publication checks reused assets by size, not GitHub
  SHA-256.** GitHub exposes digests and current assets match, but a future same-size
  replacement or corruption can pass the release gate and fail only on clients.
- **ATLAS-06 - Background worker failures are absent from the general app log.**
  Full details exist only in per-job diagnostics; common support logs cannot explain
  or correlate the failure if that directory is not supplied.
- **ATLAS-07 - Startup timing labels interactive setup as application creation.**
  Field logs report several-minute `application_created` durations because setup,
  repair, and diagnostics occur before the mark and before useful phase logging.
- **RLA-009 - Artifact downloads have no declared-size write limit.** A 4-byte
  artifact response wrote all 32 supplied bytes while progress stayed at 100%; an
  oversized or unbounded response can fill the cache volume before verification.
- **ATLAS-13 - Silent in-app updates close the app without relaunching it.** The
  updater passes `/SILENT /RUN`, but the only installer launch entry is marked
  `skipifsilent`; `/RUN` merely bypasses this project's mutex check. Verification
  confirms installed files but never asserts that the new process starts.
- **ATLAS-15 - Resume trusts any HTTP 206 response and can discard valid progress.**
  The downloader appends without validating `Content-Range` or object validators.
  A wrong-start 206 probe converted a valid partial into a verification failure and
  deleted the entire partial, forcing a multi-gigabyte restart.
- **VC-05 - First-use model status remains stale after successful installation.**
  A widget probe observed zero status-resolver calls after preview success and the
  label remained `First use downloads about 121 MB`.
- **VC-07 - Cleanup result labels become duplicates after deletion.** Creating
  results 1-3, deleting 2, and creating another produced two `Clean vocal 3`
  entries that are also indistinguishable in the conversion input pool.
- **VC-12 - Noise removal irreversibly quantizes float vocals to 16-bit.** The
  shared denoise service always writes `pcm_s16le`, then cleanup and training paths
  rewrap those rounded samples as FLOAT. An exact-filter probe measured only
  59.20 dB agreement in a quiet tail and 1,072 distinct PCM16 values versus 43,934
  float values.
- **VC-14 - Cleanup deletion can commit, report failure, and leave orphan media.**
  The manifest is saved before WAV unlink. A faulted unlink raised failure while a
  reload showed the result already absent, the stale UI still showed it, and the
  protected orphan file remained.

Full triggers, source paths, executable probes, impact, and recommended fixes are
recorded in `VocalCleanupAudit.md`, `RuntimeLogicAudit.md`, `Atlas.md`,
`Session-Architecture-Audit.md`, `Session-External-Input-Audit.md`, and `Sol.md`.

## Cross-validation queue

- Cross-check **VC-04** against the broader asynchronous stale-snapshot patterns in
  `Sol.md` and architecture findings before choosing a shared concurrency primitive.
- Cross-check **VC-09** with `RuntimeLogicAudit.md`; model registry locking should
  be implemented once at the runtime asset boundary rather than per feature.
- Validate the product policy for **VC-08**: RVC-ready isolation and archival
  mixture reconstruction require different residual-routing behavior.
- Cross-check **A-005** against the complete realtime render graph and define one
  canonical gain/FX/pan order before fixing individual effects.
- Treat **SOL-003**, **SOL-006**, and **SOL-010** as one resource-generation problem:
  deletion must invalidate owned workers before any package path can be recreated.
- Treat **SOL-004** and **SOL-008** as one shutdown ownership program covering both
  subprocess trees and in-process Qt workers.
- Cross-check **SOL-013** against every persisted metadata path, not only log text,
  before allowing diagnostics archives to be shared automatically.
- Treat **SOL-015**, **SOL-019**, and **SOL-021** as one deletion-transaction defect:
  destructive file operations and metadata commits require quarantine plus rollback.
- Treat **SOL-016** and **SOL-017** as blockers for advertising Safe Cleanup as safe:
  execute-time task leases and recoverable quarantine are both required.
- Cross-check **SOL-022** and **SOL-023** when redesigning checkpoint recovery; one
  durable artifact state machine must cover checkpoint validation through registration.
- Resume deferred verification from `Sol.md`'s prioritized backlog after confirmed
  fixes. P0 covers shared-ZIP containment/resource limits, crash reconciliation,
  checkpoint semantics, cleanup TOCTOU, and shutdown ownership; these are candidates,
  not confirmed findings.
