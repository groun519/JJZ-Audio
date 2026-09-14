# 08. Export Tutorial

## Status

- **Fact:** Export는 왼쪽 Export Song + Audio/Video 설정, 오른쪽 Exports result list 구조다.
- **Decision:** 초보 tutorial은 preset 중심으로 설명하고 Custom 세부값은 "필요할 때" 영역으로 취급한다.
- **Decision:** 실제 export/share/delete/rename은 tutorial에서 실행하지 않는다.

---

## 1. 페이지 소개

Export는 Studio 결과를 실제 오디오 또는 영상 파일로 만드는 페이지다.

여기서:

- 내보낼 Work Song을 고른다.
- Audio 또는 Video mode를 고른다.
- preset을 선택한다.
- 필요한 경우 format/quality 세부값을 조정한다.
- Export 실행 후 결과를 관리한다.
- 결과를 미리듣고, 이름 변경, 위치 열기, Drive 공유, 삭제를 할 수 있다.

---

## 2. 기본 작업 순서

1. Export Song 확인
2. Audio / Video mode 선택
3. 목적에 맞는 preset 선택
4. 필요하면 세부 설정 확인
5. Export 실행
6. 오른쪽 Exports 결과 확인
7. Preview / Rename / Open Folder / Drive / Remove 사용

---

## 3. Audio Export

현재 preset:

- Master WAV
- Lossless FLAC
- Share MP3
- Discord 10MB
- Custom

세부 설정:

- Format
- Sample Rate
- Bit Depth
- Output Level
- Compressed Bitrate
- Dither

기본 설명:

### Master WAV

편집/보관용 고품질 master.

### Lossless FLAC

손실 없이 파일 크기를 줄인 보관/전달용.

### Share MP3

호환성과 공유 편의 중심.

### Discord 10MB

Opus 기반으로 길이에 맞춰 목표 용량을 맞추는 공유 preset.

### Custom

사용자가 format/세부값을 직접 바꾼 상태.

---

## 4. Video Export

현재 preset:

- 1080p
- High
- 720p
- 10MB
- Custom

세부 설정:

- Resolution
- Frame Rate
- Video Quality
- Encoding Speed
- Audio Bitrate

10MB preset은 고정 resolution 하나만 쓰는 단순 preset이 아니라 내용/용량 목표에 맞춰 출력 전략이 달라질 수 있다.

---

## 5. Result management

오른쪽 `Exports` list:

- 생성된 audio/video 결과를 수정 시간 기준으로 표시
- preview
- rename
- open location
- Google Drive share/copy/delete share
- remove
- export folder 열기

결과가 없으면 `No exports yet.` empty state가 표시된다.

---

## 6. 주의할 점

- Audio와 Video preset은 서로 다른 설정 집합이다.
- preset을 선택한 뒤 세부값을 직접 바꾸면 Custom 상태가 될 수 있다.
- 10MB preset은 "항상 같은 화질"이 아니라 용량 제한을 우선하는 전달용 preset이다.
- Export 실행은 실제 파일을 생성하므로 tutorial에서 실행하지 않는다.
- Remove는 생성된 결과 파일 관리에 영향을 주므로 tutorial에서 실행하지 않는다.
- Drive share도 tutorial에서 호출하지 않는다.

---

## 7. Semantic targets

| Target ID | Current mapping | Fallback |
|---|---|---|
| `export.song` | `export_page.song_selector` | left panel |
| `export.mode` | `export_page.export_mode_buttons` union | left panel |
| `export.audio.controls` | `export_page.audio_controls` | left panel |
| `export.audio.presets` | `audio_controls.preset_buttons` union | audio controls |
| `export.audio.details` | format/sample/bit depth/level/bitrate/dither group | audio controls |
| `export.audio.action` | `audio_controls.export_button` | audio controls |
| `export.video.controls` | `export_page.video_controls` | left panel |
| `export.video.presets` | `video_controls.preset_buttons` union | video controls |
| `export.video.details` | resolution/fps/quality/encoding/audio bitrate group | video controls |
| `export.video.action` | `video_controls.export_button` | video controls |
| `export.results` | `export_page.export_content` / result panel | right panel |
| `export.result.row` | first visible `_ExportRow` | `export.results` |
| `export.open_folder` | `export_page.open_folder_button` | results header |

