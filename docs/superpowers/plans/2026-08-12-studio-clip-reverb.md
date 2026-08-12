# Studio Clip Reverb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add non-destructive, clip-scoped Reverb to Studio with drag-and-drop assignment, Inspector editing, timeline visibility, and identical preview/export rendering.

**Architecture:** Store typed effects on immutable `StudioClip` values and mutate them through focused timeline service functions so Studio history continues to provide undo/redo. Route effected sessions through the existing rendered Studio preview and process both preview and export with one deterministic NumPy Reverb engine.

**Tech Stack:** Python 3.11, PySide6, NumPy, WAV rendering, unittest/pytest, immutable dataclasses.

## Global Constraints

- Effects apply to a single clip fragment, never to a whole track or source file.
- Splitting copies effects to both resulting clips.
- Reverb tails continue naturally after clip source end.
- Preview and export must use the same processing function.
- The UI exposes all Reverb controls in one editor.
- Do not add paid services, external VST dependencies, or mutate original media.
- Preserve unrelated uncommitted Library Row changes.

---

### Task 1: Session v5 clip effect model

**Files:**
- Modify: `src/jang_app/services/studio_session.py`
- Test: `tests/test_studio_session.py`

**Interfaces:**
- Produces: `StudioReverbSettings`, `StudioEffect`, `StudioClip.effects`, session JSON v5.
- Consumes: existing `StudioClip`, `_clip_from_data`, `_clip_to_data`, and normalization helpers.

- [ ] **Step 1: Write failing tests** for v4 loading with `effects == ()`, v5 Reverb round-trip, and clamping invalid values.
- [ ] **Step 2: Run tests to verify RED** with `python -m pytest tests/test_studio_session.py -q` and confirm missing effect types/fields cause failure.
- [ ] **Step 3: Implement typed immutable values** with `StudioReverbSettings` defaults, `StudioEffect(effect_id, kind, enabled, reverb)`, `StudioClip.effects`, JSON serializers, and session version 5 accepting versions 2-4.
- [ ] **Step 4: Run tests to verify GREEN** with `python -m pytest tests/test_studio_session.py -q`.

### Task 2: Immutable clip effect editing

**Files:**
- Modify: `src/jang_app/services/studio_timeline.py`
- Test: `tests/test_studio_timeline.py`

**Interfaces:**
- Produces: `add_studio_clip_effect(session, clip_id, effect)`, `update_studio_clip_effect(session, clip_id, effect)`, `remove_studio_clip_effect(session, clip_id, effect_id)`.
- Consumes: `StudioEffect` and immutable `StudioSession` replacement helpers.

- [ ] **Step 1: Write failing tests** proving add/update/remove target one clip, duplicate IDs are rejected, missing IDs raise `StudioTimelineError`, and split clips inherit the full effects tuple.
- [ ] **Step 2: Run tests to verify RED** with `python -m pytest tests/test_studio_timeline.py -q`.
- [ ] **Step 3: Implement the minimal immutable mutations** through the existing clip replacement path.
- [ ] **Step 4: Run tests to verify GREEN** with `python -m pytest tests/test_studio_timeline.py -q`.

### Task 3: Deterministic Reverb DSP

**Files:**
- Create: `src/jang_app/services/audio_reverb.py`
- Modify: `src/jang_app/services/audio_mix_processing.py`
- Test: `tests/test_audio_reverb.py`
- Test: `tests/test_audio_mix_processing.py`

**Interfaces:**
- Produces: `apply_reverb(audio: np.ndarray, sample_rate: int, settings: StudioReverbSettings) -> np.ndarray` and effect-aware `process_mix_source(..., effects=())`.
- Consumes: float audio shaped `(frames, channels)` and clamped Reverb settings.

- [ ] **Step 1: Write failing tests** for zero-wet identity, nonzero wet tail, deterministic output, stereo preservation, finite samples, and sequential effect application.
- [ ] **Step 2: Run tests to verify RED** with `python -m pytest tests/test_audio_reverb.py tests/test_audio_mix_processing.py -q`.
- [ ] **Step 3: Implement deterministic impulse generation and FFT convolution** with separate direct, early, and late paths; map every saved control into impulse timing, damping, modulation, or gain.
- [ ] **Step 4: Add finite-value and peak guards** without normalizing quiet signals upward.
- [ ] **Step 5: Run tests to verify GREEN** with `python -m pytest tests/test_audio_reverb.py tests/test_audio_mix_processing.py -q`.

### Task 4: Preview and export parity

**Files:**
- Modify: `src/jang_app/services/audio_export.py`
- Modify: `src/jang_app/services/song_export.py`
- Modify: `src/jang_app/qt_app/main_window.py`
- Test: `tests/test_audio_export.py`
- Test: `tests/test_song_export.py`
- Test: `tests/test_main_window_playback_navigation.py`

**Interfaces:**
- Extends: `AudioMixSource.effects: tuple[StudioEffect, ...]`.
- Produces: effect tails included in mix length and `MainWindow._direct_studio_preview_duration()` returning zero for effected sources.

