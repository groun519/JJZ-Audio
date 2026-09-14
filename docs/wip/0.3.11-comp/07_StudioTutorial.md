# 07. Studio Tutorial

## Status

- **Fact:** Studio는 JJZero Audio에서 가장 복잡한 작업공간이다.
- **Fact:** 현재 구조는 왼쪽 Sound Pool + FX Pool, 중앙 Media Preview + Transport + Timeline, 오른쪽 Inspector다.
- **Decision:** Studio tutorial은 기능을 실제 실행시키지 않고 **작업공간 지도를 먼저 이해시키는 방식**으로 구성한다.
- **Decision:** custom-painted Timeline 내부 요소는 QWidget을 새로 만들지 않고 read-only geometry target으로 강조한다.

---

## 1. 페이지 소개

Studio는 Work Song의 vocal, instrumental, RVC take, media를 Timeline에 배치하고 편집하는 공간이다.

주요 작업:

- Sound Pool에서 음원/미디어 찾기
- Timeline에 clip 배치
- clip 이동/trim/split
- track 조정
- 여러 clip 선택
- snapping
- FX preset/effect 적용
- Inspector에서 clip/track/FX 세부값 조정
- media preview
- undo/redo/history

---

## 2. 기본 작업 순서

1. Sound Pool에서 사용할 asset을 찾는다.
2. asset을 Timeline에 배치한다.
3. clip 위치와 길이를 정리한다.
4. 필요하면 track을 추가/정리한다.
5. snapping, split, multi-selection으로 편집한다.
6. FX Pool에서 preset/effect를 clip에 적용한다.
7. Inspector에서 Gain/Pitch/Fade/Media/FX 값을 조정한다.
8. Preview/Transport로 결과를 확인한다.
9. 필요하면 Project History로 과거 revision을 확인한다.
10. 완성 후 Export page로 이동한다.

---

## 3. 화면 구조

```text
┌──────────────┬──────────────────────────────┬───────────────┐
│ Sound Pool   │ Media Preview                │ Inspector     │
│              ├──────────────────────────────┤               │
│              │ Transport                    │               │
├──────────────┤──────────────────────────────┤               │
│ FX Pool      │ Timeline                     │               │
│              │                              │               │
└──────────────┴──────────────────────────────┴───────────────┘
```

실제 splitter 비율은 사용자가 바꿀 수 있으므로 tutorial이 고정 layout으로 되돌리지 않는다.

---

## 4. Sound Pool

`studio_editor.sound_pool`

기능:

- Search sounds
- role filter
  - All
  - Vocal
  - Inst.
  - RVC
  - Media
- Grid/List view
- asset cards
- drag to Timeline
- managed asset remove

튜토리얼은 drag/remove를 실행하지 않는다.

---

## 5. FX Pool

`studio_editor.fx_pool`

현재 Presets:

- Synth
- Lush
- Karaoke
- Animatronic
- Walkie-Talkie
- Broken Robot

현재 Effects:

- Reverb
- Delay
- Doubler
- Radio Filter
- Ring Modulator
- Bitcrusher
- Distortion
- Level Match
- Hard Tune

사용 방식:

- preset/effect card를 Timeline clip 위로 drag
- Inspector의 FX page에서 적용 chain과 세부값 편집

튜토리얼은 실제 effect를 drop하지 않는다.

---

## 6. Media Preview

`video_preview_panel`

기능:

- image/video preview
- file drop
- URL source
- saved media reuse
- local location open
- media source change/clear
- download 가능한 URL source

Media Preview는 Timeline의 audio edit와 별개의 "영상/이미지 결과 화면" 역할을 한다.

---

## 7. Transport

`studio_transport_bar`

현재 기능:

- play/pause + seek
- Undo
- Redo
- Cut Tool / Split
- Snapping
- Zoom

Shortcuts:

- Space: play/pause
- Ctrl+B: Cut Tool
- Esc: Cut Tool 종료
- N: Snapping toggle
- Alt hold: snapping 임시 bypass
- Ctrl+Z / Ctrl+Y: Undo / Redo

---

## 8. Timeline

`studio_editor.timeline`

지원:

- playhead drag/seek
- track 선택
- track add/remove/collapse
- track mute/volume
- asset drop
- effect drop
- clip move
- trim left/right
- split
- clip delete
- Shift toggle multi-select
- marquee multi-select
- multi-clip group move
- snapping
- horizontal/vertical scroll
- zoom에 따른 scale

Timeline은 custom paint 기반이므로 clip/track이 child QWidget이 아닐 수 있다.

---

## 9. Inspector

