# Project Rules

This document records the working rules for this project.

## Workflow

- Discuss and agree before changing implementation direction.
- Work in small reviewable steps.
- Build one feature, verify it, then move to the next feature.
- Do not modify the original reference projects.
- Use original projects only as references or source material to copy from.
- All edits for this product must happen inside this repository.
- Do not commit unless the user explicitly asks for a commit.

## Commit Format

- Use `YY/MM/DD Workstream Sequence - Summary` for commit titles.
- Use the Asia/Seoul date. Use `YY/MM/DD~DD` only when one commit intentionally covers work across multiple dates.
- Keep a stable workstream name and increment its sequence for related work, starting at `01`.
- Write the commit body with a `DONE` section followed by verified completed items.
- Write a `TODO` section with only the agreed next work that remains relevant to this project.
- Keep the title concise and use Korean for detailed `DONE` and `TODO` items.

## Scope Control

- Do not add future features before they are implemented end-to-end.
- Do not add placeholder modules, product types, flags, or configuration fields for features that do not exist yet.
- Link downloading is out of scope until it is explicitly requested.
- RVC conversion, mixing, and video replacement should be added only after the separation UI is reviewed.

## Code Structure

- Keep each script/module responsible for one clear area.
- UI modules should own layout, user input, status display, and presentation behavior.
- Pipeline modules should own domain operations such as separation, conversion, mixing, and video replacement.
- Shared reusable behavior should be separated when it has real reuse value.
- Avoid thin wrappers that only forward calls without adding validation, ownership, or clearer intent.
- Prefer direct, intent-revealing call sites over hidden setup state.
- Keep file/path handling explicit and easy to trace.

## Reusable Services

- Extract subprocess execution when multiple pipeline steps need it.
- Extract environment checks when multiple features need tool availability checks.
- Extract workspace/output path handling when multiple features create job outputs.
- Do not create broad utility dumping grounds.
- Prefer focused modules with narrow responsibilities.

## UI Direction

- The app should feel like a real desktop tool, not a default Tkinter prototype.
- Improve the UI through a dedicated theme/style layer.
- Keep UI behavior separate from audio processing logic.
- Do not give every `QWidget` an opaque global background. Window roots and visual panels must opt into an explicit surface role.
- Use `TransparentContainer` for layout-only wrappers and `SurfaceFrame` for reusable visual surfaces instead of relying on incidental QSS inheritance.
- Parent dynamic child widgets before calling `show()`, `setVisible(True)`, or measuring them for an item view.
- Cover dynamic Qt screens with a top-level `Show` event regression test so child widgets cannot flash as temporary windows.
- Keep the application-wide `WindowLifecycleGuard` enabled; legitimate non-dialog top-level widgets must opt in explicitly or use a framework window type such as popup, tooltip, or splash screen.
- Required user inputs should fail clearly instead of failing silently.
- Show meaningful status and result paths after each operation.

## Assets And Generated Files

- Keep generated outputs out of Git.
- Keep local models, runtimes, caches, and large media files out of Git.
- Keep source code, docs, and small configuration files tracked.
- Do not depend on absolute paths from old local projects at runtime.

## Encoding

- Markdown files should be valid UTF-8.
- Korean text is allowed when it remains readable.
- Do not preserve broken Korean text; rewrite it clearly or use concise English.
