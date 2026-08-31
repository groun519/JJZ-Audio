# Runtime Logic Audit Session

## Session status

- Status: source remediation reverified
- Started: 2026-08-23 23:06 KST
- Reverified: 2026-08-27 KST
- Scope: installer/update downloads, runtime activation and fallback, startup cache
  cleanup, migration I/O, and packaged-user disk usage
- Main.md lock: not held

## Post-remediation verification

- Rechecked `RLA-001` through `RLA-013` against the current implementation and their
  original failure paths. Each confirmed source defect now has an inverted regression
  test and the implementation matches the remediation ledger.
- The complete repository suite passed: 1,579 tests in 154.325 seconds.
- A second focused run covering the concurrently completed archive-safety, updater,
  managed-transaction, model-share, storage, cleanup, and conversion-state changes
  passed: 136 tests in 7.369 seconds.
- `compileall` passed for `src` and `tests`; `git diff --check` reported no content
  errors. Existing checkout line-ending warnings remain informational.
- No additional source patch was required by this re-verification. Packaged
  second-instance behavior, signed installer/update/uninstall, real Drive failure
  recovery, bundled FFmpeg rendering, and supported GPU training remain live or
  packaged integration gates rather than source-level closures.

## Method

Only findings backed by a concrete code path and a reproducible test or static
invariant are promoted to confirmed. Each confirmed finding records impact,
trigger, ownership, and a suggested verification gate.

## Confirmed findings

### RLA-001 - The named mutex does not enforce a single app instance

- Severity: high
- Owner: `services/windows_app_mutex.py` and the application entry point
- Evidence: `create_app_mutex()` returns the handle from `CreateMutexW` but never
  checks `GetLastError() == ERROR_ALREADY_EXISTS`. `qt_app/main.py` accepts every
  returned handle and continues startup.
- Reproduction: creating the mutex twice in one process returned two nonzero
  handles; the second call left Windows error `183` (`ERROR_ALREADY_EXISTS`).
- Impact: two JJZero Audio processes can concurrently mutate settings, work-song
  state, SQLite catalogs, model manifests, and update/runtime state. SQLite's busy
  timeout does not protect JSON files or multi-file operations.
- Missing gate: tests only prove that a named mutex handle can be created and that
  the installer sees it. No test covers second-instance rejection or foregrounding
  the existing window.
- Recommended direction: make acquisition return an explicit owner/already-running
  result, stop before storage/bootstrap mutation when ownership is not acquired,
  and add a Windows integration test with two processes.

### RLA-002 - A complete `.part` artifact is not promoted before resume

- Severity: medium
- Owner: `services/app_update.py::download_artifact`
- Evidence: after reading the partial size, the function removes only files larger
  than the artifact. A partial exactly equal to the expected size still enters the
  network path and sends `Range: bytes=<artifact-size>-` without first verifying it.
- Reproduction: a checksum-valid 24-byte `runtime.zip.part` caused a request with
  `Range: bytes=24-`; an offline opener then raised `UpdateError`, the final ZIP was
  absent, and the valid partial remained.
- Impact: interruption after the final write but before `os.replace` can make a
  fully downloaded multi-gigabyte runtime/update appear unable to resume, especially
  offline or when the server answers an EOF range with HTTP 416.
- Missing gate: resume tests cover only a genuinely incomplete partial.
- Recommended direction: verify and atomically promote an exact-size partial before
  opening the network; delete and restart only when that exact-size partial fails
  verification.

### RLA-003 - Runtime install has no free-space preflight despite very high peak use

- Severity: high
- Owner: `services/runtime_bootstrap.py` and `services/runtime_installation.py`
- Evidence: runtime provisioning downloads every selected component before install;
  `_install_archive_tree()` then validates and extracts to a sibling staging tree,
  and `_swap_runtime()` temporarily retains the prior runtime as `.previous`. None of
  these paths calls `disk_usage()` or compares required and available bytes.
- Release evidence: the current local release manifest reports 3.91 GiB compressed /
  6.84 GiB unpacked for the shared runtime, 3.57 / 6.87 GiB for CU128, and 2.41 /
  6.56 GiB for ROCm. Cached archives, staging, and an existing runtime can therefore
  coexist at a peak well above the nominal download size.
