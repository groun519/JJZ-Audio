# 09. Problem Reporting

## Status

- **Requirement:** 사용자가 신고 전송 때문에 GitHub 계정이나 추가 Google 권한을 요구받지 않는다.
- **Requirement:** 신고 화면에서 최종 전송은 `보내기` 한 번으로 끝나야 한다.
- **Requirement:** 개발자는 최종적으로 GitHub Issues 한 곳만 확인한다.
- **Requirement:** 운영 비용은 0원 경로를 기본으로 한다.
- **Decision:** Primary는 JJZ 전용 Cloudflare Workers Free endpoint를 사용한다.
- **Decision:** 앱에는 GitHub write token을 포함하지 않는다.

---

## 1. Entry points

### Global

상단 Help menu:

```text
튜토리얼
문제 신고
```

### Contextual

실제 작업 오류 dialog/toast에서 가능한 경우:

```text
다시 시도
자세히 보기
문제 신고
```

Contextual 진입은 현재 page, operation, task/job id, error 정보를 미리 채운다.

---

## 2. Single common dialog

페이지별 신고 panel을 만들지 않는다.

하나의 `ProblemReportDialog`만 사용한다.

```text
┌──────────────────────────────────────────────────────┐
│ 문제 신고                                      [X]  │
├──────────────────────────────────────────────────────┤
│ 문제 유형                                            │
│ [ RVC 변환                                     ▼ ]  │
│                                                      │
│ 문제 설명                                            │
│ ┌──────────────────────────────────────────────────┐ │
│ │ 어떤 상황에서 문제가 발생했는지 적어주세요.     │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ 자동 첨부                                            │
│ • JJZero Audio / Runtime version                    │
│ • 현재 페이지 / 작업 / 오류                         │
│ • Windows / CPU / GPU / active backend              │
│ • 정제된 관련 로그                                  │
│                                                      │
│ [첨부 내용 보기]                                     │
│                                                      │
│ 원본 음원과 로그인 토큰은 전송하지 않습니다.        │
├──────────────────────────────────────────────────────┤
│                                      [취소] [보내기] │
└──────────────────────────────────────────────────────┘
```

---

## 3. Category

초기 allowlist:

- 앱이 멈춤 / 종료됨
- 기능이 작동하지 않음
- Library
- Models / Model Import
- RVC Training
- Separation
- RVC Conversion
- Studio
- Export
- 설치 / 업데이트
- Runtime / GPU
- Google Drive
- UI / 표시
- 성능
- 기타

Context가 있으면 자동 선택하되 사용자가 바꿀 수 있다.

---

## 4. Automatic diagnostic payload

가능한 경우 자동 수집:

- report schema version
- Report ID
- JJZero Audio version
- Runtime version/profile
- Windows version
- CPU
- GPU
- selected compute backend
- current page
- current sub-workspace
- operation kind
- task/job id
- error class/code
- user-safe error message
- traceback summary
- recent related job diagnostics
- storage schema version
- locale
- theme

자동 첨부하지 않음:

- 원본 음원
- video/image
- RVC model file
- project archive
- 대용량 전체 log archive

---

## 5. Privacy sanitizer

클라이언트가 server 전송 전에 정제한다.

반드시 제거/마스킹:

- OAuth access token
- OAuth refresh token
- Google credential
- GitHub token
- Authorization header
- cookies
- Windows user name
- Google email/account id
- 임의 secret/key
- 원본 media 내용

경로:

```text
C:\Users\Alice\Music\MySong.wav
→ <USER_HOME>\Music\<MEDIA_FILE>
```

model/media title이 개인 파일명일 수 있으면 일반화한다.

사용자는 `첨부 내용 보기`에서 실제 최종 JSON/읽기 쉬운 text view를 확인할 수 있다.

---

## 6. Report ID

클라이언트가 Send 직전에 생성한다.

예:

```text
JR-20260914-7F3A91C2
```

특성:

- 날짜 + 충분한 random component
- 같은 Outbox item과 모든 retry에서 동일 ID
- GitHub issue body/title에 포함
- 사용자가 접수 후 확인 가능

---

## 7. Primary transport

```text
JJZero Audio
  ↓ HTTPS POST
JJZ dedicated Cloudflare Worker
  ↓ GitHub REST API
JJZ-Reports Issues
```

Cloudflare account는 JJZ 전용으로 분리한다.

Worker 역할만 가진다.

- request validation
- payload size limit
- rate control
- category allowlist
- Report ID validation
- GitHub token 사용
- duplicate check
- GitHub Issue create
- normalized success/error response

DB 역할을 추가하지 않는다.

---

## 8. GitHub repository

권장:

```text
groun519/JJZ-Reports
```

Primary/backup endpoint 모두 같은 repository의 Issues만 생성한다.

개발자는 이 Issues inbox만 확인한다.

### Privacy recommendation

자동 diagnostic가 포함되므로 repository는 **Private**를 우선한다.

이 경우 일반 사용자의 "GitHub에서 직접 issue 생성"은 fallback으로 사용할 수 없다.

따라서 private repo를 쓸 경우 manual GitHub fallback을 설계에 넣지 않는다.

---

## 9. GitHub authentication

Fine-grained credential을 server side에만 둔다.

최소 권한:

- 지정 report repository
- Issues write에 필요한 범위만

저장:

- Cloudflare Worker Secret
- backup endpoint를 사용할 경우 해당 server-side secret store

JJZero Audio executable/config에는 write credential을 포함하지 않는다.

---

## 10. Local Outbox

Send를 누르면 **네트워크 요청보다 먼저** sanitized payload를 로컬 Outbox에 atomic write한다.

예:

