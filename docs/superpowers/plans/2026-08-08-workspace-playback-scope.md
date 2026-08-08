# Workspace Playback Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Play only the output tracks visible in the active Separation, Conversion, or Studio workspace while retaining one shared audio player and bottom transport.

**Architecture:** The active work song and output sound set remain global. `MainWindow` derives one `PlaybackQueue` from the active workspace scope: Separation includes original vocal and accompaniment, Conversion includes original vocal and the selected converted take, and Studio includes all available tracks. The existing `AudioPlayer` remains the sole mixer; switching workspace scopes rebuilds its source list at the current position when playback is active.

**Tech Stack:** Python 3, PySide6, existing `AudioPlayer`, `PlaybackQueue`, Qt unit tests.

## Global Constraints

- Do not modify the external RVC installation.
- Keep a single `AudioPlayer`; do not create per-card or per-page audio backends.
- Preserve library row preview as a single-file playback context.
- Keep selected work song and active converted take shared across the workspace.
- Keep Studio mix settings persisted through the existing studio session store.

---

### Task 1: Define Workspace Playback Scope

**Files:**
- Create: `src/jang_app/services/workspace_playback.py`
- Test: `tests/test_workspace_playback.py`

**Interfaces:**
- Produces `WorkspacePlaybackScope` enum with `SEPARATION`, `CONVERSION`, and `STUDIO`.
- Produces `scope_track_ids(scope) -> tuple[str, ...]`.
- Produces `scope_label(scope) -> str`.

- [x] Write failing tests for each scope's track IDs and display label.
- [x] Implement the enum and immutable scope mapping.
- [x] Verify the focused test file passes.

### Task 2: Build Scope-Limited Playback Queues

**Files:**
- Modify: `src/jang_app/qt_app/main_window.py`
- Modify: `tests/test_main_window_playback_navigation.py`

**Interfaces:**
- Consumes `WorkspacePlaybackScope` and `scope_track_ids`.
- Produces `MainWindow._workspace_playback_queue(scope) -> PlaybackQueue | None`.
- Produces `MainWindow._workspace_scope_for_page(page_index) -> WorkspacePlaybackScope | None`.

- [x] Write failing tests showing Separation excludes converted vocal, Conversion excludes accompaniment, and Studio includes all available tracks.
- [x] Replace the unconditional output queue builder with a scope-limited builder.
- [x] Keep mute and volume values aligned with their shared track IDs.
- [x] Verify focused playback tests pass.

### Task 3: Preserve Position While Switching Scope

**Files:**
- Modify: `src/jang_app/qt_app/main_window.py`
- Modify: `tests/test_main_window_playback_navigation.py`

**Interfaces:**
- Consumes `_workspace_playback_queue`.
- Updates `_sync_playback_queue_for_page` and `_refresh_output_playback_queue`.

- [x] Write failing tests for active playback moving between workspace scopes at the same position.
- [x] Rebuild the active source set at the current position only when its page scope changes.
- [x] Limit playhead updates to the active workspace surface.
- [x] Verify navigation and playback tests pass.

### Task 4: Make Converted Vocal Selection Explicit

**Files:**
- Modify: `src/jang_app/qt_app/vocal_results_panel.py`
- Modify: `src/jang_app/qt_app/main_window.py`
- Modify: `src/jang_app/services/i18n.py`
- Modify: `tests/test_vocal_results_panel.py`

**Interfaces:**
- Produces an always-visible conversion take selector in `VocalResultsPanel(mode="conversion")`.
- Emits the existing `converted_selected(Path | None)` signal.

- [x] Write a failing UI test that the conversion selector is visible with one or more takes and the embedded card selector is hidden.
- [x] Move conversion take selection into the panel header and show a readable model, pitch, and created-time label.
- [x] Keep selection synchronized with the active converted Studio track and page playback queue.
- [x] Verify focused UI tests pass.

### Task 5: Clarify the Bottom Transport Context

**Files:**
- Modify: `src/jang_app/qt_app/workspace_transport_dock.py`
- Modify: `src/jang_app/qt_app/main_window.py`
- Modify: `src/jang_app/services/i18n.py`
- Test: `tests/test_workspace_transport_dock.py`

**Interfaces:**
- Produces `WorkspaceTransportDock.set_playback_scope(scope: WorkspacePlaybackScope | None)`.

- [x] Write a failing widget test for the context label.
- [x] Add a compact context label such as Separation Preview, Conversion Compare, or Studio Mix without duplicating song selection or track controls.
- [x] Synchronize the label when navigating, changing work song, or clearing output.
- [x] Verify focused widget and playback tests pass.

### Task 6: Regression Verification and Documentation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [x] Update user-facing documentation for page-scoped playback and converted-take selection.
- [x] Run the complete test suite under the Windows Qt renderer.
- [x] Run `python -m compileall src` and `git diff --check`.
