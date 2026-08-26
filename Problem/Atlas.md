# Atlas Session Audit

## Session status

- Status: findings confirmed; awaiting shared-index lock
- Started: 2026-08-23 23:10 KST
- Scope: update manifests, package boundaries, release asset integrity, updater recovery
- Main.md lock: not held

## Method

Findings are confirmed only when the code path and a test, manifest comparison, or
public release check support the same conclusion. Each item records user impact,
trigger, evidence, and a concrete verification target.

## Confirmed findings

### ATLAS-01 - Embedded RVC runtime upgrades preserve stale executables

- Severity: critical
- Trigger: install a new `ai-runtime` package that still embeds `rvc/runtime` over an
  existing installation.
- Evidence:
  - `runtime_installation.py` includes `Path("rvc/runtime")` in
    `_PRESERVED_DIRECTORIES` and copies preserved directories over the freshly
    extracted staging tree with `dirs_exist_ok=True`.
  - `release/runtime-packages.json` declares runtime 4 with
    `requires_rvc_profile: false`; no separate cu118 package index exists, so this is
    an embedded-runtime configuration rather than a split profile configuration.
  - Executable reproduction: install an old embedded runtime, alter
    `rvc/runtime/python.exe`, then install a new embedded package. Result was
    `state=new python=old-runtime-binary`.
- User impact: metadata reports the new runtime version while Python, Torch, and other
  RVC files can remain old. Diagnostics can therefore trust a false version state and
  stop offering repair, leaving conversion/training failures persistent.
- Required fix: preserve only user/model data unconditionally. Preserve the active
  profile runtime only when the incoming base package explicitly declares a split
  runtime (`requires_rvc_profile=true`), or reinstall the selected profile after the
  base swap. Add a legacy-to-legacy upgrade test that asserts new runtime binaries win.

### ATLAS-02 - A complete `.part` file can enter a permanent HTTP 416 retry loop

- Severity: high
- Trigger: the process exits after all bytes are written to `<artifact>.part` but
  before verification/rename.
- Evidence:
  - `app_update.py:421-430` only resets a partial when `offset > artifact.size`; an
    exactly complete partial sends `Range: bytes=<size>-`.
  - Reproduction with a valid 16-byte partial produced
    `UpdateError`, `Range: bytes=16-`, and left the partial in place after a simulated
    HTTP 416 response.
  - No test covers an exactly complete partial; current tests only cover an incomplete
    resume and verification failure.
- User impact: every retry repeats the same 416 until cache is manually removed or a
  cleanup path happens to delete it.
- Required fix: verify/promote a full-size partial before network access; if its hash is
  wrong, delete it and restart from zero. Validate `Content-Range` before appending.

### ATLAS-03 - Artifact names are only unique inside each component

- Severity: high
- Trigger: two selected components publish different artifacts with the same filename.
- Evidence:
  - `parse_release_manifest` rejects duplicate component IDs and `_parse_artifacts`
    rejects duplicates only within one component; it has no manifest-wide name check.
  - `_download_update_artifacts` stores every selected artifact in one
    `cache/updates/<app-version>` directory.
  - `_component_packages` resolves downloaded files using `{path.name: path}`, losing
    component identity.
  - Reproduction parsed a runtime and cu128 profile that both used `shared.zip`; the
    plan contained both names with different hashes (`b`, `c`) without rejection.
- User impact: the later download overwrites the earlier path, and installation can
  feed one component the other component's archive. At best installation fails; at
  worst same-shaped payloads create a mixed environment.
- Required fix: enforce globally unique artifact names or cache by component ID and
  key package resolution by `(component_id, artifact identity)`. Cover collisions in
  parser, downloader, and installer tests.

### ATLAS-04 - A discovered update freezes its manifest until app restart

- Severity: high
- Trigger: an update plan is discovered, then its manifest or remote URLs are hotfixed
  after a download failure.