- Manifest contract gap: release manifests already publish `unpacked_size` and
  `file_count` per runtime artifact, but `ReleaseArtifact` and
  `parse_release_manifest()` discard both fields. The installer therefore cannot
  perform the pre-download expanded-size check with data the release already owns.
- Contrast: training storage, storage migration, Drive download, and model-share
  packaging already own explicit free-space checks. Initial diagnostics only verify
  that storage directories exist.
- Impact: a user can spend substantial time downloading valid packages and then fail
  late during extraction or swap, leaving large retry caches and no advance capacity
  explanation. Runtime and cache may also be on different volumes, requiring separate
  checks.
- Recommended direction: have runtime provisioning calculate per-volume download,
  staging, current-runtime, and safety-margin requirements before network transfer;
  report a typed storage diagnostic before starting.

### RLA-004 - Runtime ZIP duplicate validation ignores Windows path equivalence

- Severity: medium
- Owner: `services/runtime_installation.py`
- Evidence: `_validated_unpacked_size()` stores `_normalized_member_name(member)` in
  a case-sensitive `set`. Windows extraction targets are case-insensitive, so names
  that differ only by case can address the same destination and overwrite in archive
  order.
- Reproduction: an archive containing
  `Lib/site-packages/Torch/config.py` and
  `lib/site-packages/torch/config.py` passed `runtime_packages_unpacked_size()` and
  reported 11 bytes instead of raising a duplicate-file error.
- Impact: a malformed or incorrectly assembled component can pass prevalidation but
  produce order-dependent runtime files on Windows. Related Windows aliases such as
  trailing dots/spaces and reserved device names are also not represented by the
  current POSIX-only normalization contract.
- Recommended direction: define one Windows destination-key owner that rejects
  case-fold collisions, invalid drive/colon components, trailing-dot/space aliases,
  and reserved device names before extraction; cover multi-archive collisions.

### RLA-005 - A recent hardware check suppresses live GPU-change detection

- Severity: high
- Owner: `services/hardware_diagnostics_state.py::hardware_diagnostics_required`
- Evidence: when the stored runtime profile/version still matches and `checked_at` is
  less than seven days old, the function returns `False` before calling
  `detect_rvc_hardware()`. The normal startup call in `qt_app/main.py` does not pass
  an already detected selection, so it always takes this shortcut.
- Reproduction: after recording a CPU selection, patching live detection to return
  an AMD DirectML selection still produced
  `required_after_live_hardware_change=False` and `live_detection_calls=0`.
- Impact: a GPU replacement, eGPU attach/removal, or relevant driver change within
  seven days can leave JJZero Audio using an obsolete runtime profile. Conversion
  and training can then fail or silently fall back until the cache expires or the
  user manually opens diagnostics.
- Missing gate: the existing hardware-change test passes `selection=` explicitly;
  it does not exercise the argument-free startup path.
- Recommended direction: make the lightweight hardware fingerprint check part of
  every startup and reserve the seven-day cache for expensive capability probes.

### RLA-006 - Failed diagnostics are cached as if no recheck were needed

- Severity: high
- Owner: `services/hardware_diagnostics_state.py` and diagnostics-only setup flow
- Evidence: `record_hardware_diagnostics()` persists `ready=False` and failed check
  keys, but `hardware_diagnostics_required()` never evaluates either field before
  accepting a recent `checked_at`. `InitialSetupDialog._on_diagnostics_complete()`
  records diagnostics immediately in diagnostics-only mode, before the user repairs
  missing components.
- Reproduction: recording a `SystemDiagnostics` result containing a failed
  `ai_runtime` check produced `diagnostics_ready=False` followed immediately by
  `recheck_required_immediately=False`.
- Impact: after a failed runtime/system check, closing the dialog can suppress the
  required check for seven days and let later starts proceed without prompting the
  user to repair the same incomplete environment.
- Missing gate: no test records a failed diagnostics result and then asks whether a
  recheck is required.
- Recommended direction: failed or not-ready results must remain due immediately;
  only a ready result should qualify for the recent-check shortcut.

### RLA-007 - Discovering one update permanently stops polling for newer releases

