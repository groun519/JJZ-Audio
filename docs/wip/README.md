# JJZero Audio WIP Design Mockups

> Branch: `mockup/jjz-ui-plan`  
> Storage model: design-only workspace  
> Implementation reference: current `main` or the actual implementation branch named by each topic  
> Purpose: JJZero Audio의 구현 전 설계/목업 문서를 한 브랜치에서 주제별로 관리한다.

## 1. Branch policy

이 브랜치는 기능별 목업 브랜치를 계속 만드는 대신 모든 WIP 설계를 한 곳에서 관리한다.

원칙:

1. 새로운 목업 주제마다 별도 Git branch를 만들지 않는다.
2. 주제별로 `docs/wip/<topic>/` 폴더를 추가한다.
3. 실제 구현 코드는 이 브랜치의 문서가 아니라 현재 `main` 또는 해당 구현 브랜치를 직접 읽어 검증한다.
4. 목업 브랜치는 설계 문서의 공유 작업공간이며 구현 브랜치의 대체물이 아니다.
5. 목업에서 확정된 결정만 실제 코드/문서로 의도적으로 이관한다.
6. 구현 결과가 목업과 다르면 구현을 정답으로 간주하지 않고 차이를 먼저 검토한다.
7. 기능 목록만 나열하지 않고 실제 화면 구조, 상호작용, 상태, 예외, 성공 조건까지 작성한다.
8. Codex가 UI 구조를 임의로 새로 만들지 않도록 기존 컴포넌트 재사용 위치와 새로 만들면 안 되는 UI를 명시한다.

## 2. Current workspaces

### `0.3.11-comp/`

0.3.11 완성 단계용 목업.

범위:

- 기존 Quick Start / 온보딩 구조 정리
- 페이지별 도움말
- 페이지별 실행형 튜토리얼
- 실제 UI Highlight Target 정의
- 대상 부재 / 비활성 상태 fallback
- 문제 신고 UX
- 0.3.11 최종 통합 검증

## 3. Folder rule

권장 구조:

```text
docs/
└─ wip/
   ├─ README.md
   └─ 0.3.11-comp/
      ├─ README.md
      ├─ 01_TutorialSystem.md
      ├─ 02_HelpPanel.md
      ├─ 03_LibraryTutorial.md
      ├─ 04_ModelsTutorial.md
      ├─ 05_SeparationTutorial.md
      ├─ 06_ConversionTutorial.md
      ├─ 07_StudioTutorial.md
      ├─ 08_ExportTutorial.md
      ├─ 09_ProblemReporting.md
      └─ 10_ImplementationPlan.md
```

문서 수와 파일명은 실제 범위에 맞게 조정할 수 있다.

## 4. Status labels

필요한 경우 다음 상태를 사용한다.

- **Fact**: 현재 코드/UI에서 직접 확인된 사실
- **Requirement**: 반드시 만족해야 하는 요구
- **Decision**: 현재 채택된 설계
- **Candidate**: 유력하지만 아직 확정되지 않은 안
- **Deferred**: 이번 범위에서 구현하지 않는 항목
- **Open Question**: 의도적으로 미결정 상태인 항목

## 5. Page mockup rule

페이지별 문서는 최소 다음을 포함한다.

1. 현재 UI 사실
2. 페이지 역할
3. 도움말 패널 상세 내용
4. 실행형 튜토리얼 단계
5. 각 단계의 실제 Highlight Target
6. 대상이 없거나 비활성일 때 fallback
7. 데이터 변경 여부
8. 좁은 창 / 테마 / 접근성 조건
9. 제거할 기존 온보딩 요소
10. 구현 완료 조건

튜토리얼은 사용자의 실제 작업을 검사하는 퀘스트 시스템이 아니다.

- 전역 진행률 없음
- 완료 상태 없음
- 체크 표시 없음
- 초기화 없음
- 작업 결과 감시 없음
- 실제 데이터 변경 없음
- 언제든 재실행 가능

## 6. Implementation handoff

목업이 구현 가능한 수준까지 정리되면 해당 주제 문서에 다음을 남긴다.

- 구현 순서
- 재사용할 기존 UI/서비스
- 새로 추가할 최소 책임
- 제거할 레거시
- 금지할 불필요한 새 패널/상태 시스템
- 테스트 방법
- 성공 조건
- 보류 범위

Codex는 문서의 `Decision`을 임의로 변경하지 않고, 실제 코드와 충돌하는 경우 차이를 먼저 보고한다.