- Evidence:
  - `MainWindow._start_update_check` returns whenever `_available_update_plan` is not
    `None`.
  - `_schedule_next_update_check` also stops its timer in the same state.
  - The plan is assigned when an update is found, but no code clears or refreshes it on
    download failure or dialog close; repository search found only that assignment.
  - There is no update-polling test for failed-download manifest refresh.
  - Field evidence: a packaged `0.3.0` session (`c7be2358ff6d`) failed at
    `2026-08-20T14:58Z` while updating to `0.3.9`, with
    `NETWORK_DOWNLOAD_FAILED` and HTTP 404 for `JJZero-Runtime-4-part01.zip`.
  - Git history confirms the generated `v0.3.9` manifest had rewritten reused runtime
    URLs to nonexistent release `v0.3.2`; commit `33f9152` later corrected them to
    their immutable source release `v0.3.0` and changed the generator to preserve
    source URLs.
  - GitHub reports the corrected `v0.3.9/latest.json` asset was uploaded at
    `2026-08-20T15:03:48Z`, about five minutes after the field failure. The runtime
    asset currently exists in `v0.3.0`, and its size and SHA-256 match the corrected
    manifest. This establishes the original 404 cause and shows why an already-open
    client needed a manifest refresh after the hotfix.
- User impact: pressing retry after a server-side 404/hash hotfix still uses the stale
  URL and fails again. Users must restart the application, but the UI does not explain
  this requirement.
- Required fix: on retry/failure, conditionally refetch the manifest and rebuild the
  plan, or continue low-frequency polling while an update is pending and atomically
  replace the plan when ETag/content changes.

### ATLAS-05 - Release gate checks remote package size but not GitHub SHA-256

- Severity: medium (preventive integrity gap)
- Trigger: a reused GitHub release asset is replaced or corrupted with another payload
  of the same name and size.
- Evidence:
  - `publish_github_release.ps1` accepts a remote asset when `name` and `size` match;
    it does not compare the manifest SHA-256 with GitHub's `asset.digest`.
  - Remote-only components are skipped by ZIP-content checks in
    `verify_component_release.py`.
  - GitHub currently exposes `sha256:` digests. Cross-checking all 16 reused v0.3.0
    assets showed 16/16 match today, proving the data needed for a stronger gate is
    available while confirming this is not current corruption.
- User impact: a bad same-size remote asset passes publication and every client later
  fails artifact verification after a multi-gigabyte download.
- Required fix: require `asset.digest == sha256:<manifest hash>` before publishing and
  repeat the same verification after public release download.

### ATLAS-06 - Worker failures disappear from the general application log

- Severity: medium
- Trigger: a background `TaskWorker` operation fails and support receives `jang.log`
  without the matching `logs/jobs/<task-id>` directory or diagnostics ZIP.
- Evidence:
  - `TaskWorker.run()` catches the exception and emits only a traceback string through
    `failed`; it does not call the application logger.
  - `MainWindow._run_worker()` writes the failure to `JobDiagnostics` through
    `processing_queue.fail()`, but likewise does not log the task ID, diagnostic code,
    or traceback to `jang.log`.
  - Field log `message.txt` contains the affected session and only the later action
    `Opening directory in file browser: .../logs/jobs/d009...`; the actual update 404
    is absent. The separately copied task report is required to identify it.
- User impact: the most commonly shared log can prove that a user opened diagnostics
  but cannot explain the failure. If the job directory is omitted, cleaned, or lost,
  support cannot correlate or reconstruct the incident.
- Required fix: on task failure, log one structured record containing task ID, title,
  diagnostic ID, and redacted final error line, followed by `logger.debug`/a bounded
  traceback if appropriate. Keep full output in the job folder, but make `jang.log`
  independently useful as an index.

### ATLAS-07 - Startup timing mislabels interactive diagnostics as app creation

- Severity: medium
- Trigger: first-run setup, runtime repair, or hardware diagnostics takes significant
  time before the main window opens.
