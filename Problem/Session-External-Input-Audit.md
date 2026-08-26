# External Input and File Boundary Audit

## Session status

- Status: investigating
- Started: 2026-08-23 23:12 KST
- Scope: external URLs, Google Drive sharing/import, archive extraction, model and
  media import, subprocess argument boundaries, credential persistence, and
  diagnostic data exposure
- Main.md lock: not held; the shared document currently contains conflicting lock
  declarations and will not be edited until one authoritative unlocked state exists

## Method

A confirmed finding requires a concrete source location, a reproducible or
executable trigger, user impact, and a second form of evidence such as a focused
test, a second code path, or a runtime probe. Suspicions stay under candidates.

## Confirmed findings

### UI-STATE-01: Cleared RVC result selection was restored by later refreshes

- Severity: medium
- Status: fixed in the current worktree; not yet merged into the shared index
- Trigger: select a converted vocal, change the conversion input so the converted
  selection is cleared, then cause the conversion project/result list to refresh.
- Root cause: `WorkConvertSession`, `ConversionResultBrowser`, and
  `MainWindow._apply_conversion_result_context` each treated `None` as an
  uninitialized selection and independently fell back to a previous, active, or
  first converted take. An intentional clear therefore was not durable.
- Impact: the conversion timeline could show and monitor a vocal produced from a
  previous input, making the visible input and audible converted result disagree.
- Fix: retain an explicit cleared-selection state in `WorkConvertSession`, allow
  the RVC pool to rebuild without selecting a default, and make the timeline trust
  the session selection without a browser fallback.
- Verification: 55 focused conversion/session/UI tests pass, including refresh
  after an explicit clear, adding another separation result, switching songs, and
  preventing browser fallback. The full 1,438-test run reached completion with
  only four unrelated storage-migration errors caused by 337.9 MB free space being
  below those tests' 512 MB precondition.

## Candidates under verification

None yet.

## Cross-check log

- 2026-08-23 23:12 KST: reviewed all existing session scopes. Chose external-input
  and trust-boundary handling to avoid duplicating architecture, general async/UI,
  and vocal-cleanup investigations.
- 2026-08-23 23:12 KST: `Main.md` contained simultaneous `VocalCleanupAudit` and
  `Session-Architecture-Audit` lock declarations. No shared edit was attempted.
- 2026-08-23: confirmed and fixed `UI-STATE-01` after a user report that an older
  converted vocal sometimes remained visible. Kept this cross-scope finding here
  because the shared `Main.md` lock is still ambiguous.