- Severity: medium
- Owner: `qt_app/main_window.py` update lifecycle
- Evidence: `_start_update_check()`, `_schedule_next_update_check()`, and
  `_on_application_state_changed()` all stop or return whenever
  `_available_update_plan` is non-null. No code clears that plan unless the process
  is replaced, and the same release manifest also carries remote feature-disable
  policy.
- Impact: a user who leaves an available update uninstalled can keep the app open
  indefinitely and never discover a newer corrective release, a replaced runtime
  package, or a newly published feature kill switch. Restarting the app is the only
  refresh path.
- Missing gate: polling tests cover intervals and backoff only; none covers continued
  manifest checks while an older update remains available.
- Recommended direction: keep low-frequency conditional manifest polling active,
  replace the pending plan when a newer manifest arrives, and continue applying
  remote feature policy independently of whether the user installs the update.

### RLA-008 - App and runtime updates are not one compatibility transaction

- Severity: high
- Owner: `qt_app/main_window.py` update install flow
- Evidence: `_install_downloaded_update()` provisions runtime components first and
  invokes `_finish_runtime_update_install()` only after that swap has committed.
  `_launch_downloaded_installer_or_restart()` then launches the application installer
  separately and has no runtime rollback path if launch fails or the installer is
  later cancelled.
- Reproduction: installed runtime version 1, provisioned a combined app/runtime plan
  to runtime version 2, and forced `start_detached_command()` to fail. The runtime
  remained version 2, `QApplication.quit()` was not called, and only an installer
  error was shown.
- Impact: the old application can continue running against a newly replaced runtime
  that was released for a newer app. Installer cancellation/failure across process
  boundaries can preserve the same version skew on the next start, with no automatic
  rollback or compatibility declaration proving the pair is safe.
- Missing gate: tests cover runtime completion and installer launch independently,
  but no combined-plan test asserts rollback or compatible recovery after launch or
  installer failure.
- Recommended direction: stage runtime without activating it until application
  installation commits, or persist a transactional update journal that lets the new
  app activate the runtime and lets the old app roll it back. At minimum, manifests
  need an explicit app/runtime compatibility contract and startup recovery gate.

### RLA-009 - Artifact downloads have no declared-size write limit

- Severity: medium
- Owner: `services/app_update.py::_write_download`
- Evidence: the writer reads until response EOF and never stops when
  `downloaded > expected_size`. Progress is clamped to 100%, and size mismatch is
  checked only after the entire response has been written.
- Reproduction: an artifact declared as 4 bytes accepted a 32-byte `BytesIO` response
  and wrote all 32 bytes to `.part`; progress only reported 100%.
- Impact: a misconfigured release host, bad redirect target, or unbounded response can
  fill the cache volume far beyond the signed manifest size. A disk-full exception
  leaves the oversized partial in place until another retry happens to remove it.
- Missing gate: download tests cover resume and corrupt fixed-size payloads, not an
  oversized or non-terminating response.
- Recommended direction: cap every read to the remaining declared bytes, read one
  sentinel byte to detect overflow, abort immediately, and remove the invalid partial
  in the same failure path.

### RLA-010 - Auto-update executable trust is optional and publisher matching is weak

- Severity: critical
- Owner: release manifest generation and `services/app_update.py`
- Current-release evidence: `release/latest.json` for 0.3.10 has no `authenticode`
  requirement on its application artifact, and Windows reports the matching local
  `JJZero-Audio-0.3.10-Setup.exe` as `NotSigned`. The release scripts explicitly
  permit this through `-AllowUnsigned`.
- Trust-boundary evidence: the client accepts a missing `authenticode` object as
  `signature_required=False`. The installer checksum therefore proves only equality
  with the mutable manifest fetched from the same GitHub release trust domain. A
  manifest compromise can replace both the EXE and its accepted hash, after which the
  updater launches it silently.
- Weak-match reproduction: even when signature metadata is present,
  `verify_authenticode_signature()` checks whether the configured publisher is a
  substring of the certificate subject. Mock valid subjects
  `CN=Not JJZero Software Malware LLC` and `CN=JJZero Software Support Scam` both
  passed a pinned publisher value of `JJZero Software`.
