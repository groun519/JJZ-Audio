# JJZero Audio 0.3.11 Completion Mockup

> Workspace: `docs/wip/0.3.11-comp/`  
> Mockup branch: `mockup/jjz-ui-plan`  
> Implementation reference: current `main`  
> Purpose: 0.3.11을 최종 사용자에게 배포 가능한 수준으로 완성하기 위한 상세 설계.

## 1. Goal

이번 목업의 핵심은 기능 추가 자체가 아니라 **기존 온보딩 시도에서 과도하게 단순화되거나 불필요하게 분리된 UI를 다시 설계하는 것**이다.

최종 방향:

- 온보딩의 `빠른 시작(Quick Start)` 개념 제거
- 페이지별 튜토리얼
- 전역 진행률 없음
- 완료 상태 없음
- 체크 표시 없음
- 튜토리얼 초기화 없음
- 사용자의 실제 작업 결과를 감시하지 않음
- 실제 데이터에 영향을 주지 않음
- 사용자가 원하는 페이지 튜토리얼을 언제든 다시 실행 가능

> **중요:** Library의 실제 제작 기능인 `Quick Create`는 `Quick Start` 온보딩과 별개다. 별도 제품 결정이 없는 한 제거 대상으로 취급하지 않는다.

## 2. Help flow

```text
상단 도움말
→ 튜토리얼
→ 현재 페이지 자동 선택
→ 페이지 설명
→ [튜토리얼 시작]
→ 실제 화면 Highlight
→ 이전 / 다음 / 종료
```

튜토리얼 실행 상태는 현재 실행 중인 임시 UI 상태일 뿐 영구 저장하지 않는다.

## 3. Help panel layout

넓은 창:

```text
┌──────────────────────────────────────────────────────────────┐
│ Library                                                [X]   │
├───────────────┬──────────────────────────────────────────────┤
│ Library       │ 페이지 소개                                 │
│ Models        │                                              │
│ Separation    │ 기본 작업 순서                              │
│ Conversion    │                                              │
│ Studio        │ 주요 기능                                   │
│ Export        │                                              │
│               │ 주의할 점                                   │
│               │                                              │
│               │          [페이지로 이동] [튜토리얼 시작]    │
└───────────────┴──────────────────────────────────────────────┘
```

좁은 창에서는 왼쪽 페이지 목록을 상단 선택 메뉴로 바꾼다.

현재 페이지가 선택된 상태라면 `페이지로 이동`은 숨긴다.

## 4. Page document split

각 페이지는 별도 목업 문서로 작성한다.

- `03_LibraryTutorial.md`
- `04_ModelsTutorial.md`
- `05_SeparationTutorial.md`
- `06_ConversionTutorial.md`
- `07_StudioTutorial.md`
- `08_ExportTutorial.md`

각 문서는 실제 현재 UI를 기준으로 다음을 확정한다.

### Help content

- 페이지 소개
- 기본 작업 순서
- 주요 기능
- 주의할 점

### Interactive tutorial

각 단계마다:

- Step ID
- 설명
- semantic Highlight Target ID
- 현재 실제 QWidget / 컨테이너 매핑
- 대상이 숨김/부재/비활성일 때 fallback
- 튜토리얼이 임시로 바꿔도 되는 UI 상태
- 실제 데이터 변경 금지 여부
- 이전 / 다음 동작

## 5. Current page scope

### Library

- YouTube 가져오기
- 파일 가져오기
- 가져올 그룹 지정
- 그룹 패널
- 검색
- 정렬
- 곡 목록
- 작업곡 지정
- 곡 상세
- 파일/자산 관리
- Quick Create (실제 제작 기능, 온보딩 Quick Start와 별개)

### Models

Model Library와 개별 Model Workspace를 구분한다.

Model Library:

- 요약
- Add Model
- Refresh
- 검색
- 필터
- 모델 목록

Model Workspace:

- Overview
- Dataset
- Analysis
- Evaluation
- Training
- 모델 사용
- 파일 위치
- Drive 공유

### Separation

- 공통 작업곡
- Separation Recipe
- 실행
- Stem Pool
- 결과 비교/선택
- 결과 Transport

### Conversion

- Conversion Input Pool
- RVC Model
- Pitch
- Pitch Guide
- Advanced Settings
- Index
- Device
- Conversion Quality
- Convert
- Result Browser
- Vocal Results
- Transport

### Studio

- Sound Pool
- FX Pool
- Media Preview
- Transport
- Timeline
- Track
- Clip 이동
- Trim
- Split
- Snapping
- Shift 다중 선택
- Marquee 다중 선택
- Inspector
- Project History

### Export

- Export Song
- Audio / Video 모드
- Preset / 세부 Export 설정
- 실행
- Exports 결과
- 미리듣기
- 이름 변경
- 삭제
- 폴더 열기
- Drive 공유

## 6. Design constraints

이번 재설계에서 다음은 금지한다.

- 튜토리얼 전용 상시 페이지 추가
- 튜토리얼 진행률 패널
- 완료율
- 체크리스트형 상태 UI
- 사용자의 실제 작업 완료 여부 추적
- 튜토리얼을 위한 샘플 데이터 자동 생성
- 튜토리얼 전용 데이터 변경
- Help 기능 때문에 기존 페이지 구조를 크게 재배치
- 페이지마다 별도 신고 패널 생성
- 튜토리얼 타깃을 맞추기 위한 중복 UI 생성
- 좌표를 하드코딩한 Highlight

기본 원칙:

> 기존 실제 작업 UI 위에 설명과 Highlight만 얹는다.

## 7. Planned documents

1. `01_TutorialSystem.md`
2. `02_HelpPanel.md`
3. `03_LibraryTutorial.md`
4. `04_ModelsTutorial.md`
5. `05_SeparationTutorial.md`
6. `06_ConversionTutorial.md`
7. `07_StudioTutorial.md`
8. `08_ExportTutorial.md`
9. `09_ProblemReporting.md`
10. `10_ImplementationPlan.md`

## 8. Completion gate

0.3.11-comp 목업 완료 조건:

- 모든 페이지 도움말 내용 확정
- 모든 페이지 튜토리얼 단계 확정
- semantic Highlight Target과 실제 UI 매핑 확정
- 대상 부재 fallback 확정
- 기존 Quick Start/온보딩 제거 범위 확정
- 문제 신고 UX 확정
- 구현 순서 확정
- Codex가 추가 UX 결정을 하지 않아도 구현 가능한 수준
