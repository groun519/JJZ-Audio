# 06. Conversion Tutorial

## Status

- **Fact:** Conversion은 왼쪽 RVC input/settings/action, 오른쪽 result browser/results/transport 구조다.
- **Fact:** 입력은 `ConversionInputPool`, 모델/피치/고급 설정은 RVC settings, 품질 설정은 `RvcInferenceControls`가 담당한다.
- **Decision:** 기본 튜토리얼은 "입력 선택 → 모델/피치 → 품질 → 변환 → 결과 비교" 흐름으로 설명한다.
- **Decision:** Root/Index/Device는 고급 설정으로 설명하되 튜토리얼이 값을 변경하지 않는다.

---

## 1. 페이지 소개

Conversion은 분리된 보컬을 RVC 모델로 변환하는 페이지다.

여기서:

- 어떤 보컬을 변환할지 고른다.
- 사용할 RVC 모델을 고른다.
- Pitch를 조정한다.
- Conversion Quality preset 또는 세부값을 확인한다.
- 필요하면 Index/Device 등의 고급 설정을 확인한다.
- 변환 결과를 여러 take로 관리하고 비교한다.

---

## 2. 기본 작업 순서

1. 상단 Work Song 확인
2. Conversion Input에서 원본 보컬 선택
3. RVC Model 선택
4. Pitch 확인
5. Pitch Guide 참고
6. Conversion Quality preset 선택
7. 필요할 때만 Advanced Settings 확인
8. Convert 실행
9. RVC Pool에서 take 선택
10. Results/Transport로 원본과 결과 비교

---

## 3. 주요 기능

### Work Song

`primary_navigation.work_song_selector`

Conversion은 Work Song의 vocal 결과들을 입력 후보로 사용한다.

### Conversion Input

`conversion_input_pool`

가능한 입력 예:

- Original vocal result
- Lead stem
- Backing stem
- Cleanup result

실제 보유 결과에 따라 카드가 달라진다.

### Model

`model_combo`

Models page에서 등록된 RVC model 중 사용할 모델을 선택한다.

Model 선택 시 해당 모델의 기본 Pitch가 반영될 수 있다.

### Pitch

`pitch_spin`

semitone 단위 이동.

Pitch는 모델 음역에 맞추기 위한 핵심 설정이다.

### Pitch Guide

`pitch_guide`

Source vocal과 선택 모델의 안정적인 pitch range를 비교해 현재 Pitch가 적절한지 판단하는 보조 정보다.

모델 evaluation data가 있으면 더 정밀한 범위를 활용할 수 있다.

### Model Settings / Advanced

기본 표시:

- Model
- Pitch
- Pitch Guide

펼친 Advanced:

- RVC Root
- Index
- Device

#### Root

RVC runtime root 경로.

일반 사용자가 매 변환마다 조절하는 옵션이 아니다. 정상 설치에서는 건드리지 않는 것을 기본으로 설명한다.

#### Index

선택한 RVC model과 함께 사용할 index file.

Index 자체는 모델 사용에 필수는 아니지만 설정된 경우 timbre 반영에 영향을 줄 수 있다.

#### Device

변환 실행 장치.

System Setup에서 준비된 profile을 기본으로 사용하며, 문제 해결 목적이 아니라면 임의 변경을 권장하지 않는다.

### Conversion Quality

`rvc_inference_controls`

Preset:

- Balanced
- Timbre
- Detail

세부값:

- Index Influence
- Pitch Smoothing
- Volume Envelope
- Breath Protection

Help 기본 설명:

- **Balanced:** 안정적인 기본값
- **Timbre:** 모델 음색을 더 강하게 반영
- **Detail:** 자음/숨소리 보존을 더 중시

세부 slider는 고급 사용자용으로 본다.

### Convert

`rvc_action`

현재 input/model/settings로 새 take를 만든다.

### RVC Pool

`conversion_result_browser`

Work Song에 생성된 여러 converted take를 선택한다.

### Result panel

`vocal_results_panel`

선택한 take를 원본 vocal/instrumental과 함께 비교하고, rename/remove/reconvert/location 같은 결과 작업을 제공한다.

### Transport

`conversion_transport_bar`

결과 비교의 공통 재생/seek.

---

## 4. 주의할 점

- Input이 없으면 먼저 Separation 결과가 필요하다.
- 모델이 없으면 Models에서 가져오거나 생성해야 한다.
- Pitch는 무조건 크게 바꿀수록 좋은 값이 아니다.
- Root/Device는 일반적인 음색 조절 옵션이 아니다.
- Index와 Conversion Quality는 비슷해 보일 수 있지만 역할이 다르다.
  - Index file 선택은 사용할 검색 index 자체
  - Index Influence는 그 index를 결과에 얼마나 반영할지
- tutorial은 실제 Convert를 실행하지 않는다.
- 결과 rename/remove/reconvert도 tutorial에서 실행하지 않는다.

---

## 5. Semantic targets