- Evidence:
  - `qt_app/main.py` constructs `QApplication` at line 28, then runs path discovery,
    runtime adapter repair, initial setup, and potentially the modal hardware
    diagnostics dialog before marking `application_created` at line 75.
  - Field logs contain otherwise normal RTX 4060 sessions reporting
    `application_created=211462.1ms`, `592493.8ms`, and `1007545.1ms`.
  - The application logger is initialized only after that mark, so there are no phase
    records explaining where those 3.5, 9.9, and 16.8 minutes were spent.
- User impact: support sees what looks like a Qt/application-construction freeze while
  runtime installation or user-facing diagnostics may be the real wait. Startup
  optimization work is therefore aimed at the wrong phase and genuine hangs cannot be
  distinguished from expected setup work.
- Required fix: mark `application_created` immediately after `QApplication(...)`, add
  `paths_discovered`, `runtime_overlay_repaired`, `setup_started/finished`, and
  `hardware_diagnostics_started/finished` phases, and initialize a minimal startup
  logger before any potentially blocking setup.

### ATLAS-08 - Backup cleanup failure reports install failure after committing the new runtime

- Severity: high
- Trigger: the staging-to-runtime swap succeeds, but deleting `.runtime.previous`
  fails because of a transient Windows file lock, antivirus scan, or permission error.
- Evidence:
  - `_swap_runtime()` moves the current runtime to backup and staging to the active
    root inside its rollback block, then calls `_remove_directory(backup)` outside
    that block.
  - Any cleanup exception propagates through `_install_archive_tree()` as an install
    failure. The staging cleanup in its exception handler cannot roll back because
    staging has already become the active root.
  - Fault-injection reproduction made only the final backup deletion raise. The
    result was `PermissionError`, active state `new`, active binary `new`, backup
    present, and backup binary `old`.
- User impact: UI and job diagnostics say installation failed even though the runtime
  version actually changed. A retry starts from an unexpected mixed state and may
  redownload gigabytes; the abandoned backup also consumes several additional GB.
- Required fix: define the active-root swap as the commit point. Retry/best-effort the
  old-backup cleanup and report it separately without failing the committed install,
  or retain explicit transaction state that can roll back the active root before an
  install failure is returned. Add a post-swap cleanup fault test.

### ATLAS-09 - App and runtime components are committed in the wrong transaction order

- Severity: high
- Trigger: an update requires both application and runtime components, runtime
  provisioning succeeds, then the installer cannot start, is terminated, or fails
  after launch.
- Evidence:
  - `_install_downloaded_update()` provisions runtime/profile components first.
  - Its success callback `_finish_runtime_update_install()` deletes verified runtime
    archives when an application update is pending, then calls
    `_launch_downloaded_installer_or_restart()`.
  - Installer launch failure only restores the app mutex and updates UI state. There
    is no runtime rollback path. Successful process creation is also treated as final;
    the application does not monitor installer exit or prove that the new app version
    was committed.
  - Existing update tests verify cache markers and mutex restoration, but none covers
    the app/runtime version pair after installer launch failure or installer-process
    failure.
- User impact: the old application can be left running on a newly committed runtime,
  while the runtime packages needed for recovery have already been deleted. This is
  precisely the version-skew state a component manifest should prevent.
- Required fix: persist a pending multi-component transaction, install the app first,
  and let the newly installed app/helper commit the runtime and validate the complete
  version pair. Do not delete component archives until the new app acknowledges the
  transaction. Add failure injection at runtime commit, installer spawn, installer
  exit, and first launch.

### ATLAS-10 - The manifest release version is not bound to the application component

- Severity: high
- Trigger: a schema-2 manifest is assembled or hotfixed with a root `version` that
  differs from the `application` component version and installer artifact.
- Evidence:
  - `parse_release_manifest()` validates both strings independently but never requires
    `release.version == release.application.version`.
  - `create_update_plan()` decides whether the application is newer using only the root
    release version, while `UpdatePlan.artifacts` downloads the application component's
    installer.
  - `verify_component_release.py` reuses the same parser and has no additional version
    relationship check. The publication script likewise takes the release tag from the
    root version.
  - Executable reproduction parsed root version `9.0.0`, application version `1.0.0`,
    and an artifact named `JJZero-Audio-1.0.0-Setup.exe`. A client at `8.0.0` produced
    `application_required=True` and selected the `1.0.0` installer.