- Impact: the automatic update channel can execute an unsigned installer without an
  independent publisher identity check. Future signing does not close the boundary if
  a compromised manifest may omit the requirement or a different valid certificate
  merely contains the expected text.
- Missing gate: release readiness may be bypassed with `-AllowUnsigned`, and client
  tests prove optional metadata and substring behavior rather than requiring a pinned
  signer for every application artifact.
- Recommended direction: the client must unconditionally require Authenticode for
  application installers, pin an exact certificate identity (preferably SHA-256
  public-key/certificate thumbprint with an explicit rotation set), and reject a
  manifest that attempts to downgrade signature policy. Until a signing identity is
  available, automatic silent execution should not be treated as a trusted channel.

### RLA-011 - A process exit during runtime swap strands a complete rollback copy

- Severity: high
- Owner: `services/runtime_installation.py` runtime transaction lifecycle
- Evidence: `_swap_runtime()` moves the current tree to `.<root>.previous` before
  moving the staged tree into place. Its `except` rollback only runs while the same
  Python process remains alive. Neither application startup nor
  `repair_rvc_runtime_adapter()` discovers or restores a valid `.previous` tree.
- Reproduction: installed a complete runtime version 1, moved the live tree to
  `.runtime.previous` to represent termination between the two `os.replace()` calls,
  and ran the normal startup adapter repair. The backup still reported version 1,
  while the visible root remained absent, `installed_runtime_version(root)` returned
  `None`, and repair returned `unavailable`.
- Impact: a power loss, forced termination, or process crash in the narrow commit
  window turns an intact multi-gigabyte runtime into an invisible backup. The app
  reports the runtime missing and makes the user download/reinstall it instead of
  performing an immediate local rollback.
- Missing gate: swap tests cover Python exceptions and retryable rename failures, but
  no startup test begins with only a valid `.previous` transaction artifact.
- Recommended direction: introduce a startup-owned runtime transaction recovery step.
  Before diagnostics or repair, validate `root`, `.installing`, and `.previous`; when
  the live root is absent and the backup is complete, atomically restore it. Delete
  transaction artifacts only after choosing and validating the committed tree.

### RLA-012 - The shared atomic JSON writer is not safe for concurrent callers

- Severity: high
- Owner: `services/managed_files.py::write_json_atomic`
- Evidence: every writer uses the same deterministic sibling path
  `<target>.tmp`. Concurrent calls therefore truncate and write the same temporary
  file before independently calling `os.replace()`. Atomic replacement protects only
  the final rename, not construction of that shared temporary payload or the
  surrounding read-modify-write transaction.
- Reproduction: launched 16 threads through the real
  `roformer_model_assets._update_model_registry()` path with distinct model entries.
  One run produced malformed JSON (`Extra data`). A second run left valid JSON with
  only 1 of 16 entries and 12 writer exceptions caused by the shared temporary-file
  lifecycle.
- Scope: `write_json_atomic()` has 76 application call sites, including song/model
  manifests, studio state, training state, OAuth data, diagnostics, storage migration
  journals, runtime state, and update cleanup markers. Worker threads can write some
  of these while autosave or another task is active; `RLA-001` also permits a second
  process to hit the same files.
- Impact: callers may receive sporadic file-not-found/replace errors, silently lose a
  concurrent update, or leave a syntactically corrupt JSON file. Recovery behavior
  varies by owner, so the symptom can appear as missing models, reset state, hidden
  outputs, or repeated setup/diagnostics rather than an obvious storage race.
- Missing gate: managed-file tests do not run concurrent writers, and owner tests
  generally assert only a single sequential save.
- Recommended direction: give each write a same-directory unique temporary name,
  flush and `fsync` it before replacement, and use an owner-level interprocess lock
  around every shared read-modify-write transaction. A unique temp file fixes payload
  corruption but cannot by itself prevent lost updates.

### RLA-013 - Google Drive sharing loses ownership of uploaded public files

- Severity: high
- Owner: `services/google_drive.py` and `services/google_drive_share.py` share
  transaction
- Evidence: `upload_shared_file()` creates the remote file first, then grants public
  permission and fetches final metadata. Any failure after upload raises without
  deleting the new file. `GoogleDriveShareService.share_file()` then records the
  returned file in a separate local JSON transaction; catalog failure also has no
  compensating remote delete.
