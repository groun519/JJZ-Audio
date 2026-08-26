# Session Architecture Audit

## Session status

- Status: investigating
- Started: 2026-08-23 23:08 KST
- Scope: domain boundaries, persistence invariants, service/API contracts, and
  structural duplication
- Main.md lock: released after protocol initialization

## Method

Findings require a concrete source location, an observable failure mode, a trigger,
and independent confirmation by a test, second code path, or executable probe.
Unconfirmed concerns remain candidates and are not merged into `Main.md`.

## Confirmed findings

### A-001: An existing empty required track is never populated after a new RVC result appears

- Severity: high
- Area: Studio session restoration / asset synchronization
- Evidence:
  - `studio_assets.build_default_studio_tracks()` builds the active converted-vocal
    clip correctly when a converted asset exists.
  - `studio_session._session_with_required_tracks()` reduces the current session
    to `existing_roles` and only appends a default track when its *role* is absent.
    It never reconciles an existing empty `converted_vocal` track with the newly
    available active converted asset.
- Trigger:
  1. Open/save Studio after separation but before the first RVC conversion. This
     persists an empty required `converted_vocal` track.
  2. Complete an RVC conversion and activate its output.
  3. Reload the Studio session.
- Executable confirmation (2026-08-23): a temporary real WAV/package probe printed
  `before_clips=0`, `after_asset_exists=True`,
  `after_active_converted=vocals_rvc_new.wav`, and `after_clips=0`.
- User impact: the converted result is present in the sound pool/catalog but the
  required converted-vocal timeline track remains empty until the user manually
  places it. This can also make a restored project appear to have lost an RVC result.
- Missing coverage: current tests verify that wholly missing roles are backfilled,
  but do not cover an existing required role whose default asset becomes available
  later.
- Recommended direction: reconcile untouched/empty required tracks against current
  default assets while preserving any track that contains user-edited clips. Add a
  transition test for separation-only session -> conversion -> reload.

### A-002: One unavailable media asset causes the entire edited video track to be replaced

- Severity: critical
- Area: Studio media restoration / non-destructive editing
- Evidence: `studio_assets.sync_studio_video_track()` preserves the existing video
  track only when *every* clip reference is currently available. If one reference is
  absent, it constructs a new one-clip default track from the active media asset.
- Trigger: place two or more media clips, edit their timing/track mix, then remove or
  temporarily disconnect any one referenced media file and reload the Studio project.
- Executable confirmation (2026-08-23): a two-clip track containing one available and
  one missing media reference changed from clip IDs
  `['clip-kept-edited', 'clip-missing']` to
  `['clip-video-d5dff1e49945']`; track volume changed from `137` to `100`, and the
  surviving edited clip timing `(5000, 1000, 8000)` was reset to `(0, 0, 10000)`.
- User impact: a temporary missing drive/file or intentional pool deletion can erase
  all video timeline edits, including unrelated valid clips, without an explicit
  destructive action. This violates the project's missing-asset recovery model.
- Contract inconsistency: audio references are retained and surfaced through the
  Studio asset manifest as unavailable, whereas video references are destructively
  rewritten during load.
- Missing coverage: no test exercises a partially available multi-clip video track.
- Recommended direction: preserve the session track verbatim and mark individual
  references unavailable; only seed a default video track when no video track has
  ever existed. Repair/relink must be explicit rather than load-time replacement.

### A-003: Export silently omits unavailable audible clips and succeeds with a partial mix

- Severity: critical
- Area: Studio audio/video export correctness
- Evidence:
  - `song_export._timeline_mix_sources()` calls `_mix_asset_path()` for every audible
    clip and silently `continue`s when the asset cannot be resolved.
  - `build_song_mix_sources()` only raises when *no* sources remain. If any other
    clip resolves, audio export and video render both proceed with the incomplete
    source set.
  - `MainWindow._start_audio_mix_export()` flushes autosave and immediately starts
    `library.export_audio_mix()`; the missing-asset status shown while restoring the
    Studio page is not an export gate.
- Trigger: retain two audible timeline clips, then delete, detach, move, or disconnect
  the file referenced by only one clip and export audio or video.
