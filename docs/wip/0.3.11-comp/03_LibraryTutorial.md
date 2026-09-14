# 03. Library Tutorial

## Status

- **Fact:** Library는 import 영역과 Library 목록 영역으로 나뉘며 Group panel, song row, details view를 포함한다.
- **Decision:** 기본 튜토리얼은 곡을 실제로 가져오거나 삭제하지 않는다.
- **Decision:** `Quick Create`는 제작 기능으로 유지하며 온보딩 `Quick Start`와 구분한다. 기본 튜토리얼의 핵심 경로에서는 제외하고 도움말 주요 기능에서 설명한다.

---

## 1. Page role

### 페이지 소개

Library는 JJZero Audio에 사용할 곡을 등록하고 정리하는 곳이다.

여기서:

- YouTube 또는 로컬 파일을 가져온다.
- 그룹으로 곡을 정리한다.
- 제작에 사용할 Work Song을 지정한다.
- 곡별 Source/Vocal/Studio/Export 자산을 확인한다.
- 필요하면 이름 변경, 위치 확인, 관리 자산 삭제를 수행한다.

Library 자체는 Separation/Conversion/Studio의 세부 작업 화면을 대체하지 않는다.

---

## 2. 기본 작업 순서

1. YouTube URL 또는 로컬 파일로 곡을 가져온다.
2. 필요하면 Import Target에서 들어갈 그룹을 정한다.
3. Group, Search, Sort로 곡을 찾는다.
4. 제작할 곡을 Work Song으로 지정한다.
5. 상단 Work Song selector에서 현재 작업곡을 확인한다.
6. Song Details에서 생성된 자산과 결과를 관리한다.
7. 이후 Separation → Conversion → Studio → Export로 진행한다.

---

## 3. 주요 기능

### Import

현재 UI:

- `youtube_card`
- `drop_card`

YouTube 다운로드와 로컬 파일 추가가 서로 다른 입력 방식일 뿐 결과는 Library song으로 등록된다.

### Import Target

`library_import_target_combo`

새로 가져오는 곡이 들어갈 Library group을 지정한다.

### Groups

- `library_group_toggle_button`
- `library_group_panel`
- 계층형 group tree
- New Group
- rename/delete context action
- song drag/drop 또는 move selection

### Search / Sort

- `library_search_edit`
- `library_sort_combo`

Library 데이터 자체를 변경하지 않고 표시 항목을 좁히거나 순서를 바꾼다.

### Song Row

`SongListRow`에는 다음 작업이 있다.

- Work Song pin
- waveform
- details
- rename
- remove
- preview transport

### Work Song

Work Song은 Separation, Conversion, Studio에서 공유되는 현재 제작 대상이다.

Library row의 pin으로 지정하고 상단 Navigation의 `work_song_selector`에서 현재 값을 확인/변경할 수 있다.

### Song Details

`library_details_panel.stage_stack`

탭:

- Source
- Vocal
- Studio
- Export

각 stage에서 관련 파일을 보고 preview, 위치 열기, 삭제를 수행한다.

### Quick Create

현재 Library에 존재하는 실제 제작 기능이다.

- model
- pitch
- Start Quick Create
- separation + conversion의 단축 제작 경로

**온보딩 Quick Start와 이름/책임이 다르다.**

튜토리얼 완료 상태와 연결하지 않는다.

---

## 4. 주의할 점

- Work Song 지정은 파일 복사/삭제가 아니라 제작 대상 선택이다.
- Remove/Delete 계열은 실제 관리 자산에 영향을 줄 수 있으므로 튜토리얼이 실행하지 않는다.
- Group panel이 접혀 있어도 기능이 사라진 것이 아니다.
- Song Details는 곡/자산이 있어야 실제 row가 표시된다.
- Quick Create는 빠른 제작 기능일 뿐 표준 페이지 흐름을 숨기거나 대체하는 온보딩 UI가 아니다.

---

## 5. Semantic targets

| Target ID | Current mapping | Fallback |
|---|---|---|
| `library.import.youtube` | `MainWindow.youtube_card` | `library.import.files` |
| `library.import.files` | `MainWindow.drop_card` | Library import area |
| `library.import.group` | `MainWindow.library_import_target_combo` | Library import area |
| `library.groups.toggle` | `MainWindow.library_group_toggle_button` | Library list header |
| `library.groups.panel` | `MainWindow.library_group_panel` if visible | `library.groups.toggle` |
| `library.search` | `MainWindow.library_search_edit` | `library.list` |
| `library.sort` | `MainWindow.library_sort_combo` | `library.list` |
| `library.list` | `MainWindow.song_list` | Library content stack |
| `library.row` | first visible `SongListRow` | `library.list` |
| `library.row.work_song` | visible row `work_song_button` or row anchor | `library.row` |
| `library.row.actions` | visible row details/rename/remove group | `library.row` |
| `library.details` | `MainWindow.library_details_panel` if active | `library.list` |
| `library.details.stages` | `library_details_panel.stage_stack` if active | `library.details` |
| `library.quick_create` | `MainWindow.quick_create_panel` | Library import area |
| `navigation.work_song` | `primary_navigation.work_song_selector` | Primary navigation |

