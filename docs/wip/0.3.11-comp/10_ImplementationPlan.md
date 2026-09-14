# 10. 0.3.11 Completion Implementation Plan

## Status

이 문서는 01~09 상세 목업을 Codex가 임의 UX 결정을 하지 않고 구현하기 위한 handoff다.

**중요:** 구현 시작 시 실제 작업 branch의 최신 코드를 다시 읽는다.

현재 mockup 작성 시점의 GitHub `main`은 온보딩 재작업 결과가 모두 올라와 있지 않을 수 있다. 따라서 이미 로컬/다른 branch에 구현된 Quick Start/Help 코드가 있다면 **삭제 전 반드시 실제 구조를 inventory**한다.

---

## 1. Non-negotiable decisions

### Tutorial

- Quick Start onboarding 제거
- page-based tutorial만 유지
- no global progress
- no completion state
- no checkbox/badge
- no reset
- no persisted seen/skipped/completed state
- no task-result watcher
- no fake tutorial data
- no domain mutation
- same page tutorial always replayable

### Help

- one global title-bar `?`
- menu: Tutorial / Report Problem
- Tutorial = one common dialog
- left page list + right detail
- narrow width = top page combo
- footer only Page Move / Tutorial Start
- current page = Page Move hidden
- no persistent help drawer

### Reporting

- one common report dialog
- Cloudflare Worker primary
- GitHub Issues final inbox
- no client GitHub write token
- no user GitHub login
- no additional Google permission
- final Send one click
- Outbox before network
- report privacy sanitizer

---

## 2. Terminology guard

두 용어를 혼동하지 않는다.

### Quick Start

제거 대상.

기존 onboarding / tutorial shortcut / progress concept.

### Quick Create

현재 Library의 실제 production feature.

`QuickCreatePanel`, `quick_production` pipeline 등.

**별도 제품 결정 없이는 삭제하지 않는다.**

Codex는 "빠른 시작 제거"를 보고 Quick Create production code를 지우면 안 된다.

---

## 3. Phase A — Existing onboarding audit / removal

먼저 actual implementation branch에서 다음을 찾는다.

검색어:

```text
Quick Start
quick_start
onboarding
tutorial progress
tutorial state
completed
skipped
reset tutorial
guided
walkthrough
help panel
```

목표:

1. 현재 Quick Start UI 목록
2. 영구 state key 목록
3. menu/action 목록
4. 관련 tests
5. 실제 page/tutorial code 재사용 가능 여부

제거:

- Quick Start 명칭/entry
- open/reset menu
- progress/completion UI
- completion watcher
- seen/skipped/completed persistence
- status reset logic

기존 저장값:

- migration으로 강제 삭제하지 않음
- 더 이상 read/write하지 않음
- 다른 설정 schema를 깨지 않음

**별도 commit.**

검증:

- app boot
- settings load
- 기존 사용자 settings로 boot
- Quick Create production feature 정상
- 기존 Library/Models/Workflow page 정상

---

## 4. Phase B — Content + semantic target layer

### Minimal content model

권장 개념:

```text
PageHelpContent
TutorialStep
TutorialPage
```

필드 예:

```text
PageHelpContent
- page_id
- title_key
- introduction_key
- workflow_keys
- feature_keys
- caution_keys

TutorialStep
- step_id
- title_key
- body_key
- target_id
- fallback_target_id
- view_hint
```

content에는 QWidget pointer를 저장하지 않는다.

### TargetRegistry

semantic id → resolver.

Resolver는 호출 시점의 current UI를 반환한다.

예:

```text
"studio.timeline.clip"
→ current first visible clip QRect provider
```

동적 UI rebuild를 견뎌야 한다.

### Content validation

test:

- six pages all registered
- page section complete
- all step ids unique
- all target ids known
- ko/en key complete
- no progress/completion field

**별도 commit.**

---

## 5. Phase C — Help entry / dialog

작업:

1. TitleBar action에 help button 추가
2. Help menu 추가
   - Tutorial
   - Report Problem
3. Tutorial dialog 구현
4. current page auto-select
5. page selector
6. detail section renderer
7. Page Move
8. Tutorial Start
9. responsive narrow layout
10. theme/i18n/accessibility

재사용:

- `WindowTitleBar.add_action_widget`
- `SvgIconButton`
- `FeedbackButton`
- `ScrollSafeComboBox`
- existing localization/theme

금지:

- side panel
- new navigation page
- progress header
- reset action

**별도 commit.**

---

## 6. Phase D — Stateless TutorialRunner / Overlay

구현:

- one runner
- one overlay
- previous/next/end
- Esc exit
- target resolve/fallback
- union widget target
- rect provider target
- safe scroll
- temporary view snapshot/restore
- resize tracking

Input policy:

- underlying work controls blocked
- overlay controls only
- no actual tutorial action execution

Do not add:

```text
tutorial_state.py
tutorial_progress.py
tutorial_completion_store.py
```

같은 persistence 책임.

**별도 commit.**

---

## 7. Phase E — Page target wiring

페이지별로 작은 commit을 권장한다.

### E1 Library

참조:

- `main_window.py`
- `library_row.py`
- `library_details_panel.py`
- `library_group_panel.py`

연결:

- import
- import target
- groups
- search/sort
- song list/dynamic row
- Work Song
- navigation Work Song selector
- details/stages

Quick Create는 삭제하지 않는다.

### E2 Models

참조:

- `model_workspace.py`
- `model_add_dialog.py`
- `model_detail_panel.py`
- `model_dataset_panel.py`
- `model_dataset_analysis_panel.py`
- `model_precision_benchmark_panel.py`
- `model_training_panel.py`

safe temporary section navigation + restore.

### E3 Separation

참조:

- `main_window.py`
- `separation_recipe_selector.py`
- `separation_stem_pool.py`
- results/transport

Vocal Separation unavailable 상태에서 강제 진입 금지.

### E4 Conversion

참조:

- `conversion_input_pool.py`
- `conversion_pitch_guide.py`
- `rvc_inference_controls.py`
- `conversion_result_browser.py`
- main conversion builder

advanced/quality reveal은 temporary + restore.

### E5 Studio

참조:

- `studio_editor.py`
- `studio_transport_bar.py`
- `studio_sound_pool.py`
- `studio_fx_pool.py`
- `studio_inspector.py`
- `video_preview_panel.py`

custom timeline target용 read-only rect helper 추가 가능.

절대 tutorial 전용 clip/widget를 timeline에 삽입하지 않는다.

### E6 Export

참조:

- `export_page.py`
- `audio_export_controls.py`
- `video_export_controls.py`

Audio/Video view temporary switch + restore.

---

## 8. Stable target exposure policy

현재 UI의 local variable 때문에 target을 잡기 어렵다면 우선순위:

1. 이미 존재하는 `self.*` widget 사용
2. existing widget에 semantic objectName/property 추가
3. existing widget을 `self.*` alias로 보관
4. custom paint는 read-only QRect helper

금지:

5. tutorial highlight를 위해 복제 QWidget 생성
6. 기존 layout에 invisible dummy target 삽입
7. absolute coordinate hardcoding

---

## 9. Phase F — Problem Report client

구현:

- common report dialog
- category
- description
- diagnostic context builder
- sanitizer
- attachment preview
- Report ID
- local Outbox
- network client
- success/failure UI
- pending retry

기존 `job_diagnostics`, app/runtime/hardware diagnostics를 재사용한다.

병렬 diagnostics stack을 새로 만들지 않는다.

Error UI integration은 범위가 큰 경우 우선 핵심 workflow부터:

1. Separation
2. Conversion
3. Training
4. Export
5. Update/Runtime
6. Studio async failures

**별도 commit(s).**

---

## 10. Phase G — Report endpoint

Cloudflare Worker:

