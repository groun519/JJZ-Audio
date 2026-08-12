# Studio Clip Reverb Design

## Objective

Add the first Studio Sound FX workflow: a non-destructive Reverb effect that users drag from an FX pool onto one timeline clip, edit in the Inspector, preview, and export with matching sound.

## Interaction Model

- The left Studio sidebar becomes a vertical splitter with Sound Pool above FX below. The default ratio is 65/35, both panes scroll independently, and the ratio is persisted.
- The FX pool starts expanded and initially contains one Reverb card.
- Dragging Reverb onto a timeline clip adds one Reverb instance to that exact clip. Dropping outside a clip does nothing.
- A clip may contain multiple effects in an ordered `effects` tuple. The first release exposes Reverb only, but the model is not Reverb-specific.
- A wide clip shows a `Reverb` chip; medium clips show a compact icon; narrow clips show one FX marker. Hovering the marker opens an anchored list so effects remain discoverable on short clips.
- Hovering an effect chip reveals a remove button. Removing an effect is undoable and never changes the source file.
- The Inspector uses browser-style tabs. `Clip` is always present for a selected clip; every effect adds its own tab. Closing an Inspector tab only changes the open tab. Effect deletion remains an explicit action inside the effect editor or on the timeline chip.

## Clip and Split Semantics

- Effects belong to `StudioClip`, not `StudioTrack` or the source asset.
- Splitting an effected clip copies the current effect settings to both resulting clips.
- Applying an effect after a split changes only the dropped fragment.
- Moving, trimming, fading, muting, and changing clip gain preserve the clip's effects.
- Reverb tails may continue beyond the source range and overlap later clips naturally. They do not modify adjacent clips.

## Data Model

`StudioClip.effects` stores an ordered tuple of `StudioEffect` values. `StudioEffect` contains a stable `effect_id`, a supported `kind`, an enabled flag, and typed Reverb settings. Studio session JSON advances from version 4 to version 5. Version 4 sessions load with empty effect tuples.

The first Reverb settings are:

- room height, length, and width
- pre-delay and decay time
- distance, brightness, and modulation
- early-reflection low/high frequency and gain
- reverb-tone low/high frequency and gain
- dry/wet mix
- direct, early-reflection, and reverb output gains

All settings appear in one editor. Values are clamped during session load so damaged or future files cannot destabilize rendering.

## Audio Architecture

- Reverb processing lives in a pure NumPy service shared by Studio preview and export.
- The processor generates a deterministic stereo impulse response from the saved settings and performs FFT convolution.
- Direct, early-reflection, and late-reverb components are mixed separately, then tone shaping and output gains are applied.
- Effects are processed after source range extraction and clip fades, before track pan and timeline placement.
- Any clip with an effect disables the direct multi-file preview optimization. Studio uses the existing rendered preview cache, guaranteeing preview/export parity.
- Rendering includes the effect tail in the output duration and applies a final finite-value guard and peak protection.

## Failure and Performance Rules

- Missing or unknown effects are ignored during playback but preserved only when they conform to the current session schema.
- Invalid numeric values fall back to safe defaults.
- Reverb rendering is deterministic for the same source and settings.
- Preview rendering remains cached through the existing Studio preview file path. Session mutations invalidate the queue and rerender on the next play.
- No external plugin, paid dependency, or source-file mutation is introduced.

## Verification

- Session v4 to v5 loading and v5 round-trip tests.
- Effect add, update, remove, undo, redo, and split-inheritance tests.
- DSP tests for dry identity, audible wet signal, tail extension, finite output, and deterministic output.
- Export tests for extended duration and preview/export shared processing.
- UI tests for FX dragging, exact clip targeting, responsive marker behavior, Inspector tabs, and persisted splitter sizing.
- Full project regression suite and a manual Studio smoke test with play, split, remove, undo, and export.