- Executable confirmation (2026-08-23): a real temporary song package with one valid
  original-vocal clip and one missing converted-vocal clip reported
  `audible_clip_count=2`, `mix_source_count=1`, and returned the valid source without
  raising an error.
- User impact: an export can be reported as successful even though a vocal,
  instrumental, or edited clip is absent from the rendered result. This is silent
  output corruption rather than a recoverable export failure.
- Internal trigger confirmation: removable Studio pool cards emit
  `remove_requested`; `MainWindow._remove_studio_pool_asset()` routes the request to
  `SongAssetRemovalService`, which deletes managed media/vocal data without first
  removing or relinking every timeline reference. Therefore this state is reachable
  through supported app actions, not only external filesystem damage.
- Missing coverage: export tests cover all-muted/no-source rejection but not a mixed
  set of resolvable and unresolvable audible clips.
- Recommended direction: validate every audible clip reference before render and
  fail with a structured list of missing assets. If partial export is ever desired,
  require an explicit user opt-in and record omissions in the job diagnostics.

### A-004: Export continues after Studio autosave fails and renders stale disk state

- Severity: critical
- Area: Studio autosave / export transaction boundary
- Evidence:
  - `StudioSessionAutosave.flush()` returns `False` when an in-flight or synchronous
    save fails and retains retryable pending data for ordinary failures.
  - Callers that restore Studio or open project history correctly stop when
    `flush() is False`.
  - `MainWindow._start_audio_mix_export()` and `_start_video_render()` call
    `flush()` but ignore its return value, then dispatch export workers.
  - `SongLibrary.export_audio_mix()` and `render_video()` do not receive the live
    session; both reload it from package storage with `load_package_studio_session()`.
- Trigger: make a Studio edit, then encounter any autosave failure (full/read-only
  drive, interrupted storage, permission error) and immediately export.
- Executable confirmation (2026-08-23): invoking the real audio export start method
  with an autosave object returning `False` still produced
  `dispatch_calls=[('worker_started', 'Export Mix')]`.
- User impact: the application can export the last successfully saved timeline while
  presenting it as the current mix. Recent cuts, positions, gain, mute, pitch, and FX
  edits may all be absent without an export error.
- Missing coverage: autosave tests verify the `False` return and retry behavior, but
  no main-window export test asserts that a failed flush blocks worker dispatch.
- Recommended direction: treat save + render as one transaction boundary. Abort both
  audio and video export on a failed flush, keep controls enabled, and show the save
  error. Prefer passing an immutable live session snapshot into the worker after a
  confirmed save instead of reloading mutable package state implicitly.

### A-005: Realtime preview and export apply volume on opposite sides of nonlinear FX

- Severity: high
- Area: Studio playback/export fidelity contract
- Evidence:
  - Offline `audio_mix_processing.process_mix_source()` applies source volume before
    reverb, hard tune, delay, doubler, and character FX.
  - Realtime preparation bakes only level match/reverb. `AudioPlayer` then processes
    the remaining live effect chain first and multiplies the result by track volume
    afterward in `_mix_effected_chunk()`.
  - Linear effects may conceal the discrepancy, but distortion, bit crushing, radio
    filtering, hard tune, and chained character effects are level-dependent or
    nonlinear and cannot commute with gain.
- Trigger: apply a character/nonlinear FX to a clip and set its effective track/clip
  gain substantially above or below unity, then compare playback with export.
- Executable confirmation (2026-08-23): a 0.8-amplitude sine, 10% source volume, and
  the built-in `overdrive` distortion produced preview RMS `0.074738` versus export
  RMS `0.342997`, a 4.589x level difference, with maximum sample difference
  `0.357159`.
- User impact: users cannot trust Studio monitoring to predict the rendered file.
  Tone, saturation, loudness, and possibly pitch processing can change materially
  after export even with no setting changes.
- Missing coverage: realtime tests validate individual FX and live updates, but no
  parity test renders the same source/effect/gain graph through both engines.
- Recommended direction: define one canonical signal graph and use it in both paths.
  Either bake pre-FX gain into realtime buffers or move offline gain to the same
  post-FX stage, then add sample/RMS parity tests for every effect and representative
  chained presets at non-unity gain.

