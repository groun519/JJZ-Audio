# 05. Separation Tutorial

## Status

- **Fact:** Audio Separation page는 왼쪽 Recipe/Action, 오른쪽 Stem Pool/Results/Transport 구조다.
- **Fact:** 현재 recipe selector는 Fast Separation, Precision Separation(MelBand), Custom 경로를 제공한다.
- **Decision:** 기본 page tutorial은 Audio Separation을 기준으로 한다.
- **Decision:** Vocal Separation 서브모드가 unavailable/in development인 경우 tutorial이 진입을 시도하지 않는다.

---

## 1. 페이지 소개

Separation은 현재 Work Song에서 보컬과 반주 stem을 만드는 페이지다.

분리 결과는 Conversion의 입력, Studio의 Sound Pool, Library의 Vocal 자산으로 이어질 수 있다.

---

## 2. 기본 작업 순서

1. 상단에서 Work Song 확인
2. 분리 방식 선택
3. 방식 설명과 모델 준비 상태 확인
4. Separate 실행
5. Stem Pool에서 결과 버전 확인
6. 필요하면 Vocal/Instrumental 조합 선택
7. 오른쪽 결과를 재생해 비교
8. 만족한 결과를 Conversion에서 사용

---

## 3. 분리 방식

### Fast Separation

현재 HTDemucs 기반.

권장:

- 빠른 preview
- 낮은 사양
- ambience가 보컬에 섞여 있는 곡의 빠른 확인

### Precision Separation

현재 Vocal MelBand-RoFormer 기반.

UI copy 기준 RVC 변환과 최종 vocal production 전에 권장되는 기본 고품질 경로다.

첫 사용 시 필요한 모델이 다운로드될 수 있다.

### Custom

Vocal model과 Instrumental model을 각각 선택한다.

같은 모델을 두 역할에 선택하면 한 번 실행할 수 있고, 다른 모델을 고르면 두 모델을 실행해 stem을 조합한다.

따라서 가장 느릴 수 있다.

---

## 4. 주요 기능

### Work Song

`primary_navigation.work_song_selector`

Separation page 안에서 별도 곡 picker를 중복 생성하지 않는다.

### Recipe Selector

`separation_recipe_selector`

구성:

- method segmented buttons
- 현재 method title/description
- Model ready / download status
- recommended use
- processing time
- model run count
- precision
- mix correction

Custom일 때:

- Vocal model
- Instrumental model

### Separate

`separation_action`

Work Song과 runtime/model 조건이 준비되어야 활성화될 수 있다.

### Stem Pool

`separation_stem_pool`

- Vocal result pool
- Instrumental result pool
- paired/unpaired selection

Pair가 켜져 있으면 같은 separation run의 vocal/instrumental을 함께 고른다.

Pair를 풀면 서로 다른 결과의 stem을 조합해 비교할 수 있다.

### Results

`separation_results_panel`

선택된 stem 조합을 비교/재생한다.

### Transport

`separation_transport_bar`

재생/seek를 담당한다.

---

## 5. 주의할 점

- 첫 Precision 실행은 모델 다운로드 때문에 평소보다 오래 걸릴 수 있다.
- Custom에서 서로 다른 모델 두 개를 선택하면 두 번의 model run이 필요할 수 있다.
- Stem Pool에서 pair를 해제한 조합은 원래 같은 run의 쌍이 아닐 수 있다.
- Tutorial은 Separate를 실제 실행하지 않는다.
- Singer/Vocal Separation 별도 기능은 backend capability에 따라 비활성일 수 있으며 Audio Separation tutorial과 섞지 않는다.

---

## 6. Semantic targets

| Target ID | Current mapping | Fallback |
|---|---|---|
| `navigation.work_song` | `primary_navigation.work_song_selector` | Primary navigation |
| `separation.recipe` | `separation_recipe_selector` | left panel |
| `separation.recipe.methods` | `separation_recipe_selector.method_control` | selector |
| `separation.recipe.custom` | `custom_model_frame` when visible | selector |
| `separation.action` | `separation_action` | left panel |
| `separation.stems` | `separation_stem_pool` | separation result area |
| `separation.stems.pair` | `separation_stem_pool.pair_button` | stem pool |
| `separation.results` | `separation_results_panel` | result area |
| `separation.transport` | `separation_transport_bar` | result area |

---

## 7. Interactive tutorial

### SEP-01 — Work Song

**Target:** `navigation.work_song`  
**Text:** "분리는 현재 Work Song을 대상으로 합니다. 작업곡은 모든 제작 페이지가 공유합니다."  
**Interaction:** 차단

### SEP-02 — 분리 방식

**Target:** `separation.recipe.methods`  
**Text:** "Fast는 빠른 확인, Precision은 RVC 전 고품질 분리, Custom은 Vocal과 Instrumental 모델을 따로 고를 때 사용합니다."  
**Interaction:** 차단

### SEP-03 — 방식 상세 정보

**Target:** `separation.recipe`  
**Text:** "선택한 방식의 목적, 처리 시간, 모델 실행 수와 모델 준비 상태를 여기서 확인할 수 있습니다. 첫 사용에는 모델 다운로드가 필요할 수 있습니다."  
**Interaction:** 차단

### SEP-04 — 실행

**Target:** `separation.action`  
**Text:** "준비가 되면 Separate를 눌러 새 분리 결과를 만듭니다. 튜토리얼에서는 작업을 실행하지 않습니다."  
**Interaction:** 차단

### SEP-05 — Stem Pool

**Target:** `separation.stems`  
**Text:** "완료된 분리 결과의 Vocal과 Instrumental 버전이 이곳에 쌓입니다. 결과가 없어도 이 영역의 구조는 동일합니다."  
**Fallback copy:** empty pool

### SEP-06 — Pair

**Target:** `separation.stems.pair`  
**Text:** "Pair가 켜져 있으면 같은 run의 두 stem을 함께 선택합니다. 끄면 Vocal과 Instrumental을 독립적으로 골라 비교할 수 있습니다."  
**Interaction:** 차단

### SEP-07 — 결과 비교

**Target:** `separation.results` + `separation.transport`  
**Text:** "오른쪽에서 선택한 stem 조합을 확인하고 하단 Transport로 재생 위치를 비교합니다. 이후 선택된 Vocal을 Conversion에서 사용할 수 있습니다."  
**Interaction:** 차단

---

## 8. Empty / disabled behavior

Work Song 없음:

- recipe UI는 설명 가능
- action disabled 상태 그대로 강조
- "작업곡을 지정하면 실행할 수 있습니다" copy

분리 결과 없음:

- Stem Pool container 강조
- Results empty state 강조
- fake result 생성 안 함

Precision asset 미설치:

- status label을 그대로 보여줌
- 다운로드를 시작하지 않음

---

## 9. Tests

- Work Song 없음
- Work Song 있음 / 결과 없음
- Fast 선택
- Precision 선택 / asset ready
- Precision 선택 / download required
- Custom 선택
- stem 1개 / 여러 개
- pair on/off
- separation job running
- Vocal Separation submenu disabled

---

## 10. Acceptance

> Separation을 처음 보는 사용자가 실제 작업을 실행하지 않고도 "어떤 곡을 대상으로 어떤 방식으로 분리하고, 결과가 어디에 쌓이며, 왜 Pair가 있는지"를 이해할 수 있어야 한다.