`studio_editor.inspector_scroll` / `studio_editor.inspector`

선택 상태에 따라 화면이 바뀐다.

### Clip

Tabs:

- Clip
- Audio
- Media
- FX

Clip/Placement:

- Timeline Position
- Clip Duration
- Source In/Out
- Fade In/Out

Audio:

- Gain
- Pitch
- Mute 관련 clip controls

Media:

- Display Duration
- Fit/Fill
- Scale
- Horizontal/Vertical Position
- source audio

FX:

- effect chain
- effect editor

### Track

- Mute
- Solo
- Volume
- Pan
- Track name/info

### Multi Selection

- selected clips summary
- mute state
- relative Gain change
- relative Pitch change
- Apply

---

## 10. Project History

`studio_editor.project_history_button`

현재 Studio project의 revision history를 연다.

Undo/Redo와 목적이 다르다.

- Undo/Redo: 현재 editing history
- Project History: 저장된 project revision 확인/restore

튜토리얼은 restore를 실행하지 않는다.

---

## 11. 주의할 점

- Sound Pool의 Remove는 실제 managed asset 관리 작업일 수 있으므로 tutorial에서 절대 실행하지 않는다.
- Timeline의 clip delete/move/trim/split도 tutorial이 실행하지 않는다.
- FX drag는 실제 session을 변경하므로 tutorial에서 실행하지 않는다.
- Split button은 clip 상황에 따라 disabled일 수 있다.
- Inspector는 현재 선택에 따라 내용이 달라지므로 빈 상태가 정상이다.
- Snapping은 N으로 끌 수 있고 Alt를 누르는 동안 임시 bypass 가능하다.
- Timeline splitter와 scroll 위치는 사용자의 작업 상태이므로 tutorial이 영구 변경하지 않는다.

---

## 12. Semantic targets

| Target ID | Current mapping | Fallback |
|---|---|---|
| `studio.workspace` | `studio_workspace_splitter` | Studio page root |
| `studio.sound_pool` | `studio_editor.sound_pool` | left sidebar |
| `studio.sound_pool.filters` | search + role filter | sound pool |
| `studio.fx_pool` | `studio_editor.fx_pool` | left sidebar |
| `studio.media_preview` | `video_preview_panel` | center top area |
| `studio.transport` | `studio_transport_bar` | center |
| `studio.transport.undo_redo` | undo + redo buttons | transport |
| `studio.transport.split` | `split_button` | transport |
| `studio.transport.snap` | `snap_button` | transport |
| `studio.transport.zoom` | `zoom_slider` | transport |
| `studio.timeline` | `studio_editor.timeline_panel` | center lower area |
| `studio.timeline.view` | `studio_editor.timeline` | timeline panel |
| `studio.timeline.clip` | read-only first visible clip rect provider | timeline view |
| `studio.timeline.track` | read-only first visible track rect provider | timeline view |
| `studio.inspector` | `studio_editor.inspector_scroll` | right side |
| `studio.inspector.fx` | inspector FX tab/chain if available | inspector |
| `studio.history` | `studio_editor.project_history_button` | timeline header |

---

## 13. Timeline geometry helpers

Tutorial 구현을 위해 custom-painted Timeline에 새 보이는 UI를 만들지 않는다.

필요하면 다음 **read-only helper**만 추가한다.

```text
tutorial_first_visible_clip_rect() -> QRect | None
tutorial_first_visible_track_rect() -> QRect | None
tutorial_timeline_edit_area_rect() -> QRect
```

규칙:

- 기존 `_clip_by_id`, track geometry 계산 재사용
- edit/session mutation 없음
- target 없으면 None
- Tutorial 코드에 HEADER_WIDTH, ruler height 등의 좌표 복제 금지

---

## 14. Interactive tutorial

### STU-01 — Studio 전체 구조

**Target:** `studio.workspace`  
**Text:** "Studio는 왼쪽 재료, 중앙 Preview/Timeline, 오른쪽 Inspector의 세 영역으로 나뉩니다."  
**Interaction:** 차단

### STU-02 — Sound Pool

**Target:** `studio.sound_pool`  
**Text:** "현재 Work Song에서 사용할 수 있는 Vocal, Instrumental, RVC take와 Media가 모입니다. 검색과 role filter로 필요한 asset을 찾습니다."  
**Fallback:** empty sound pool도 그대로 강조

### STU-03 — FX Pool

**Target:** `studio.fx_pool`  
**Text:** "Preset과 개별 effect를 clip에 drag해 적용합니다. Preset은 여러 effect의 조합일 수 있습니다. 튜토리얼에서는 실제로 적용하지 않습니다."

