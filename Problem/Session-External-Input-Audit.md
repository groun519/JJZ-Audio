# External Input and File Boundary Audit

## Session status

- Status: active; latest conversion-state pass verified
- Started: 2026-08-23 23:12 KST
- Scope: external URLs, Google Drive sharing/import, archive extraction, model and
  media import, subprocess argument boundaries, credential persistence, and
  diagnostic data exposure
- Main.md lock: released after merging `UI-STATE-01` and `UI-STATE-02`

## Method

A confirmed finding requires a concrete source location, a reproducible or
executable trigger, user impact, and a second form of evidence such as a focused
test, a second code path, or a runtime probe. Suspicions stay under candidates.

## Confirmed findings

### UI-STATE-01: Cleared RVC result selection was restored by later refreshes

- Severity: medium
- Status: fixed in commit `f54e78a`; merged into the shared index
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
  preventing browser fallback.

### UI-STATE-02: Late completion from a previous input replaced current preview

- Severity: medium
- Status: fixed in the current worktree; merged into the shared index
- Trigger: start RVC conversion from one vocal input, select another original,
  split, or cleanup vocal in the same song while the task is running, then let the
  earlier task finish.
- Root cause: `WorkTaskScope` validated only the song ID. The completion handler
  therefore considered an old input task current and activated its output.
- Impact: a correctly selected current input could display and monitor a newly
  completed file generated from the previous input, making the defect intermittent
  and timing-dependent.
- Fix: capture the starting `VocalInputChoice` and activate the output only when its
  choice ID, input path, and owner job directory still match the current input. A
  stale result is still registered and listed; it simply cannot steal focus.
- Verification: both stale-input and matching-input completion tests pass. Expanded
  conversion, playback, deletion, project, and library coverage passed 172 tests;
  the complete suite passed all 1,562 tests in 183.646 seconds.

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
- 2026-08-27: re-audited input changes, song changes, refresh, successful completion,
  result deletion, timeline playback, and pool selection. Confirmed `UI-STATE-01`
  remains fixed, found and fixed `UI-STATE-02`, and completed a green full-suite run.
