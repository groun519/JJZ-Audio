# 02. Help / Tutorial Browser

## Status

- **Requirement:** 상단 도움말 버튼 → `튜토리얼` → 현재 페이지 설명 자동 선택.
- **Decision:** 도움말은 새 제작 페이지나 상시 side panel이 아니라 **하나의 공통 dialog**로 제공한다.
- **Decision:** 문제 신고는 같은 상단 도움말 메뉴의 별도 항목으로 진입한다.

---

## 1. Title bar entry

현재 TitleBar action 영역은 Processing Queue, Google Account, Language, Theme가 배치된다.

도움말 버튼을 여기에 하나 추가한다.

권장 순서:

```text
Processing Queue
Help (?)
Google Account
Language
Theme
Window Controls
```

Help 버튼은 `SvgIconButton` 계열의 compact icon button을 재사용한다.

새 navigation row나 새 dock를 만들지 않는다.

---

## 2. Help menu

`?` 클릭:

```text
┌─────────────────────┐
│ 튜토리얼            │
│ 문제 신고           │
└─────────────────────┘
```

초기 0.3.11 범위에서는 이 두 항목만 둔다.

불필요하게 FAQ/Home/Progress/Reset 메뉴를 추가하지 않는다.

---

## 3. Tutorial dialog

### Wide layout

```text
┌────────────────────────────────────────────────────────────────────┐
│ 스튜디오                                                     [X]  │
├────────────────┬───────────────────────────────────────────────────┤
│ 라이브러리     │ 페이지 소개                                      │
│ 모델           │ ...                                               │
│ 분리           │                                                   │
│ 변환           │ 기본 작업 순서                                   │
│ 스튜디오       │ 1. ...                                            │
│ 내보내기       │ 2. ...                                            │
│                │                                                   │
│                │ 주요 기능                                        │
│                │ ...                                               │
│                │                                                   │
│                │ 주의할 점                                        │
│                │ ...                                               │
├────────────────┴───────────────────────────────────────────────────┤
│                                [페이지로 이동] [튜토리얼 시작]     │
└────────────────────────────────────────────────────────────────────┘
```

### Header

표시:

- 선택된 page name
- close

표시하지 않음:

- 진행률
- 완료율
- 완료 badge
- reset
- last viewed
- check mark

### Left page list

순서 고정:

1. Library
2. Models
3. Separation
4. Conversion
5. Studio
6. Export

선택은 Help dialog 내부 문서만 변경한다.

목록 선택 자체로 실제 앱 페이지를 바꾸지 않는다.

### Detail area

항상 같은 네 section 순서:

1. 페이지 소개
2. 기본 작업 순서
3. 주요 기능
4. 주의할 점

detail area는 scroll 가능하다.

### Footer

버튼은 두 개만 허용한다.

- `페이지로 이동`
- `튜토리얼 시작`

현재 앱 page와 선택된 help page가 같으면 `페이지로 이동`을 숨긴다.

---

## 4. Narrow layout

Dialog의 usable width가 충분하지 않으면 왼쪽 page list를 제거하고 상단 combo로 바꾼다.

예:

```text
┌──────────────────────────────┐
│ 스튜디오                 [X] │
├──────────────────────────────┤
│ [ 스튜디오             ▼ ]  │
│                              │
│ 페이지 소개                  │
│ ...                          │
│                              │
│ 기본 작업 순서               │
│ ...                          │
│                              │
├──────────────────────────────┤
│ [페이지로 이동] [튜토리얼]  │
└──────────────────────────────┘
```

기준은 screen size가 아니라 **dialog content width**로 판단한다.

권장 전환 기준: 약 760 px 이하.

---

## 5. Open behavior

상단 Help → Tutorial을 선택하면:

1. 현재 `main_stack` page id를 읽음
2. 6개 제작 page 중 하나면 해당 page 자동 선택
3. 다른 window/management/settings 문맥이라면 마지막 제작 page 또는 Library를 선택
4. detail scroll은 top으로 이동
5. dialog 표시

사용자가 마지막으로 본 help page를 영구 저장하지 않는다.

---

## 6. Page navigation

### 페이지로 이동

1. 선택된 page로 앱 navigation 수행
2. dialog 닫기
3. tutorial은 시작하지 않음

### 튜토리얼 시작

1. 선택된 page로 앱 navigation 수행
2. dialog 닫기
3. 해당 page tutorial step 0 시작

두 버튼의 의미를 합치지 않는다.

---

## 7. Dialog type

권장:

- centered application dialog
- application window에 owner 지정
- 별도 taskbar entry 없음
- 항상 떠 있는 dock/side panel 아님

튜토리얼 시작 후 dialog는 반드시 닫혀 화면을 가리지 않는다.

---

## 8. Existing UI reuse

재사용:

- WindowTitleBar.action_widget
- SvgIconButton
- FeedbackButton
- ScrollSafeComboBox
- existing theme/localization helpers

새로 만들지 않음:

- 별도 Help navigation page
- persistent Help drawer
- Help progress card
- completion summary
- tutorial status service

---

## 9. Problem report entry

`문제 신고`는 Tutorial dialog footer에 넣지 않는다.

이유:

- 사용자 요구상 footer는 `페이지로 이동`, `튜토리얼 시작` 두 버튼만 유지
- report는 tutorial의 일부가 아니라 support action
- Help menu에서 바로 접근 가능

오류 dialog의 `문제 신고` 버튼도 같은 공통 Problem Report dialog를 연다.

---

## 10. Content rendering

섹션 제목은 고정 UI이고 본문만 locale content에서 공급한다.

```text
PageHelpContent
- introduction
- workflow[]
- features[]
- cautions[]
```

Markdown renderer까지 추가하지 않는다.

필요 UI:

- QLabel word wrap
- numbered workflow rows
- bullet feature/caution rows

복잡한 rich text dependency를 추가하지 않는다.

---

## 11. Accessibility

- Help button accessible name: `Help`
- menu item keyboard navigation
- page list/combo keyboard navigation
- dialog close: Esc
- focus order: page selector → detail → page move → tutorial start → close
- text selectable 여부는 필요 시 허용하되 링크 없는 본문은 일반 label로 유지

---

## 12. Tests

- Library에서 열면 Library 자동 선택
- Studio에서 열면 Studio 자동 선택
- 다른 page 선택 시 앱은 즉시 이동하지 않음
- 현재 page면 Page Move hidden
- 다른 page면 Page Move visible
- Page Move 후 tutorial 미실행
- Tutorial Start 후 dialog closed + overlay starts
- narrow/wide layout 전환
- Korean/English
- Light/Dark
- progress/completion/reset UI가 존재하지 않음

---

## 13. Acceptance

> 도움말은 사용자를 새로운 작업공간으로 보내는 기능이 아니라 현재 JJZero Audio의 실제 작업공간을 설명하고 그 위에 튜토리얼을 시작하는 얇은 진입점이어야 한다.