- [ ] **Step 1: Write failing tests** for effect propagation from clips, tail-preserving output length, and forced rendered preview for effected sessions.
- [ ] **Step 2: Run tests to verify RED** on the three focused test modules.
- [ ] **Step 3: Pass clip effects into `AudioMixSource`** and size the output from processed arrays rather than raw source ranges.
- [ ] **Step 4: Disable direct preview optimization when a source has effects** so preview and export share the renderer.
- [ ] **Step 5: Run focused tests to verify GREEN**.

### Task 5: FX pool and persisted left split

**Files:**
- Create: `src/jang_app/qt_app/studio_fx_pool.py`
- Modify: `src/jang_app/qt_app/studio_editor.py`
- Modify: `src/jang_app/qt_app/main_window.py`
- Modify: `src/jang_app/services/settings.py`
- Modify: `src/jang_app/qt_app/theme.py`
- Test: `tests/test_studio_fx_pool.py`
- Test: `tests/test_settings_rvc.py`
- Test: `tests/test_main_window_playback_navigation.py`

**Interfaces:**
- Produces: `STUDIO_EFFECT_MIME`, `StudioFxPool`, and persisted `StudioLayoutSettings.left_sizes`.
- Consumes: existing workspace splitter factory and Studio theme tokens.

- [ ] **Step 1: Write failing UI/settings tests** for a draggable Reverb card, 65/35 defaults, valid persisted sizes, and independent scroll containers.
- [ ] **Step 2: Run tests to verify RED**.
- [ ] **Step 3: Build the focused FX pool** and mount it below Sound Pool in a collapsible vertical splitter.
- [ ] **Step 4: Persist splitter sizes** with the existing debounced layout save.
- [ ] **Step 5: Run focused tests to verify GREEN**.

### Task 6: Exact-clip drop and timeline effect chips

**Files:**
- Modify: `src/jang_app/qt_app/studio_editor.py`
- Modify: `src/jang_app/qt_app/theme.py`
- Test: `tests/test_studio_editor.py`

**Interfaces:**
- Produces: `effect_dropped(clip_id, kind)`, effect chip hit regions, compact marker rendering, and remove requests.
- Consumes: `STUDIO_EFFECT_MIME` and Task 2 mutation functions.

- [ ] **Step 1: Write failing tests** proving drops only succeed over a clip, exact target clip receives Reverb, history records add/remove, undo/redo works, and narrow clips retain an FX hit target.
- [ ] **Step 2: Run tests to verify RED**.
- [ ] **Step 3: Add drag acceptance and target highlighting** without changing asset drag behavior.
- [ ] **Step 4: Paint responsive effect chips/markers and expose hover removal** through explicit hit regions.
- [ ] **Step 5: Connect mutations to Studio history** and run focused tests to verify GREEN.

### Task 7: Inspector effect tabs and full Reverb editor

**Files:**
- Create: `src/jang_app/qt_app/studio_reverb_editor.py`
- Modify: `src/jang_app/qt_app/studio_inspector.py`
- Modify: `src/jang_app/qt_app/studio_editor.py`
- Modify: `src/jang_app/qt_app/theme.py`
- Modify: `src/jang_app/services/i18n.py`
- Test: `tests/test_studio_reverb_editor.py`
- Test: `tests/test_studio_inspector.py`
- Test: `tests/test_studio_editor.py`

**Interfaces:**
- Produces: `reverb_changed(effect: StudioEffect)`, `effect_remove_requested(effect_id)`, and `Clip | Reverb` Inspector tabs.
- Consumes: current selected clip and Task 2 update/remove functions.

- [ ] **Step 1: Write failing tests** for tab population, close-without-delete behavior, all control ranges/defaults, live immutable updates, and explicit removal.
- [ ] **Step 2: Run tests to verify RED**.
- [ ] **Step 3: Implement the dedicated Reverb editor** with grouped Room, Time, Tone, Motion, and Output controls in one scrollable page.
- [ ] **Step 4: Add Inspector tabs** while preserving existing Clip/Track pages and selection behavior.
- [ ] **Step 5: Connect updates/removal through Studio history** and run focused tests to verify GREEN.

### Task 8: Integration and regression verification

**Files:**
- Modify only files needed for defects found by verification.

**Interfaces:**
- Verifies all interfaces from Tasks 1-7 as one Studio workflow.

- [ ] **Step 1: Run the Studio/audio focused suite** with `python -m pytest tests/test_studio_session.py tests/test_studio_timeline.py tests/test_audio_reverb.py tests/test_audio_mix_processing.py tests/test_audio_export.py tests/test_song_export.py tests/test_studio_fx_pool.py tests/test_studio_editor.py tests/test_studio_reverb_editor.py tests/test_studio_inspector.py tests/test_main_window_playback_navigation.py -q`.
- [ ] **Step 2: Run the full suite** with `python -m pytest -q`.
- [ ] **Step 3: Launch the app in background test mode** and inspect Studio at desktop and compact widths.
- [ ] **Step 4: Manually verify** Reverb drag, Inspector edit, split inheritance, one-side removal, undo/redo, playback tail, and exported WAV tail.
- [ ] **Step 5: Review `git diff`** to confirm unrelated Library Row work is preserved and no generated media or cache files are included.