- User impact: a malformed or hurriedly hotfixed manifest can downgrade the app while
  presenting it as an upgrade. After restart the root release still compares newer, so
  the updater can repeatedly offer the same wrong installer.
- Required fix: require root and application component versions to match, verify the
  signed installer's product version against both, and make release readiness fail on
  any mismatch before tagging or upload.

### ATLAS-11 - A stale release manifest can downgrade runtime components under a newer app

- Severity: high
- Trigger: a client receives an older valid manifest from a stale cache, mirror,
  rollback, or replay after installing a newer app and runtime.
- Evidence:
  - `create_update_plan()` applies semantic ordering only to the application root
    version. Base runtime and RVC profile components use inequality, so any different
    version is considered required even when the advertised component is older.
  - There is no guard that rejects `release.version < current_version` before planning
    runtime-only work, and the unsigned manifest has no monotonic release counter or
    expiry independent of GitHub's mutable `latest` endpoint.
  - Executable reproduction used app `0.3.10`, runtime `4`, and cu128 profile `2` with
    a valid release `0.3.0` containing runtime `3` and cu128 profile `1`. The plan set
    `application_required=False`, `runtime_required=True`,
    `rvc_profile_required=True`, and selected both old archives.
- User impact: a stale response can silently replace a working newer engine with an
  older one while leaving the newer app installed. This creates unsupported version
  skew, redownloads several GB, and can reintroduce fixed conversion/training defects.
- Required fix: reject manifests older than the installed app for automatic component
  changes, persist the highest accepted release/component epochs, and require explicit
  signed rollback metadata for intentional downgrades. Component versions should use
  monotonic comparison or a compatibility map rather than simple inequality.

### ATLAS-12 - Published binaries are not bound to the tagged source revision

- Severity: high
- Trigger: `dist/` or `release/` contains an older successful build, source changes are
  committed, and release preparation/publishing reuses the existing artifacts.
- Evidence:
  - Both `/dist/` and `/release/` are ignored by Git, so their provenance is not part
    of the clean-worktree check in `publish_github_release.ps1`.
  - `build_installer.ps1 -SkipAppBuild` explicitly packages the existing distribution
    and checks only that `JJZero Audio.exe` exists. `publish_github_release.ps1` does
    not rebuild; readiness tests current source and smoke-tests whichever binary is
    already present.
  - Repository search found no build metadata containing `git rev-parse`, source
    revision, or provenance in the executable, installer, or release manifest. The
    publisher creates the tag from the current HEAD only after artifact verification.
  - The publisher pushes that tag before `gh release create`. If release creation
    fails and a corrective source commit is made, the next run merely checks that the
    tag exists; it never verifies the existing tag still points to current HEAD. It can
    therefore upload newly rebuilt artifacts under an older source tag.
  - This provenance mismatch has occurred in the public channel. The current
    `v0.3.9/latest.json` GitHub asset is 7,115 bytes with SHA-256
    `47fa4af3...f9074002`; that exactly matches the CRLF form committed later in
    `33f9152` for release 0.3.10. The manifest recorded by the `v0.3.9` tag instead
    hashes to `f7fabe6b...f5cd956` and points Runtime 4 part01 at nonexistent `v0.3.2`
    rather than corrected `v0.3.0`. The hotfix was operationally necessary, but the
    public asset can no longer be reconstructed from or audited against its own tag.
- User impact: a clean current commit can be tagged and documented while users receive
  a binary built from an earlier commit. A reported fix can therefore be absent from
  the released app even though version, tag, and patch notes all claim it is present;
  support has no field metadata capable of proving which code was shipped.
- Required fix: generate artifacts only from a recorded clean source revision, embed
  that revision/build ID in the app and manifest, and have readiness/public download
  verification require it to equal the commit being tagged. Treat `-SkipAppBuild` as
  valid only when a signed build-provenance file matches HEAD and all build inputs.
  Refuse publication when an existing release tag does not resolve to current HEAD.