현재 mode segmented frame과 results panel은 local variable이므로 TargetRegistry용 alias 또는 기존 child lookup을 추가한다. 새 panel을 만들지 않는다.

---

## 8. Safe temporary mode switch

TutorialRunner는 Audio/Video 설정 위치를 보여주기 위해 **mode view만 임시 전환**할 수 있다.

조건:

- export settings value를 바꾸지 않음
- preset을 선택하지 않음
- 원래 Audio/Video mode를 종료 시 복구
- Export button을 누르지 않음

---

## 9. Interactive tutorial

### EXP-01 — Export Song

**Target:** `export.song`  
**Text:** "내보낼 곡을 먼저 확인합니다. Studio와 Library의 같은 song 단위를 기준으로 결과가 정리됩니다."  
**Interaction:** 차단

### EXP-02 — Audio / Video mode

**Target:** `export.mode`  
**Text:** "오디오 파일만 만들지, 영상까지 렌더링할지 선택합니다. 두 mode는 서로 다른 preset과 세부 설정을 사용합니다."  
**Interaction:** 차단

### EXP-03 — Audio preset

**Target:** runner가 Audio view를 임시 표시한 뒤 `export.audio.presets`  
**Text:** "Master WAV, Lossless FLAC, Share MP3, Discord 10MB 중 목적에 맞는 preset을 고를 수 있습니다. 직접 설정을 바꾸면 Custom이 됩니다."  
**Interaction:** 차단

### EXP-04 — Audio 세부 설정

**Target:** `export.audio.details`  
**Text:** "Format, Sample Rate, Bit Depth, Output Level, Bitrate와 Dither를 직접 조절할 수 있습니다. preset을 그대로 쓴다면 모두 이해할 필요는 없습니다."

### EXP-05 — Video preset / 세부 설정

**Target:** runner가 Video view를 임시 표시한 뒤 `export.video.presets`, 이어서 details  
**Text:** "영상은 1080p, High, 720p, 10MB preset과 Resolution, Frame Rate, Quality, Encoding Speed, Audio Bitrate 설정을 사용합니다."  
**Interaction:** 차단

### EXP-06 — Export 실행

**Target:** 현재 원래 mode 또는 Audio 기본의 action button  
**Text:** "설정을 확인한 뒤 Export를 누르면 실제 파일 생성 작업이 시작됩니다. 튜토리얼에서는 실행하지 않습니다."  
**Interaction:** 차단

### EXP-07 — 결과 관리

**Target:** `export.result.row` → 없으면 `export.results`  
**Text:** "완료된 결과는 오른쪽에 쌓입니다. Preview, Rename, Folder, Drive Share, Remove를 여기서 관리합니다."  
**Fallback copy:** "아직 내보낸 파일이 없습니다. Export가 끝나면 이 영역에 결과가 표시됩니다."  
**End:** 원래 mode 복구

---

## 10. Tests

- Export Song 없음
- Audio mode
- Video mode
- audio preset별
- video preset별
- Custom settings state
- results 0개
- audio result
- video result
- multiple results
- Drive unavailable
- export running
- narrow width
- temporary mode switch 후 원래 mode 복구

---

## 11. Acceptance

> 신규 사용자가 preset만으로도 "무엇을 선택해 어떤 파일을 만들고 결과를 어디서 관리하는지" 이해할 수 있고, 고급 사용자는 세부 설정 위치를 찾을 수 있어야 하며 tutorial이 실제 파일을 생성하거나 삭제하지 않아야 한다.
