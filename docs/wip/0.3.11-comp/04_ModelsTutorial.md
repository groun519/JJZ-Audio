# 04. Models Tutorial

## Status

- **Fact:** Models는 Model Library와 선택 모델의 Model Workspace 두 단계 구조다.
- **Fact:** Model Workspace는 Overview, Dataset, Analysis, Evaluation, Training section을 가진다.
- **Decision:** 모델이 없어도 튜토리얼은 끝까지 진행한다.
- **Decision:** 모델이 실제로 열려 있을 때만 section별 실제 panel을 강조하고, 없으면 library/section 설명 fallback을 사용한다.

---

## 1. 페이지 소개

Models는 RVC 모델을 등록, 학습, 평가, 공유하고 Conversion에서 사용할 모델을 관리하는 곳이다.

모델을 추가하는 방법은 크게 다음과 같다.

- 새 Managed Model 생성
- 기존 RVC inference model 가져오기
- RVC model folder 가져오기
- Google Drive의 JJZero 공유 링크 가져오기

기존 모델 가져오기에서는 저장 방식도 선택할 수 있다.

- `Copy into JJZero`: 관리 복사본 유지
- `Link Original`: 원본 위치를 그대로 참조

---

## 2. 기본 작업 순서

### 이미 사용할 모델이 있는 경우

1. Add Model
2. Existing Model 또는 Drive Link 선택
3. 저장 방식 선택
4. Model Library에서 모델 선택
5. Overview에서 파일/프로필 확인
6. Use in Convert

### 새 모델을 학습하는 경우

1. Add Model → Create New Model
2. Dataset에 원본 오디오 추가
3. Training Set 구성 및 clip 정리
4. Analysis로 학습 재료 품질 확인
5. Training Preflight 확인
6. preset/epoch/batch 설정
7. Training 실행
8. Evaluation에서 모델 안정 구간 확인
9. 필요하면 Drive로 model work 공유
10. Use in Convert

---

## 3. 주요 기능

### Model Library

현재 구성:

- total / resume / managed summary
- Add Model
- Refresh
- Search
- Filter
- Model List

### Add Model

Dialog 첫 화면:

- Create New Model
- Import Existing Model
- Import Drive Link

Import Existing:

- Inference File (.pth)
- RVC Model Folder
- Copy into JJZero
- Link Original

Drive:

- public JJZero share link 입력

### Overview

`ModelDetailPanel`

- Name
- Tags
- Pitch
- Device
- Notes
- Runtime / Model / Index / G / D file 상태 및 relink
- Use in Convert
- Open model location

### Dataset

`ModelDatasetPanel`

- Source Audio
- Training Set
- drag/drop/add/remove
- source ↔ training 이동
- 순서 변경
- clip editor
- silence analysis/clip 정리/ready 처리

### Analysis

`ModelDatasetAnalysisPanel`

- usable duration
- model center pitch
- voice activity
- needs attention
- pitch profile
- material issue/quality 정보

### Evaluation

`ModelPrecisionBenchmarkPanel`

모델 변환 안정성을 pitch 구간별로 평가한다.

결과는 Conversion Pitch Guide에서 활용될 수 있다.

### Training

`ModelTrainingPanel`

- status/stage
- workflow progress
- runtime/activity
- recovery
- training preflight
- preset
- target epoch
- batch size
- checkpoint interval
- device
- live monitor
- log console

### Drive sharing

Model Workspace header의 `workspace_work_share_action`으로 전체 model work 공유 상태를 다룬다.

Inference model 공유와 model-work 공유는 목적이 다를 수 있으므로 Help copy에서 구분한다.

---

## 4. 주의할 점

- inference `.pth`만 있어도 Conversion용 모델로 쓸 수 있으며 Index는 선택 사항이다.
- Link Original은 원본 파일 위치가 바뀌면 relink가 필요할 수 있다.
- 학습용 모델은 Dataset/Checkpoint 상태에 따라 Training 가능 여부가 달라진다.
- Training은 긴 작업이며 tutorial이 실제 시작하지 않는다.
- Evaluation도 실제 benchmark를 실행하지 않는다.
- tutorial은 Share/Drive 요청을 보내지 않는다.

---

## 5. Semantic targets

| Target ID | Current mapping | Fallback |
|---|---|---|
| `models.library.summary` | library controls summary values | Model library left controls |
| `models.library.add` | `model_workspace_page.add_model_button` | Model Library header |
| `models.library.refresh` | `refresh_button` | Model Library header |
| `models.library.search` | `model_search_edit` | model list |
| `models.library.filter` | `model_filter_combo` | model list |
| `models.library.list` | `model_list` | Model Library panel |
| `models.workspace.sections` | section button strip | model list |
| `models.workspace.overview` | `detail_panel` | Overview button |
| `models.workspace.dataset` | `dataset_panel` | Dataset button |
| `models.workspace.analysis` | `analysis_panel` | Analysis button |
| `models.workspace.evaluation` | `evaluation_panel` | Evaluation button |
| `models.workspace.training` | `training_panel` / training workspace | Training button |
| `models.workspace.training.log` | `training_log_console` | training panel |
| `models.workspace.share` | `workspace_work_share_action` | workspace header |
| `models.workspace.use` | `detail_panel.use_button` | detail panel |

