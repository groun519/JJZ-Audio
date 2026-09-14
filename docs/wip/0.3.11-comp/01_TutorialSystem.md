# 01. Tutorial System

## Status

- **Fact:** JJZero Audio의 주요 제작 페이지는 Library, Models, Separation, Conversion, Studio, Export의 6개다.
- **Requirement:** 기존 `Quick Start` 온보딩 개념과 영구 진행 상태를 제거한다.
- **Decision:** 튜토리얼은 **페이지별, 재실행 가능, 비파괴적, 무상태(stateless)** 안내 시스템으로 구현한다.

> Library의 제작 기능 `Quick Create`는 온보딩 `Quick Start`와 별개다. 이 문서의 제거 대상이 아니다.

---

## 1. Core contract

튜토리얼 시스템은 사용자의 실제 작업을 완료시키는 퀘스트 시스템이 아니다.

다음 기능을 만들지 않는다.

- 전역 튜토리얼 진행률
- 페이지별 완료 여부
- 완료 체크
- 처음 봤는지 여부
- 스킵 기록
- 튜토리얼 초기화
- 작업 결과 감시
- "이 버튼을 실제로 눌러야 다음 단계" 규칙
- 샘플 프로젝트/샘플 곡 자동 생성
- 튜토리얼 전용 작업 데이터

사용자가 도움말에서 원하는 페이지를 선택하고 언제든 처음부터 다시 시작한다.

---

## 2. Runtime state

튜토리얼 실행 중 필요한 상태만 메모리에 둔다.

예상 최소 상태:

```text
active_page_id
active_step_index
origin_page_id
temporary_view_state
resolved_target
```

앱 설정, 프로젝트, Library, Model Workspace 또는 별도 JSON에 진행 상태를 저장하지 않는다.

앱을 종료하면 실행 중 상태는 사라진다.

---

## 3. Components

필요 책임은 네 개로 제한한다.

### 3.1 TutorialContent

페이지 설명과 단계 정의.

보유 정보:

- page id
- page title localization key
- page introduction
- basic workflow
- major features
- cautions
- ordered tutorial steps

도메인 작업을 실행하지 않는다.

### 3.2 TutorialTargetRegistry

semantic target id를 현재 UI의 실제 대상에 연결한다.

예:

```text
library.import.files
conversion.pitch
studio.timeline
export.audio.presets
```

콘텐츠가 Python 멤버명에 직접 결합되지 않도록 한다.

Target 종류:

- QWidget target
- 여러 QWidget을 감싸는 union target
- 동적으로 생성된 row/card target
- custom-painted UI를 위한 read-only QRect provider

### 3.3 TutorialRunner

- 시작
- 이전
- 다음
- 종료
- 페이지 이동
- target resolve
- temporary view state 적용/복구

만 담당한다.

### 3.4 TutorialOverlay

실제 화면 위에 다음만 표시한다.

- dim layer
- highlight cutout/border
- 설명 callout
- `이전`
- `다음`
- `종료`

상시 패널이나 진행률 UI를 만들지 않는다.

---

## 4. Tutorial input safety

**Requirement:** 튜토리얼은 실제 데이터에 영향을 주지 않는다.

이를 보장하기 위해 실행 중 Overlay가 기본적으로 하위 작업 UI의 pointer input을 가로챈다.

허용 입력:

- 이전
- 다음
- 종료
- Esc로 종료
- callout 내부 스크롤이 필요할 경우 해당 스크롤

금지 입력:

- Import 실행
- Delete 실행
- Convert/Separate/Train/Export 실행
- Timeline clip 실제 이동/trim/split
- 모델/설정 값 변경
- 실제 파일 선택
- 실제 Google/Drive 작업

즉 하이라이트는 **설명용**이지 실제 조작 강제가 아니다.

---

## 5. Safe temporary UI changes

튜토리얼이 대상을 보여주기 위해 아래 UI 상태는 임시로 바꿀 수 있다.

- 선택한 제작 페이지로 이동
- scroll area 위치 이동
- collapsed help-relevant section 열기
- Model Workspace의 Overview/Dataset/Analysis/Evaluation/Training section 이동
- Conversion의 Advanced/Quality 상세 영역 열기

조건:

1. 도메인 데이터가 바뀌지 않아야 한다.
2. 실행 전 상태를 기록한다.
3. `종료` 또는 마지막 단계에서 원래 상태로 복구한다.
4. 복구 실패가 작업 데이터 손실로 이어져서는 안 된다.

사용자 설정으로 저장되는 splitter 폭, snapping preference 같은 값은 튜토리얼이 바꾸지 않는다.

---

## 6. Target resolution

각 단계는 semantic target id를 가진다.

예:

```text
step.target = "studio.transport.snap"
step.fallback_target = "studio.transport"
```

Target resolve 순서:

1. primary target 존재 확인
2. visible/enabled 여부 확인
3. 필요하면 safe temporary view change
4. 다시 target 확인
5. 그래도 없으면 fallback target
6. fallback도 없으면 페이지 root

대상 부재는 튜토리얼 오류가 아니다.

예:

> 현재 타임라인에 클립이 없어 클립 조작 영역을 직접 표시할 수 없습니다. 클립이 있을 때 이 영역에서 이동과 자르기를 사용할 수 있습니다.

---

## 7. Dynamic targets

Library row, Model row, Export row처럼 데이터에 따라 생성되는 UI는 "첫 번째 항목"을 강제로 요구하지 않는다.

Resolver 규칙:

```text
visible matching item exists
→ 실제 item target

no matching item
→ owning list/container target + empty-state explanation
```

Studio Timeline은 custom-painted widget이므로 clip/track을 child QWidget처럼 찾지 않는다.

필요하면 `StudioTimelineView`에 read-only geometry helper를 추가한다.

예:

```text
tutorial_first_visible_clip_rect()
tutorial_track_area_rect()
tutorial_ruler_rect()
```

이 helper는 hit test 결과나 기존 geometry 계산을 재사용하며 편집 상태를 변경하지 않는다.

좌표 상수를 튜토리얼 코드에 하드코딩하지 않는다.

---

## 8. Step transition

### Start

1. 선택된 page id 확인
2. 필요한 경우 해당 page로 이동
3. Help dialog 닫기
4. Overlay 생성
5. first step target resolve
6. 화면에 보이도록 scroll
7. callout 표시

### Next

1. 현재 step의 temporary view cleanup
2. 다음 step 준비
3. target resolve
4. 필요한 safe view state 적용
5. highlight 갱신

### Previous

Next와 동일하되 이전 step 정의를 다시 resolve한다.

### End

1. Overlay 제거
2. temporary view state 복구
3. 입력 focus 복구
4. 어떤 완료 상태도 기록하지 않음

---

## 9. Callout placement

Callout은 target을 가리지 않는 방향을 우선한다.

우선순위:

1. target 오른쪽
2. target 왼쪽
3. target 아래
4. target 위
5. 화면 중앙 compact callout

창 resize마다 재계산한다.

화면 밖으로 나가는 고정 좌표를 사용하지 않는다.

---

## 10. Scroll behavior

Target이 scroll area 안에 있으면 튜토리얼이 해당 target을 보이게 스크롤할 수 있다.

단:

- scroll 위치만 임시 변경
- 원래 scroll 위치 저장
- 종료 시 복구
- animated scroll은 선택 사항
- 숨겨진 데이터 row를 생성하지 않음

---

## 11. Localization

콘텐츠를 한글/영문 별도 Python 구조로 복제하지 않는다.

예상 형식:

```text
tutorial.library.intro
tutorial.library.workflow.1
tutorial.library.step.import.title
tutorial.library.step.import.body
```

기존 `tr()` 계층과 같은 locale source를 사용한다.

검사 항목:

- 모든 page에 ko/en title 존재
- 모든 section 존재
- 모든 step title/body 존재
- semantic target id 존재
- duplicate step id 없음

---

## 12. Theme and accessibility

- Light/Dark 모두 highlight contrast 확보
- highlight 의미를 색상 하나로만 전달하지 않음
- border + dim + callout을 함께 사용
- 설명 제목/본문은 screen reader에서 읽을 수 있는 accessible text 설정
- Overlay 활성 중 keyboard focus는 tutorial controls에 유지
- Esc는 항상 종료
- 창 크기가 바뀌어도 target geometry 재계산

---

## 13. Explicit non-goals

- 첫 실행 때 자동 튜토리얼 강제
- "6개 중 3개 완료" UI
- badge/checkmark
- achievement
- tutorial reset
- 실제 작업 자동 실행
- tutorial용 fake song/model
- tutorial 전용 side panel
- 페이지마다 별도 runner/overlay class

---

## 14. Tests

최소 테스트:

- 어떤 페이지든 시작 가능
- 같은 페이지 반복 실행 가능
- 중간 종료 후 즉시 재실행 가능
- 앱 재시작 후 이전 튜토리얼 상태에 의존하지 않음
- target 없음 → fallback
- target hidden → safe view reveal 또는 fallback
- target widget 삭제/refresh → crash 없음
- resize 중 overlay geometry 갱신
- Light/Dark
- Korean/English
- underlying button 클릭 차단
- underlying drag/drop 차단
- temporary view state 복구
- Studio custom rect target fallback

---

## 15. Acceptance

완료 기준:

> 사용자가 어느 상태에서든 도움말을 열어 원하는 페이지 튜토리얼을 실행할 수 있고, 튜토리얼을 몇 번 실행하거나 어디서 종료하더라도 Library/Model/Project/Output 데이터가 변하지 않는다.
