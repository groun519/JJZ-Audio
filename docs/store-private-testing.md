# Microsoft Store 비공개 테스트 배포

JJZero Audio의 무료 신뢰 배포 경로는 Microsoft Store의 `Private audience`를 사용한다. Store에 제출된 MSIX는 Microsoft가 서명하므로 테스터에게 게시자 불명 경고가 표시되지 않고, 업데이트도 Store가 담당한다.

## 현재 구현 범위

- Store용 MSIX는 앱 본체만 포함한다. 선택형 AI 런타임은 포함하지 않으며 첫 실행 설정에서 별도 설치한다.
- Store 패키지는 `distribution-channel.json`에 `store` 채널을 기록한다.
- Store 채널에서는 GitHub 기반 자체 업데이트 확인을 실행하지 않는다.
- 직접 배포판은 기존 `direct` 채널과 자체 업데이트 흐름을 그대로 사용한다.
- 앱 버전 `0.2.8`은 Store 패키지 버전 `1.2.8.0`으로 변환한다. Store 규칙에 맞게 첫 번째 버전 값은 0이 아니며 네 번째 값은 0이다.

## 사전 준비

Partner Center에서 앱 이름을 예약한 뒤 제품의 패키지 ID 페이지에서 다음 값을 확인한다.

- `Package/Identity/Name`
- `Package/Identity/Publisher`
- 사용자에게 표시할 게시자 이름

임의의 개발용 값으로 만든 MSIX는 구조 검사에만 사용할 수 있으며 Store에 제출할 수 없다.

## 패키지 생성

프로젝트 루트에서 다음 명령을 실행한다.

```powershell
.\scripts\build_msix.ps1 `
  -IdentityName "<Package/Identity/Name>" `
  -Publisher "<Package/Identity/Publisher>" `
  -PublisherDisplayName "JJZero"
```

이미 `dist\JJZero Audio`가 최신 상태라면 앱 재빌드를 건너뛸 수 있다.

```powershell
.\scripts\build_msix.ps1 `
  -IdentityName "<Package/Identity/Name>" `
  -Publisher "<Package/Identity/Publisher>" `
  -PublisherDisplayName "JJZero" `
  -SkipAppBuild `
  -SkipTests
```

결과는 `release\store\JJZero-Audio-<앱 버전>-Store.msix`에 생성된다. 인증서 옵션을 전달하지 않은 로컬 결과물은 서명되지 않은 상태이며, 설치 테스트용이 아니라 Store 제출 및 구조 검증용이다.

## 비공개 배포

1. Partner Center에서 새 제출을 만들고 생성한 MSIX를 업로드한다.
2. 가격을 무료로 설정한다.
3. 가시성을 `Private audience`로 설정한다.
4. 허용할 테스터의 Microsoft 계정 이메일을 등록한다.
5. 제출 및 인증이 완료되면 제공되는 Store 링크를 테스터에게 전달한다.
6. 이후 버전은 같은 제품에 더 높은 패키지 버전으로 제출한다. 테스터는 Store를 통해 업데이트한다.

## 로컬 검증

패키지를 별도로 다시 검사하려면 다음 명령을 사용한다.

```powershell
.\scripts\verify_msix_package.ps1 `
  -PackagePath ".\release\store\JJZero-Audio-0.2.8-Store.msix" `
  -ExpectedIdentityName "<Package/Identity/Name>" `
  -ExpectedPublisher "<Package/Identity/Publisher>" `
  -ExpectedVersion "1.2.8.0"
```

검증은 매니페스트, 실행 파일, Store 채널 표식, 패키지 ID와 버전을 확인하고 선택형 AI 런타임이 패키지에 중복 포함되지 않았는지 검사한다.

## 외부에서 남은 작업

- Microsoft Partner Center 개발자 계정 등록
- 앱 이름 예약과 실제 패키지 ID 확인
- Private audience 제출 및 Microsoft 인증 통과
- 새 PC에서 Store 설치, 첫 실행 런타임 설치, Store 업데이트 검증