### A-006: Video source audio ignores the media track's mute, volume, solo, and pan

- Severity: high
- Area: Studio media audio / video render fidelity
- Evidence:
  - A video track can be selected in `StudioTimeline`; `StudioInspector.set_selection()`
    opens the normal track page and `_load_track()` exposes mute, solo, volume, and
    pan for every `StudioTrack`, including `TRACK_VIDEO`.
  - `_visual_clips()` flattens video clips into `_VisualClip`, which contains only
    timing, visual settings, and the `source_audio_enabled` boolean. It never carries
    the owning track or any mix state.
  - `_render_filter()` trims and delays enabled media audio, then mixes it at unity
    with `amix normalize=0`. There is no mute gate, volume filter, pan filter, solo
    resolution, or track-state input anywhere in the video render path.
- Trigger: enable `Use Original Audio` for a video clip, select the video track, set
  it to mute or 0% volume (or change solo/pan), and render the video.
- Executable confirmation (2026-08-23): two otherwise identical sessions were built
  with video track states `(muted=False, volume=100, pan=0)` and
  `(muted=True, volume=0, pan=-100)`. With the same real MP4 and mix WAV, both
  `_visual_clips()` tuples were equal and both generated FFmpeg commands were equal
  except for the output filename. The filter graph mixed the video stream directly
  through `atrim`, `adelay`, and unity `amix`.
- User impact: a track that appears muted or silent in Studio can reappear at full
  volume in the rendered video. Solo and pan decisions are likewise discarded, so
  the final soundtrack can contradict the visible project state.
- Missing coverage: the current video-export command test checks that enabled source
  audio is delayed and mixed, but never varies or asserts the owning track mix state.
- Recommended direction: resolve media-audio sources through the same audible-track
  policy used by Studio audio, carry the owning track state into render inputs, and
  apply mute/solo, effective gain, and pan explicitly. Add command and rendered-RMS
  tests for muted, zero-volume, panned, and soloed media tracks.

### A-007: Video export silently drops missing visual clips and reports success

- Severity: critical
- Area: Studio video export / missing-asset integrity
- Evidence:
  - `_resolved_timeline_clips()` includes only references that currently resolve and
    silently omits every missing video/image clip.
  - `can_render_song_video()` returns `True` when that filtered tuple contains any
    clip; it does not compare the count against the media track in the session.
  - `_visual_clips()` and `render_song_video()` therefore render the reduced tuple
    without a missing-media validation gate.
- Trigger: create a timeline with two or more visual clips, then delete, disconnect,
  or move one managed media file while at least one other visual remains available,
  and render the video.
- Executable confirmation (2026-08-23): a real temporary song package contained two
  valid imported PNG clips plus an audible vocal track. After deleting one managed
  PNG, `can_render_song_video()` remained true, `_visual_clips()` reduced two session
  clips to one, and the real bundled FFmpeg path successfully produced an MP4 rather
  than rejecting the incomplete project.
- User impact: a video can be exported and presented as complete while an image,
  scene, or edited video section is missing. This is silent visual output corruption
  and is especially dangerous for long timelines where the omission may not be
  noticed before publishing.
- Relation to other findings: A-003 is the equivalent audio-mix omission; A-002 can
  destructively rewrite a partially missing video track during restoration. A-007
  remains independently reachable from a live/autosaved session before that rewrite
  and represents a separate export validation failure.
- Missing coverage: tests reject a session whose only media clip is missing, but do
  not cover a mixed available/missing visual set or assert full reference fidelity.
- Recommended direction: validate every visual clip reference before encoding and
  fail with the missing clip IDs/paths. Partial render should require an explicit
  opt-in and must be recorded in job diagnostics and output metadata.

### A-008: A failed Studio session commit can still replace its asset manifest

- Severity: high
- Area: Studio project persistence / diagnostic integrity
- Evidence:
  - `studio_session.save_studio_session()` writes `assets.json` through
    `save_studio_project_assets()` before it archives or commits the corresponding
    session payload.
  - The asset write and `commit_studio_project_session()` are separate atomic-file
    operations with no shared transaction or rollback.
  - `studio_project_missing_asset_ids()` trusts only `assets.json`; it does not
    reconcile that manifest against the session actually recovered from disk.
  - The supported history path has the same split: `restore_studio_project_revision()`
    commits only a prior session payload and never restores or rebuilds the matching
    asset manifest.