### ATLAS-13 - The silent updater does not relaunch the installed application

- Severity: medium
- Trigger: install an application update through the in-app update dialog.
- Evidence:
  - `_launch_downloaded_installer_or_restart()` starts Inno Setup with `/SILENT` and
    `/RUN`, then immediately quits the current application.
  - The installer `[Run]` entry has `skipifsilent`, so the new app is intentionally
    skipped in this mode. `[Setup]` also declares `RestartApplications=no`.
  - `/RUN` is not an Inno Setup relaunch option; this project's Pascal code consumes it
    only in `InitializeSetup()` to bypass the running-app mutex check.
  - `verify_installer.ps1` runs the same silent argument set and verifies installed
    version/files, but never asserts that a new application process starts.
- User impact: the button presented as restart/install closes JJZero Audio and leaves
  the user with no app window after setup completes. It also prevents the updater from
  performing a first-start acknowledgement of the multi-component transaction, which
  compounds ATLAS-09/RLA-008.
- Required fix: add a dedicated updater switch and a `[Run]` entry whose `Check`
  explicitly allows post-update launch in silent mode, or use a small update helper
  that waits for installer success and launches the exact installed executable. Add an
  end-to-end assertion for one and only one new-version process.

### ATLAS-14 - Uninstall can recursively delete unrelated files in custom Runtime and Cache roots

- Severity: critical (user data loss)
- Trigger: select an empty custom folder as the Audio Engine or Cache location, then
  place unrelated files in that same folder before uninstalling JJZero Audio.
- Evidence:
  - The first-run/settings UI accepts each category as an exact independent absolute
    path. `build_custom_storage_layout()` checks only overlap and application-folder
    placement; migration checks that a changed target is empty only at migration time.
  - The installer writes no ownership marker into those roots. Repository search found
    no root-ownership contract used by the uninstaller.
  - `PrepareRuntimeRemoval()` reads `runtime_root` and `cache_root` directly from the
    mutable `storage.json`. `IsSafeGeneratedRoot()` rejects only an empty path, a drive
    root, and paths containing Data, Output, or the LocalAppData control root.
  - A passing runtime root is recursively removed by `RemoveRuntimeRoot()` with
    `DelTree(RuntimeRoot, True, True, True)` after preserving only `rvc/weights` and
    `rvc/logs`. A passing cache root is likewise deleted recursively. Unknown files
    anywhere else below either root are not preserved or even enumerated separately.
  - Installer verification uses dedicated generated `Runtime` and `Cache` directories;
    no uninstall test places a sentinel user file into a custom category root and
    asserts that it survives.
- User impact: a valid configuration can cause uninstall to permanently erase unrelated
  projects, downloads, or other application data that the user later stored below the
  selected folder. The safety predicate proves only that the path is not one of three
  protected roots, not that JJZero Audio owns it.
- Required fix: create and validate an unforgeable/app-specific ownership marker when a
  dedicated category root is initialized, prefer an app-owned child directory even for
  custom locations, and delete only a manifest of managed paths. Preserve unknown
  entries and leave the root in place. Add silent and interactive uninstall tests with
  sentinels at the root and nested levels, plus tampered/missing-marker cases.

### ATLAS-15 - Resume accepts an unrelated HTTP 206 range and destroys valid progress

- Severity: medium (multi-gigabyte recovery failure)
- Trigger: a partial artifact exists and a CDN, proxy, or changed release object returns
  HTTP 206 whose `Content-Range` starts somewhere other than the requested offset.
- Evidence:
  - `download_artifact()` decides to append solely from `offset > 0` and
    `response.status == 206`; it never parses or validates `Content-Range`, total size,
    ETag, or Last-Modified for the resumed object.
  - `_write_download()` then appends every returned byte. The inevitable final size or
    SHA mismatch unconditionally deletes the `.part` file instead of retrying from zero
    or retaining the previously valid prefix.
  - Executable probe created an 8-byte valid prefix for a 16-byte artifact and returned
    `206 Content-Range: bytes 0-15/16` with the full payload. The call failed verification
    and left neither the partial nor final artifact.
  - The resume test asserts only that the outgoing `Range` header is present and the
    mock status is 206; its response has no `Content-Range`, so the missing validation is
    not covered.