### STU-04 — Media Preview

**Target:** `studio.media_preview`  
**Text:** "이미지나 영상을 사용하는 작업은 이 영역에서 결과 화면을 확인합니다. 파일, URL, 저장된 media source를 사용할 수 있습니다."

### STU-05 — 재생과 편집 도구

**Target:** `studio.transport`  
**Text:** "재생, Undo/Redo, Cut Tool, Snapping, Zoom을 한 줄에서 제어합니다. Space는 재생/일시정지입니다."

### STU-06 — Timeline과 Track

**Target:** `studio.timeline.track` → 없으면 `studio.timeline.view`  
**Text:** "Timeline은 실제 배치 공간입니다. 각 Track에는 clip이 놓이며 track 자체도 선택, 추가, 제거, 접기, mute/volume 조정이 가능합니다."  
**Interaction:** 차단

### STU-07 — Clip 이동과 Trim

**Target:** `studio.timeline.clip` → 없으면 `studio.timeline.view`  
**Text:** "Clip 본체를 drag하면 위치를 옮기고, 양 끝을 drag하면 Source 범위를 trim합니다. 현재 clip이 없으면 Sound Pool asset을 배치했을 때 이 기능을 사용할 수 있습니다."  
**Interaction:** 차단  
**No clip:** fake clip 생성 안 함

### STU-08 — 여러 Clip 선택

**Target:** `studio.timeline.view`  
**Text:** "Shift 클릭으로 선택을 추가/해제하거나 빈 Timeline 영역을 drag해 marquee로 여러 clip을 선택할 수 있습니다. 여러 clip은 함께 이동하거나 Inspector에서 상대 Gain/Pitch를 조정할 수 있습니다."

### STU-09 — Cut Tool

**Target:** `studio.transport.split`  
**Text:** "Ctrl+B로 Cut Tool을 켜고 clip을 원하는 위치에서 나눌 수 있습니다. Esc로 종료합니다. 분할 가능한 clip이 없으면 버튼이 비활성일 수 있습니다."  
**Interaction:** 차단

### STU-10 — Snapping

**Target:** `studio.transport.snap`  
**Text:** "Snapping은 clip, playhead, split 위치를 주변 기준점에 붙입니다. N으로 켜고 끄며, Alt를 누르는 동안만 임시로 무시할 수 있습니다."  
**Interaction:** 차단

### STU-11 — Undo/Redo와 Zoom

**Target:** `studio.transport.undo_redo` + `studio.transport.zoom`  
**Text:** "편집을 되돌리거나 다시 적용하고, Zoom으로 긴 구간과 세밀한 구간을 오갈 수 있습니다. 튜토리얼은 현재 history나 zoom 값을 바꾸지 않습니다."

### STU-12 — Inspector

**Target:** `studio.inspector`  
**Text:** "선택한 대상에 따라 Inspector가 Clip, Track, Multi Selection 화면으로 바뀝니다. Clip에서는 위치/trim/fade, audio gain/pitch, media 배치, FX chain을 세부 조정합니다."  
**Fallback:** empty inspector

### STU-13 — Project History

**Target:** `studio.history`  
**Text:** "Project History는 저장된 revision을 확인하는 기능입니다. Undo/Redo보다 긴 범위의 복구에 사용합니다. 튜토리얼에서는 restore하지 않습니다."

---

## 15. Empty / busy behavior

### Studio asset 없음

- Sound Pool empty state 강조
- Timeline empty state 강조
- clip-specific step는 timeline fallback

### Clip 없음

- split button disabled여도 target 가능
- "clip이 있을 때 활성화" 설명

### Inspector empty

- inspector container 강조
- selected target에 따라 내용이 바뀐다는 설명

### Playback preparing/running

- Tutorial은 playback 상태를 바꾸지 않는다.
- UI busy 여부에 관계없이 overlay만 표시한다.

---

## 16. Tests

- completely empty Studio
- audio clip 1개
- 여러 track/clip
- multi-selection active
- FX 적용 clip
- media clip
- inspector clip/track/multi/empty
- split button enabled/disabled
- snapping on/off
- narrow left/right splitter
- long timeline scrolled
- zoom min/max
- project history button
- tutorial 중 resize
- custom-painted clip target가 사라지는 refresh 상황

---

## 17. Acceptance

> Studio tutorial이 사용자의 session을 한 번도 수정하지 않으면서도 Sound Pool → Timeline → 편집 도구 → FX → Inspector → History의 실제 관계를 설명하고, clip이 없는 빈 프로젝트에서도 동일한 순서로 끝까지 진행되어야 한다.