Import area의 `import_panel`은 현재 local variable이므로 필요하면 기존 frame을 `self.library_import_panel` alias로 노출하거나 TargetRegistry 등록만 추가한다. 새 panel을 만들지 않는다.

---

## 6. Interactive tutorial

### LIB-01 — 곡 가져오기

**Target:** `library.import.files` + 가능하면 `library.import.youtube` union  
**Text:** "곡은 YouTube 주소 또는 로컬 파일로 Library에 가져올 수 있습니다. 튜토리얼에서는 실제 가져오기를 실행하지 않습니다."  
**Interaction:** 차단  
**Data change:** 없음  
**Fallback:** import area frame

### LIB-02 — 가져올 그룹

**Target:** `library.import.group`  
**Text:** "가져오기 전에 이 위치에서 곡이 들어갈 그룹을 정할 수 있습니다. 그룹을 쓰지 않아도 됩니다."  
**Interaction:** 차단  
**Data change:** 없음

### LIB-03 — 그룹 관리

**Target:** visible이면 `library.groups.panel`, 아니면 `library.groups.toggle`  
**Text:** "그룹은 많은 곡을 계층적으로 정리합니다. 그룹 패널이 닫혀 있으면 폴더 버튼으로 다시 열 수 있습니다."  
**Interaction:** 차단  
**Temporary state:** 패널을 강제로 열지 않음. 현재 layout preference를 보존.

### LIB-04 — 곡 찾기

**Target:** `library.search` + `library.sort` union  
**Text:** "검색과 정렬은 Library 표시만 바꾸며 곡 파일을 변경하지 않습니다."  
**Interaction:** 차단

### LIB-05 — 곡 목록

**Target:** `library.row` 또는 `library.list`  
**Text:** "각 행에는 곡 정보와 파형, 작업곡 지정, 상세 보기, 이름 변경, 제거 기능이 있습니다."  
**Interaction:** 차단  
**Fallback copy:** "현재 Library가 비어 있습니다. 곡을 가져오면 이 영역에 행이 나타납니다."

### LIB-06 — Work Song 지정

**Target:** `library.row.work_song` → 없으면 `library.row` → 없으면 `library.list`  
**Text:** "핀 버튼으로 이 곡을 Work Song으로 지정합니다. Work Song은 Separation, Conversion, Studio가 공유하는 현재 제작 대상입니다."  
**Interaction:** 차단  
**Note:** hover reveal 상태를 실제 hover로 강제하지 않는다.

### LIB-07 — 공통 Work Song selector

**Target:** `navigation.work_song`  
**Text:** "현재 Work Song은 상단에서도 확인하고 바꿀 수 있습니다. 제작 페이지가 바뀌어도 같은 작업곡을 사용합니다."  
**Interaction:** 차단

### LIB-08 — 상세와 파일 관리

**Target:** 현재 details view가 열려 있으면 `library.details.stages`, 아니면 `library.row.actions` 또는 `library.list`  
**Text:** "상세 보기에서는 Source, Vocal, Studio, Export 단계별 파일을 확인하고 미리듣기, 위치 열기, 삭제를 할 수 있습니다."  
**Interaction:** 차단  
**Fallback:** details가 없어도 설명 후 종료.

---

## 7. Quick Create treatment

기본 interactive tutorial step에는 넣지 않는다.

이유:

- Library 핵심 개념을 먼저 이해시키는 것이 목적
- 표준 제작 흐름은 Separation/Conversion 각 페이지에서 설명
- Quick Create가 onboarding shortcut처럼 오해되는 것을 방지

Help의 `주요 기능`에서는 실제 제작 기능으로 짧게 설명한다.

---

## 8. Tests

- Library empty
- 1 song
- multiple songs
- group panel open/closed
- search active
- details view open/closed
- row hover 여부와 무관하게 tutorial 진행
- work-song loading animation 중에도 crash 없음
- Quick Create running 중 tutorial target resolve가 UI를 조작하지 않음

---

## 9. Acceptance

> Library에 데이터가 전혀 없어도 8단계를 끝까지 볼 수 있고, 데이터가 있으면 실제 현재 row/details 위치를 정확히 강조하지만 어떤 곡/그룹/파일도 변경하지 않는다.