- Failure reproduction: a real client flow uploaded all 1,024 bytes and then received
  HTTP 403 from the permission endpoint. It raised `Google Drive link sharing failed`
  with zero DELETE requests. A separate service-level probe returned a public remote
  file and forced catalog persistence to fail with `disk full`; again no compensating
  delete was issued.
- Replacement reproduction: shared one source, changed it, then shared it again. Two
  remote IDs were uploaded, no DELETE occurred, and the local catalog retained only
  the second ID. The first public file and link became permanently unmanaged by the
  application.
- Impact: permission/network/catalog failures and ordinary re-sharing of modified
  models or exports can consume large Drive quota with invisible files. More
  importantly, deleting the visible current share does not revoke older public links
  whose IDs were discarded, contradicting user expectations around share removal.
- Missing gate: tests cover successful upload, quota rejection, and resumable network
  recovery, but not post-upload rollback, catalog commit failure, or replacement of an
  existing public share.
- Recommended direction: make the share service own a transaction journal containing
  the new remote ID as soon as upload completes. If permission/final lookup/catalog
  commit fails, best-effort delete the new file while retaining a recoverable cleanup
  record. When replacing a share, commit the new record first and then delete the old
  remote ID, preserving a retry record if either side fails.

## Candidates under verification

### RLA-C01 - Main-window import dominates cold startup

- A fresh development interpreter measured approximately 5.07 seconds for
  `import jang_app.qt_app.main_window`, while importing `startup_coordinator` took
  approximately 1.15 seconds on the same machine.
- The splash remains visible, but `_load_main_window()` runs synchronously on the UI
  thread. The next step is import-time attribution and frozen-build measurement
  before proposing module boundaries.

#### Follow-up measurement (2026-08-27)

- With the current source tree and isolated interpreter, `-X importtime` measured
  approximately 0.83 seconds cumulative for `jang_app.qt_app.main_window` and
  approximately 0.24 seconds cumulative for `jang_app.qt_app.startup_coordinator`.
- The largest application-local contribution was `jang_app.qt_app.model_workspace` at
  approximately 79 ms cumulative, followed by `jang_app.qt_app.studio_editor` at
  approximately 23 ms; this is not large enough to justify a risky module split by
  itself.
- No source split is justified by this development measurement alone. A frozen clean
  launch measurement remains the required gate before changing startup module
  boundaries.

## Cross-validation

### Architecture A-001 independently supported

- `studio_session._session_with_required_tracks()` computes only `existing_roles`
  and appends defaults for absent roles. It never examines whether an existing
  required role has zero clips.
- `studio_assets.build_default_studio_tracks()` independently constructs a converted
  clip when the active output now has one. That populated default is discarded when
  the empty `converted_vocal` role already exists.
- Existing tests cover missing-role backfill and edit preservation, but not the
  empty-role -> newly available asset transition. This independently supports the
  trigger and impact recorded as `A-001` in `Session-Architecture-Audit.md`.

### Architecture mutex finding independently supported

- `Session-Architecture-Audit.md` repeated the native mutex probe independently and
  observed the same second-handle error `183`. This cross-validates `RLA-001` from a
  separate session and code review path.

### Atlas ATLAS-01 independently supported

- Installed a complete embedded runtime, changed its installed
  `rvc/runtime/python.exe` payload to `old-runtime-binary`, then installed a second
  complete runtime package as version `2`.
- `installed_runtime_version()` returned `2`, while `python.exe` still contained the
  old payload. This independently confirms that preserving all of `rvc/runtime`
  allows stale executables to override freshly extracted files while version state
  reports the new runtime.

### Atlas ATLAS-02 and ATLAS-04 independently supported

- `RLA-002` is the same complete-partial retry defect as `ATLAS-02`; both sessions
  used independent executable probes and observed an EOF range request instead of
  local verification/promotion.
- `RLA-007` is the same pending-update polling freeze as `ATLAS-04`; Atlas also tied
  it to a field update failure and stale URL retry, strengthening the user impact.

### Atlas ATLAS-03 independently supported

- Parsed a valid manifest whose `ai-runtime` and `rvc-runtime-cu128` components each
  declared `shared.zip` with different hashes. Both artifacts remained selected.