현재 `section_control`, summary frame 등 일부는 local variable이다. TargetRegistry 등록을 위해 기존 QWidget reference alias를 추가할 수 있지만 새 UI를 만들지 않는다.

---

## 6. Safe section navigation

모델 Workspace가 실제로 열려 있고 selected model이 존재하면 TutorialRunner는 다음 section으로 **보기만 이동**할 수 있다.

- Overview
- Dataset
- Analysis
- Evaluation
- Training

조건:

- 분석 실행 안 함
- 평가 실행 안 함
- 학습 실행 안 함
- dataset selection/edit 안 함
- 원래 section index를 종료 시 복구

모델이 없으면 Model Library를 벗어나지 않는다.

---

## 7. Interactive tutorial

### MOD-01 — Model Library

**Target:** `models.library.summary` 또는 Model Library left controls  
**Text:** "여기서 등록된 모델 수와 관리 상태를 확인합니다. 오른쪽 목록에서 실제 모델을 선택합니다."  
**Interaction:** 차단

### MOD-02 — 모델 추가

**Target:** `models.library.add`  
**Text:** "Add Model에서 새 학습 모델, 기존 RVC 모델, Google Drive 공유 링크 중 하나를 선택할 수 있습니다."  
**Interaction:** 차단  
**Dialog:** 실제 Add Model dialog를 열지 않는다.

### MOD-03 — 검색과 필터

**Target:** `models.library.search` + `models.library.filter`  
**Text:** "모델이 많아지면 이름 검색과 필터로 필요한 모델을 찾습니다."

### MOD-04 — 모델 목록

**Target:** `models.library.list`  
**Text:** "모델을 열면 Overview, Dataset, Analysis, Evaluation, Training 작업공간으로 들어갑니다."  
**Fallback copy:** empty library 설명

### MOD-05 — 모델 Workspace

**Target:** workspace가 열려 있으면 `models.workspace.sections`, 아니면 `models.library.list`  
**Text:** "선택한 모델의 작업은 다섯 section으로 나뉩니다. 변환만 할 모델은 Overview만 확인해도 됩니다."

### MOD-06 — Overview

**Target:** model이 있으면 safe navigate Overview → `models.workspace.overview`  
**Text:** "Overview에서 모델 프로필, pitch/device 기본값과 연결된 모델·Index·Checkpoint 파일을 확인하고 Conversion으로 보낼 수 있습니다."  
**Fallback:** Overview section button 또는 model list

### MOD-07 — Dataset / Analysis

**Target:** model이 있으면 Dataset panel, 다음 callout에서 Analysis panel을 union/순차 표시  
**Text:** "학습할 때는 먼저 Source Audio에서 Training Set을 구성하고, Analysis로 사용 가능한 길이와 pitch 분포, 문제 항목을 확인합니다."  
**Interaction:** 차단  
**Data:** clip editor 실제 조작 없음

### MOD-08 — Training

**Target:** safe navigate Training → `models.workspace.training`  
**Text:** "Training에서는 Preflight를 먼저 확인한 뒤 preset, epoch, batch와 device를 정합니다. 진행 중에는 단계, 시간, 장치 사용 상태와 로그를 볼 수 있습니다."  
**Fallback:** Training section button

### MOD-09 — Evaluation / Share

**Target:** Evaluation panel을 먼저 표시한 뒤 workspace share action을 callout anchor로 사용  
**Text:** "학습한 모델은 Evaluation으로 안정적인 pitch 범위를 확인할 수 있고, 필요하면 Drive로 model work를 공유할 수 있습니다."  
**Interaction:** 차단  
**End:** 원래 Model Workspace section 복구

---

## 8. Tutorial content scope

초보 튜토리얼에서 각 Training 파라미터의 수치 튜닝법까지 설명하지 않는다.

Help의 주요 기능에서:

- Target Epoch
- Batch Size
- Checkpoint Interval
- Resume / Start Over

의 의미를 한 줄씩 설명한다.

세부 성능 최적화와 recovery code 해석은 contextual help/diagnostics 책임이다.

---

## 9. Tests

- 모델 0개
- imported inference model
- linked model
- managed training model
- workspace Overview에서 시작
- Dataset에서 시작
- Training 중 tutorial open
- training button disabled/locked 상태
- share action hidden/disabled
- narrow model workspace
- section navigate 후 원래 section 복구

---

## 10. Acceptance

> 모델이 하나도 없는 신규 사용자에게는 Model Library의 구조와 모델 생성/가져오기 경로를 설명하고, 실제 모델이 있는 사용자에게는 현재 모델 Workspace의 Dataset → Analysis → Training → Evaluation 구조까지 실제 위치를 보여주되 어떤 모델 파일이나 학습 상태도 변경하지 않는다.