- dedicated JJZ account
- Free plan
- secret
- strict schema
- 64 KiB max
- category allowlist
- Report ID
- duplicate search
- GitHub issue create

Optional backup:

- Apps Script Web App
- no Sheet/Drive
- same private JJZ-Reports repo
- no user OAuth

endpoint deployment/config를 app source와 어떻게 관리할지는 구현 직전 결정하되 GitHub token은 source에 commit하지 않는다.

---

## 11. Phase H — Integration cleanup

확인:

- old onboarding code import 0
- old progress/reset UI 0
- ignored legacy setting write 0
- Quick Create remains functional
- Help button only one
- Report dialog only one
- tutorial runner only one
- page-specific duplicate overlay class 0

dead files/tests 제거는 실제 reference search 후 수행한다.

---

## 12. Test matrix

### Tutorial state

- first run
- old settings present
- no tutorial settings
- app restart
- repeated same page tutorial
- mid-step exit
- previous/next
- resize during tutorial

### Data safety

Before/after hash or model comparison:

- Library catalog unchanged
- Library groups unchanged
- Work Song unchanged unless user explicitly navigated before tutorial
- model metadata unchanged
- Dataset unchanged
- Training unchanged
- separation jobs unchanged
- conversion takes unchanged
- Studio session unchanged
- export files unchanged

### Page data states

- no songs
- no models
- no separation output
- no conversion output
- empty Studio
- no exports
- populated variants for all above

### UI

- Korean
- English
- Light
- Dark
- minimum supported window
- large window
- 100/125/150% Windows scaling if release verification environment allows

### Reporting

- manual report
- contextual report
- no network
- Worker 5xx
- duplicate response loss case
- backup success
- both endpoints fail
- restart with Outbox

---

## 13. Packaging smoke

final build에서 확인:

1. clean install
2. first run setup
3. Library tutorial
4. Models tutorial
5. Separation tutorial
6. Conversion tutorial
7. Studio tutorial
8. Export tutorial
9. same tutorial replay
10. app restart and replay
11. problem report success
12. update path
13. normal uninstall
14. complete removal

튜토리얼은 first run에 자동으로 강제 시작하지 않는다.

---

## 14. Commit policy

큰 한 번의 implementation commit을 피한다.

권장:

1. legacy onboarding removal
2. content/target model
3. help dialog
4. runner/overlay
5. Library
6. Models
7. Separation
8. Conversion
9. Studio
10. Export
11. reporting client
12. report endpoint/integration
13. final cleanup/tests

각 commit은 독립적으로 test 가능한 범위를 유지한다.

---

## 15. Codex stop conditions

Codex는 다음 상황에서 임의 설계를 하지 말고 작업을 멈추고 차이를 보고한다.

- 실제 implementation branch의 UI가 이 mockup과 구조적으로 다름
- semantic target을 기존 UI로 연결할 수 없음
- tutorial 때문에 domain data mutation이 필요해 보임
- 새 persistent state가 필요해 보임
- Quick Create와 Quick Start 제거 범위가 충돌
- problem reporting이 사용자 OAuth permission을 요구하게 됨
- private report repo와 fallback design이 충돌
- existing diagnostics를 재사용할 수 없는 이유가 발견됨

---

## 16. Definition of done

0.3.11 completion은 다음을 모두 만족해야 한다.

- 6개 page help content 구현
- 6개 page tutorial 구현
- no persisted tutorial progress
- no Quick Start onboarding residue
- Quick Create production feature 보존
- no tutorial data mutation
- no duplicate help/report panels
- reporting one-click success path
- user account permission 추가 없음
- all tests/build/package smoke 통과
- 실제 UI를 사용자 검수 후 최종 commit

마지막 기준:

> **기능이 존재하는 것**이 아니라 사용자가 처음 보는 JJZero Audio에서 구조를 이해하고, 막혔을 때 같은 화면을 다시 안내받고, 문제가 생기면 손쉽게 신고할 수 있는 상태가 0.3.11 completion이다.