- Passing two distinct local `shared.zip` paths to `_component_packages()` resolved
  both components to the second path (`b'profile'`) because the name-keyed map
  discarded the first identity. This independently confirms both the parser gap and
  the installer misrouting path.

### Vocal cleanup VC-09 has an interprocess registry-loss path

- `roformer_model_assets._update_model_registry()` performs an unlocked
  read-modify-write of shared `download_checks.json`. `write_json_atomic()` prevents
  partial JSON bytes, but it does not prevent two processes from reading the same old
  value and the later replacement discarding the earlier process's new model entry.
- `prepare_roformer_model_assets()` invokes this update even when all model files are
  already present. Because `RLA-001` proves that the named mutex currently permits
  multiple JJZero Audio processes, a Python thread lock alone would not close this
  boundary. The registry owner needs an interprocess lock or the application must
  first enforce a real single-instance contract.

### Sol SOL-014 independently confirms RLA-012

- The asynchronous-lifecycle session synchronized two real
  `write_json_atomic()` calls after both wrote the same fixed temporary path. The
  caller that successfully renamed the file committed the other caller's payload,
  while the second caller raised `FileNotFoundError`.
- This independently confirms both halves of `RLA-012`: unique temporary names are
  required to preserve payload identity, and a separate owner-level lock/CAS contract
  is required to preserve read-modify-write updates.

## Cross-check log

- 2026-08-23 23:06 KST: `Problem/Main.md` was empty. `Sol.md` declared that it did
  not hold the shared lock, so this session began an independent runtime audit.
- 2026-08-23 23:09 KST: confirmed RLA-001 through the native Windows last-error
  value and RLA-002 with an executable checksum-valid partial-download scenario.
- 2026-08-23 23:10 KST: shared merge deferred. `Main.md` simultaneously declared
  a top-level `VocalCleanupAudit` lock and a second unlocked protocol block, so no
  authoritative unlocked state existed.
- 2026-08-23 23:12 KST: confirmed RLA-003 by comparing release component sizes,
  staging/swap code, and the absence of a runtime storage check. Independently
  cross-validated architecture finding A-001.
- 2026-08-23 23:13 KST: confirmed RLA-004 with a two-entry case-collision ZIP that
  passed the runtime package validator on Windows.
- 2026-08-23 23:18 KST: confirmed RLA-005 and RLA-006 with executable startup-path
  reproductions. A recent record skipped live detection, and a failed diagnostics
  result was immediately treated as not requiring a recheck.
- 2026-08-23 23:20 KST: confirmed RLA-007 from all three update scheduling guards;
  the pending update plan has no in-process invalidation or supersession path.
- 2026-08-23 23:23 KST: cross-validated Atlas findings 01 and 03 with executable
  runtime-upgrade and duplicate-artifact-name probes; linked the independently
  duplicated complete-partial and update-polling findings instead of renumbering.
- 2026-08-23 23:31 KST: promoted the combined app/runtime transaction candidate to
  RLA-008 after an executable installer-launch failure left runtime version 2 active
  under the old running app. Added manifest `unpacked_size` loss to RLA-003.
- 2026-08-23 23:33 KST: confirmed RLA-009 by writing an eight-times-oversized response
  through the real download writer without any early abort.
- 2026-08-23 23:36 KST: confirmed RLA-010 against the current 0.3.10 installer and
  manifest. Windows reported `NotSigned`; two misleading but valid mock certificate
  subjects also passed the current substring publisher comparison.
- 2026-08-23 23:44 KST: confirmed RLA-011 with a complete version-1 runtime stranded
  in `.runtime.previous`; normal startup repair ignored it. Cross-validated VC-09's
  shared model-registry race against the independently confirmed broken process mutex.
- 2026-08-23 23:48 KST: promoted the registry race's shared root cause to RLA-012.
  Sixteen real concurrent registry writes produced both malformed JSON and a separate
  run with only 1 retained entry plus 12 writer exceptions.
- 2026-08-23 23:56 KST: cross-validated RLA-012 against SOL-014's controlled payload
  substitution probe. Confirmed RLA-013 with permission-failure, catalog-failure, and
  changed-source re-share probes; all three left a remote file without a manageable
  local ownership record.