- Trigger: change the set of referenced/missing assets and then encounter a session
  commit failure after `assets.json` succeeds (permission change, full disk, I/O or
  journal error).
- Executable confirmation (2026-08-23): an initial saved session referenced one
  missing converted-vocal clip and correctly reported its asset ID. A second save
  removed that clip while `commit_studio_project_session()` was fault-injected to
  raise. After restart, the old session still contained `missing-clip`, but
  `studio_project_missing_asset_ids()` returned an empty tuple; the probe printed
  `inconsistent=True`.
- Normal-flow confirmation (2026-08-23): revision 1 contained a missing media
  reference, revision 2 removed it, and the manifest then reported no missing IDs.
  Restoring revision 1 through `restore_studio_project_revision()` brought back the
  `history-missing` clip while the missing-ID tuple remained empty, again without
  any injected failure.
- User impact: after a failed autosave and restart, Studio can suppress its missing
  media warning even though the restored timeline still references unavailable
  content. The inverse ordering can also leave false warnings for edits that never
  committed. This weakens the only visible safeguard before the partial exports in
  A-003 and A-007.
- Missing coverage: persistence tests cover successful reuse of an asset snapshot and
  recovery of session writes, but not a fault between asset-manifest and session
  commit or the asset state after restoring a historical revision.
- Recommended direction: commit the session and its asset-reference snapshot under
  one journal revision, or regenerate the availability manifest from the recovered
  session on load. A failed save must leave both authoritative files at the same
  revision; add failure tests at every write boundary.

### A-009: Video export truncates the visual timeline to the audio-mix duration

- Severity: critical
- Area: Studio timeline duration / video export fidelity
- Evidence:
  - `render_song_video()` renders the Studio audio mix first and defines
    `duration_ms` exclusively from `read_audio_metadata(mix_path)`.
  - `_visual_clips()` then computes `remaining = output_duration_ms -
    clip.timeline_start_ms` and clamps every visual clip to that audio-derived
    remainder. `_render_command()` also passes the same value to FFmpeg `-t`.
  - No code compares this duration with the end of the video/image timeline.
- Trigger: place an image or video clip whose timeline end is later than the last
  audible audio clip, then render the project.
- Executable confirmation (2026-08-23): a real package containing a one-second
  vocal clip and a three-second imported PNG clip was rendered with the bundled
  FFmpeg. `ffprobe` reported a 1,000 ms MP4, so 2,000 ms of valid visual timeline
  content was silently removed.
- User impact: intentionally delayed visuals, title/outro cards, or any scene after
  the soundtrack ends disappear from a successful-looking export. The timeline and
  rendered file therefore disagree even when every asset is available.
- Missing coverage: video export tests derive expected duration only from the fake
  audio mix and never place a visual clip beyond that boundary.
- Recommended direction: define project duration as the maximum end of every
  renderable visual and audible clip. Pad the audio stream with silence when the
  visual timeline is longer, and add real rendered-duration tests for audio-shorter,
  visual-shorter, delayed-start, and silent-tail cases.

### A-010: The UI enables video render for a project that the renderer always rejects

- Severity: high
- Area: video render capability contract / silent projects
- Evidence:
  - `can_render_song_video()` returns true solely from the presence of one resolved
    visual clip (or fallback source).
  - `MainWindow._refresh_export_page()` uses that result, together with the song's
    general export capability, to enable the video export action.
  - `render_song_video()` unconditionally calls `build_song_mix_sources()` before
    processing visuals. A session with tracks but no audible clips raises
    `AudioExportError`; the renderer has no silence-generation path.
- Trigger: keep a valid image/video timeline while muting all audio tracks, or create
  a media-only Studio session for a song that already has a separation output.
- Executable confirmation (2026-08-23): a real package with a valid imported PNG,
  one valid but muted vocal clip, and an attached vocal output returned
  `can_render=True`; the immediate render call failed with
  `AudioExportError("Add at least one audible clip to the Studio timeline.")`.