- User impact: a malformed one-off resume response near the end of a large Runtime/RVC
  download converts recoverable progress into a complete redownload. On constrained or
  metered connections this can make update installation practically impossible.
- Required fix: require `Content-Range` start to equal the local offset and total to
  equal the manifest size, bind partial metadata to URL/hash plus ETag/Last-Modified,
  and restart once from byte zero without deleting a known-good prefix until the fresh
  response is established. Add wrong-start, wrong-total, changed-validator, ignored-
  range, and exact-size-partial tests.

## Candidates under verification

- Manifest `architecture` and `minimum_windows` are emitted but ignored by the parser.
  Installer constraints reduce current impact; behavior for runtime-only updates needs
  a concrete unsupported-platform path before promotion.

## Cross-validation

- `RuntimeLogicAudit.md` independently reproduced ATLAS-02 as `RLA-002`. Both sessions
  agree that an exact-size `.part` must be verified/promoted before any range request.
  The shared index should merge these as one finding rather than duplicate them.
- `RLA-003` confirms the disk-space consequence of ATLAS-08/09 at a broader level:
  cache, staging, active runtime, and `.previous` can coexist without a preflight.
  Atlas adds the transaction/commit-state failure; RuntimeLogicAudit owns capacity
  calculation and per-volume preflight.
- `RLA-010` was independently checked against the local 0.3.10 release. Windows
  reports `NotSigned` for `JJZero-Audio-0.3.10-Setup.exe`, and `latest.json` has no
  Authenticode requirement. The client verifier also accepts any signer subject that
  merely contains the configured publisher text. RuntimeLogicAudit owns this finding;
  Atlas records the release-channel evidence rather than duplicating it.
- `RLA-011` complements ATLAS-08: Atlas proved that cleanup failure after the swap
  reports a false install failure, while RuntimeLogicAudit proved that process death
  between the two renames leaves a valid `.previous` tree that startup never restores.
  Both require an explicit persisted runtime transaction and startup recovery owner.

## Cross-check log

- 2026-08-23 23:10 KST: `Problem/Main.md` was empty. `Problem/Sol.md` was actively
  investigating asynchronous lifecycle, shared state, storage safety, runtime/update
  boundaries, and diagnostics. This session narrowed scope to release/update integrity.
- 2026-08-23 23:17 KST: public v0.3.0 component assets were checked against the
  current v0.3.10 manifest; all 16 GitHub digests matched.
- 2026-08-23 23:19 KST: executable reproductions confirmed ATLAS-01, ATLAS-02, and
  ATLAS-03. Static assignment/lifecycle search confirmed ATLAS-04.
- 2026-08-23 23:20 KST: `Problem/Main.md` contained conflicting lock headers while
  `VocalCleanupAudit` was initializing the protocol. This session did not edit Main.
- 2026-08-23 23:34 KST: field log from a packaged RTX 4060 installation cross-checked
  ATLAS-04 and exposed the independent observability gaps ATLAS-06 and ATLAS-07.
  The failure preceded the corrected `v0.3.9/latest.json` upload by about five minutes;
  public `v0.3.0` runtime part01 now matches the corrected manifest.
- 2026-08-23 23:39 KST: backup-cleanup fault injection confirmed ATLAS-08. Static
  update sequencing and missing rollback/acknowledgement gates promoted the prior
  multi-component transaction candidate to ATLAS-09. RLA-002/RLA-003 were linked as
  independent cross-validation rather than duplicated.
- 2026-08-23 23:31 KST: an executable mismatched-version manifest probe confirmed
  ATLAS-10. Local signature inspection independently supported RLA-010, and RLA-011
  was linked to the same missing runtime transaction/recovery boundary as ATLAS-08.