```text
%LOCALAPPDATA%\JJZero Audio\reports\outbox\JR-....json
```

성공 응답을 받은 뒤에만 삭제한다.

목적:

- 앱 종료
- timeout
- server 5xx
- response loss
- network disconnect

상황에서 신고 내용을 잃지 않게 한다.

---

## 11. One-click send flow

```text
[보내기]
 ↓
validate local form
 ↓
sanitize
 ↓
write Outbox
 ↓
Primary Worker
 ↓
GitHub Issue success
 ↓
delete Outbox
 ↓
"신고가 접수되었습니다"
```

사용자가 전송 과정에서 별도 login/브라우저/메일 Send를 누르지 않는다.

---

## 12. Backup transport

Primary endpoint 자체 장애에 대비해 **선택적으로** Apps Script Web App backup을 둔다.

```text
Cloudflare Worker 실패
 ↓
제한된 retry
 ↓
Apps Script Web App
 ↓
같은 JJZ-Reports GitHub Issues
```

조건:

- Apps Script는 owner account로 실행
- 사용자 Google login/permission 불필요
- Google Sheet/Drive를 report store로 사용하지 않음
- GitHub token은 Script Properties 같은 server-side store
- 사용자 quota를 소비시키는 구조로 만들지 않음

이 backup은 Cloudflare가 정상일 때 호출하지 않는다.

---

## 13. Duplicate handling

Primary가 GitHub Issue를 만들었지만 response가 유실된 뒤 backup으로 넘어갈 수 있다.

따라서 두 endpoint는 create 전에 Report ID로 기존 issue 존재 여부를 확인한다.

공통 idempotency key:

```text
Report ID
```

GitHub를 공통 source of truth로 사용해 가능한 범위에서 duplicate create를 막는다.

완전한 atomic distributed transaction까지 만들지는 않는다.

중복이 드물게 생겨도 같은 Report ID로 식별 가능해야 한다.

---

## 14. Failure UX

Primary + backup 모두 실패하면:

```text
현재 신고를 전송하지 못했습니다.

신고 내용은 이 PC에 저장되어 있습니다.

[다시 시도]
[리포트 복사]
[닫기]
```

정상 경로와 달리 여기서는 fallback controls가 나타난다.

사용자가 앱을 다시 실행하면 pending Outbox를 감지해 다시 전송할 수 있다.

단, 사용자 동의 없이 background에서 무한 재시도하지 않는다.

---

## 15. Physical limitation

인터넷 자체가 없고 Primary/Backup endpoint가 모두 접근 불가능하며 사용자가 앱을 다시 실행하지 않는 상황에서는 원격 전달을 보장할 수 없다.

이 경우 가능한 최선은:

- local Outbox 보존
- 같은 session retry
- backup endpoint
- report copy 제공

"어떤 상황에서도 100% 서버에 도착"한다고 문서에서 주장하지 않는다.

---

## 16. Complete Removal interaction

Pending Outbox가 있는 상태에서 Complete Removal을 수행하면 local report도 삭제될 수 있다.

앱 내부 Complete Removal 진입 전에 pending report가 있으면:

```text
아직 전송되지 않은 문제 신고가 1개 있습니다.
Complete Removal을 계속하면 이 PC의 미전송 신고도 삭제됩니다.

[신고 다시 보내기]
[리포트 복사]
[계속 제거]
```

같은 보호 UX를 검토한다.

Normal uninstall 보존 정책과 충돌하지 않도록 0.3.11 distribution plan과 함께 확인한다.

---

## 17. Worker validation

최소:

- POST only
- HTTPS only
- content type allowlist
- schema version
- maximum payload size
- maximum field lengths
- category allowlist
- Report ID regex
- unknown large nested object reject
- user supplied GitHub labels/repo/assignee 금지
- markdown body escape/normalization
- token/error detail client에 그대로 반환 금지

권장 initial payload limit: **64 KiB 이하**.

큰 로그는 보내지 않는다.

---

## 18. Abuse model

Desktop client 안의 hardcoded secret은 진짜 인증 수단으로 보지 않는다.

공개 endpoint임을 전제로:

- Cloudflare edge protection
- request size 제한
- rate control
- strict schema
- content length limit
- Report ID format
- server-side GitHub token scope 최소화

를 사용한다.

복잡한 device fingerprint나 사용자 추적 시스템은 초기 범위에서 만들지 않는다.

---

## 19. Issue format

예:

```text
[RVC Conversion] Conversion failed

Report ID: JR-20260914-7F3A91C2
App: 0.3.11
Runtime: ...
OS: Windows ...
GPU: ...
Page: Conversion
Operation: RVC Conversion

User description:
...

Error:
...

Diagnostics:
...
```

Labels는 server가 category mapping으로 정한다.

사용자가 임의 label/assignee를 지정하지 않는다.

---

## 20. Tests

Client:

- report dialog manual open
- error-context open
- category prefill
- sanitize path/email/token
- attachment preview
- Outbox atomic write
- success delete
- timeout preserve
- restart pending detection
- Copy Report

Server:

- valid issue create
- invalid method
- oversized payload
- malformed ID
- unknown category
- duplicate Report ID
- GitHub 401/403/429/5xx normalization
- secret not leaked

Integration:

- Cloudflare success
- Cloudflare failure → backup success
- both failure → Outbox
- same report retry creates at most one logical report
- user GitHub/Google login 없이 정상 완료

---

## 21. Acceptance

> 정상 사용자는 문제 설명을 적고 `보내기` 한 번만 누르면 GitHub Issue까지 접수되고, 사용자 계정/권한/비용을 소비하지 않으며, 실패해도 report가 조용히 사라지지 않아야 한다.