| Target ID | Current mapping | Fallback |
|---|---|---|
| `navigation.work_song` | `primary_navigation.work_song_selector` | Primary navigation |
| `conversion.input` | `conversion_input_pool` | left settings scroll |
| `conversion.model` | `model_combo` | `rvc_settings_frame` |
| `conversion.pitch` | `pitch_spin` | `rvc_settings_frame` |
| `conversion.pitch_guide` | `pitch_guide` | `rvc_settings_frame` |
| `conversion.model_settings` | `rvc_settings_frame` | left panel |
| `conversion.advanced.toggle` | `rvc_settings_header` | model settings |
| `conversion.advanced` | `rvc_advanced_settings_panel` | advanced toggle |
| `conversion.index` | `index_combo` | advanced panel |
| `conversion.device` | `device_combo` | advanced panel |
| `conversion.root` | `rvc_root_edit` | advanced panel |
| `conversion.quality` | `rvc_inference_controls` | left panel |
| `conversion.action` | `rvc_action` | left panel |
| `conversion.pool` | `conversion_result_browser` | right result area |
| `conversion.results` | `vocal_results_panel` | right result area |
| `conversion.transport` | `conversion_transport_bar` | right result area |

---

## 6. Safe temporary state

Conversion tutorial은 다음 UI 상태만 임시로 바꿀 수 있다.

- Advanced Settings expand/collapse
- Conversion Quality detail expand/collapse
- scroll position

원래 expand state와 scroll 위치를 종료 시 복구한다.

다음 값은 바꾸지 않는다.

- Model selection
- Pitch
- Index
- Device
- Root
- inference preset/slider
- selected Conversion Input
- selected RVC take

---

## 7. Interactive tutorial

### CON-01 — Work Song

**Target:** `navigation.work_song`  
**Text:** "변환도 현재 Work Song을 기준으로 합니다. 먼저 어떤 곡을 작업 중인지 확인하세요."  
**Interaction:** 차단

### CON-02 — 변환할 보컬

**Target:** `conversion.input`  
**Text:** "분리된 보컬 중 실제로 RVC에 넣을 입력을 고릅니다. Lead, Backing, 정리된 vocal 등 보유 결과에 따라 카드가 달라질 수 있습니다."  
**Fallback:** empty pool  
**Data change:** 없음

### CON-03 — 모델과 Pitch

**Target:** `conversion.model` + `conversion.pitch` union  
**Text:** "RVC 모델을 고르고 필요한 semitone Pitch를 설정합니다. 모델을 선택하면 저장된 기본 Pitch가 사용될 수 있습니다."  
**Interaction:** 차단

### CON-04 — Pitch Guide

**Target:** `conversion.pitch_guide`  
**Text:** "Pitch Guide는 원본 보컬과 모델이 안정적으로 처리하는 음역을 비교합니다. 극단적인 Pitch를 정하기 전에 이 정보를 확인하세요."  
**Fallback:** model settings frame

### CON-05 — Conversion Quality

**Target:** `conversion.quality`  
**Text:** "Balanced는 기본, Timbre는 모델 음색, Detail은 자음과 숨소리 보존에 초점을 둡니다. 필요할 때만 세부 slider를 조정하세요."  
**Interaction:** 차단

### CON-06 — Advanced Settings

**Target:** TutorialRunner가 임시로 펼친 뒤 `conversion.advanced`  
**Text:** "Index는 모델 index file, Device는 실행 장치, Root는 RVC runtime 위치입니다. 정상적인 변환에서는 Root/Device를 자주 바꿀 필요가 없습니다."  
**Interaction:** 차단  
**Temporary:** advanced panel만 임시 reveal

### CON-07 — Convert

**Target:** `conversion.action`  
**Text:** "모든 설정을 확인한 뒤 Convert를 실행하면 새 RVC take가 생성됩니다. 튜토리얼에서는 실제 변환을 시작하지 않습니다."  
**Interaction:** 차단

### CON-08 — RVC Pool

**Target:** `conversion.pool`  
**Text:** "생성된 여러 take는 RVC Pool에 쌓입니다. 여기서 비교할 take를 선택합니다."  
**Fallback copy:** "아직 변환 결과가 없습니다. Convert가 끝나면 이 영역에 take가 나타납니다."

### CON-09 — 결과 비교

**Target:** `conversion.results` + `conversion.transport`  
**Text:** "선택한 converted vocal을 원본/반주와 함께 들어보고 결과를 비교합니다. 필요하면 이후 Studio에서 편집합니다."  
**Interaction:** 차단

---

## 8. Empty / disabled behavior

### Input 없음

- input pool empty state 강조
- Convert disabled 상태 설명
- Separation으로 자동 이동하지 않음

### Model 없음

- model combo 강조
- Models page가 모델 관리 위치임을 설명
- 모델 생성 dialog 자동 실행 안 함

### Pitch Guide 데이터 없음

- Pitch Guide container 또는 model settings fallback
- "모델 분석 결과가 없으면 제한된 정보만 표시될 수 있습니다."

### Result 없음

- RVC Pool empty state
- fake take 생성 안 함

---

## 9. Tests

- Work Song 없음
- Work Song 있음 / vocal result 없음
- vocal result 여러 개
- model 0개 / 1개 / 여러 개
- index 없음
- advanced collapsed/open
- quality details collapsed/open
- pitch guide data 있음/없음
- conversion running
- result 0개/여러 개
- tutorial 종료 후 advanced/quality 상태 복구

---

## 10. Acceptance

> 사용자가 Conversion에서 어떤 보컬을 어떤 모델과 Pitch로 변환하고, Index/Quality/Device가 어디에 있으며, 결과가 RVC Pool에서 어떻게 비교되는지를 실제 UI 위치로 이해하되 어떤 변환 설정이나 결과도 튜토리얼 때문에 바뀌지 않아야 한다.