- User impact: the Export page presents an enabled Video action that can never
  complete for the visible project state. Users also cannot intentionally create a
  silent video despite having a fully valid visual timeline.
- Contract inconsistency: `SongVideoExportError` is the advertised video-service
  error boundary, but this expected state leaks an `AudioExportError` instead.
- Missing coverage: capability tests verify local-media resolution, while render
  tests always synthesize an audio mix and never assert capability/execution parity.
- Recommended direction: either support silent video by synthesizing a silent audio
  stream (preferred for an editor) or include audibility in the capability predicate
  and disable the action with a precise reason. In both cases, make capability and
  execution share one validation result and normalize expected failures to the video
  error contract.

### A-011: Realtime preview reorders reverb ahead of nonlinear effects

- Severity: high
- Area: Studio FX graph / preview-export parity
- Evidence:
  - `add_studio_clip_effect()` appends each effect to `StudioClip.effects`, and the
    session serializer/deserializer preserves that tuple order.
  - Offline `process_mix_source()` walks enabled reverb, hard-tune, delay, doubler,
    and character effects in the declared tuple order.
  - Realtime preparation instead partitions the same tuple by effect kind:
    `_baked_effects()` extracts every reverb and processes it into the decoded
    track, while `_realtime_effects()` extracts every other effect for later live
    processing. This always moves reverb ahead of all nonlinear live effects,
    regardless of its position in the user's chain.
- Trigger: put distortion before reverb on one clip, or otherwise combine reverb
  with a nonlinear character/hard-tune effect whose declared order matters.
- Executable confirmation (2026-08-23): the real preview preparation received the
  same 0.5-second tone with `(distortion, reverb)` and `(reverb, distortion)`.
  It produced byte-identical prepared tracks and identical live chains for both
  orders. The offline processor produced a maximum absolute difference of
  `0.9387`, mean absolute difference of `0.2172`, and RMS values `0.3592` versus
  `0.6097` for those two declared chains.
- User impact: Studio preview cannot predict the exported result. Two clips that
  preview identically can render with materially different loudness and timbre,
  so effect ordering and final-mix decisions are unreliable.
- Missing coverage: realtime tests cover isolated reverb, isolated delay, and
  isolated level match, but no mixed ordered chain compares preview output with
  export output.
- Recommended direction: execute one canonical ordered effect graph in both paths.
  If expensive effects must be baked, bake only a contiguous prefix (and retain
  the remaining suffix in order), or bake the complete chain; never partition the
  chain globally by effect kind. Add parity tests for both orders of every baked
  effect paired with a nonlinear live effect.

## Candidates under verification

None yet.

## Cross-check log

- 2026-08-23 23:08 KST: `Main.md` was empty. Initialized the shared lock protocol
  and session index while holding the first lock.
- 2026-08-23 23:13 KST: `RuntimeLogicAudit.md` independently confirmed A-001 by
  tracing the same role-only reconciliation contract and identifying the same
  missing transition coverage.
- 2026-08-23 23:14 KST: independently cross-validated `RLA-001`. Two calls to the
  real Windows named-mutex function both returned valid handles; the second left
  `GetLastError()==183` (`ERROR_ALREADY_EXISTS`), yet `qt_app.main` has no branch
  that rejects that state. Both handles were closed after the probe.
- 2026-08-23 23:42 KST: independently cross-validated `SOL-005` with the real
  `TaskWorker`. A model-A task was held after starting, the panel switched to
  model B, and then the task was released. The final panel state was
  `selected_model=model-b`, `displayed_dataset=model-a`, with model A's success
  status applied. This confirms both stale-result acceptance and cross-model UI
  state corruption without relying on Sol's original harness.
- 2026-08-23 23:54 KST: independently cross-validated `SOL-003` with the real
  `StudioSessionAutosave`. A save was paused after becoming `_inflight`,
  `discard("song-deleted")` was called, and the save was then released. The
  deleted song's marker file was still created (`marker_after_discard=True`),
  proving that `discard()` cannot invalidate work already owned by the executor.
