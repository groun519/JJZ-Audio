# Update Cache Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove only completed JJZero Audio update artifacts at the earliest safe lifecycle point.

**Architecture:** A focused update-cache service owns managed-path validation, completion markers, cleanup retries, and reports. Runtime-only updates remove their release directory immediately after verified installation, while application updates write a marker after the installer launches and the next successfully updated app startup performs cleanup.

**Tech Stack:** Python 3.11, pathlib, JSON marker files, unittest, PySide6 integration

## Global Constraints

- Cleanup is restricted to `Cache/updates/<release-version>/`.
- Unmarked directories and resumable `.part` files must remain untouched.
- User media, models, runtimes, waveform caches, settings, logs, and OAuth data must never be cleanup inputs.
- Cleanup failures are logged and retried without changing update success into failure.
- The completion marker is deleted only after every other managed artifact is removed.

---

### Task 1: Managed Update Cache Service

**Files:**
- Create: `src/jang_app/services/update_cache.py`
- Create: `tests/test_update_cache.py`

**Interfaces:**
- Produces: `mark_update_cleanup_ready(cache_root: Path, update_dir: Path, target_version: str) -> bool`
- Produces: `discard_completed_update(cache_root: Path, update_dir: Path) -> UpdateCacheCleanupReport`
- Produces: `cleanup_completed_updates(cache_root: Path, current_version: str) -> UpdateCacheCleanupReport`
- Produces: immutable `UpdateCacheCleanupReport(removed_files: int, reclaimed_bytes: int, failed_paths: tuple[Path, ...])`

- [ ] Write failing tests proving that a marked completed directory is removed only when the running version reaches the marker target, an unmarked `.part` survives, external and symlinked paths are rejected, and a deletion failure preserves the marker.
- [ ] Run `python -m unittest tests.test_update_cache` and confirm failures are caused by the missing service.
- [ ] Implement managed-root resolution, atomic marker writing, semantic three-part version comparison, marker-last recursive deletion, and cleanup report aggregation.
- [ ] Run `python -m unittest tests.test_update_cache` and confirm all service tests pass.

### Task 2: Startup Cleanup Integration

**Files:**
- Modify: `src/jang_app/services/app_bootstrap.py`
- Modify: `tests/test_app_bootstrap.py`

**Interfaces:**
- Consumes: `cleanup_completed_updates(paths.cache_dir, __version__)`

- [ ] Write a failing bootstrap test that creates a completed update marker and asserts `prepare_app_environment()` removes the managed update directory while leaving an unmarked partial download intact.
- [ ] Run the focused bootstrap test and confirm the completed directory remains before implementation.
- [ ] Call cleanup after cache directory creation, log reclaimed bytes and failures, and continue startup if cleanup cannot remove a locked file.
- [ ] Run `python -m unittest tests.test_app_bootstrap tests.test_update_cache` and confirm both suites pass.

### Task 3: Update Completion Wiring

**Files:**
- Modify: `src/jang_app/qt_app/main_window.py`
- Modify: `tests/test_main_window_update_check.py`

**Interfaces:**
- Consumes: `discard_completed_update(...)` after verified runtime-only installation.
- Consumes: `mark_update_cleanup_ready(...)` after a detached application installer starts successfully.

- [ ] Write failing tests proving runtime-only completion removes its whole release directory and successful installer launch creates a target-version cleanup marker, while failed installer launch creates none.
- [ ] Run the focused main-window tests and confirm they fail for the missing lifecycle calls.
- [ ] Update `_finish_runtime_update_install()` to remove the full update directory only for runtime-only plans and preserve the application installer for combined plans.
- [ ] Update `_launch_downloaded_installer_or_restart()` to write the cleanup marker only after `start_detached_command()` succeeds.
- [ ] Run the focused update UI and cache tests and confirm all pass.

### Task 4: Regression Verification

**Files:**
- Verify only; no production changes expected.

**Interfaces:**
- Consumes all update-cache and update-flow behavior from Tasks 1-3.

- [ ] Run `python -m unittest tests.test_update_cache tests.test_app_update tests.test_app_bootstrap tests.test_main_window_update_check tests.test_runtime_bootstrap`.
- [ ] Run `python -m unittest discover -s tests` and require zero failures.
- [ ] Run `git diff --check` and inspect `git status --short` to ensure unrelated `library_row` edits remain untouched.
- [ ] Commit only the update-cache implementation, tests, and plan with the project commit format.
