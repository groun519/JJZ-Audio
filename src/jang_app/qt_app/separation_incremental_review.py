from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.widgets import FeedbackButton, SurfaceFrame, WaveformView
from jang_app.services.audio_player import AudioPlaybackError, AudioPlayer
from jang_app.services.separation_incremental_review import (
    COMPARISON_VALUES,
    load_incremental_responses,
    load_incremental_review,
    review_stage_definitions,
    save_incremental_responses,
)


_CLIP_ROLE_LABELS = {
    "dracula-easy": "쉬운 보컬과 과도한 처리 여부를 확인하는 기준 구간",
    "popin2-artifact": "금속성·갈라짐·고주파 잡음을 확인하는 구간",
    "999999-synthetic": "기계형 보컬의 음색과 빠른 음정 변화를 확인하는 구간",
    "o3ohn-effects": "잔향·효과음·작은 보컬·반주 유입을 확인하는 구간",
}
_RESULT_LABELS = ("더 좋음", "비슷함", "더 나쁨")


class IncrementalSeparationReviewWindow(QMainWindow):
    def __init__(self, review_path: Path) -> None:
        super().__init__()
        self.review_path = review_path.expanduser().resolve()
        self.review = load_incremental_review(self.review_path)
        self.clips = tuple(self.review["clips"])
        self.challenger_label = (
            "도전자"
            if self.review.get("review_type") == "incremental-followup"
            else "신규"
        )
        self.stage_definitions = review_stage_definitions(self.review)
        self.stages = tuple(value["key"] for value in self.stage_definitions)
        self.playback_stages = (*self.stages, "source")
        self.stage_labels = {
            value["key"]: value["label"] for value in self.stage_definitions
        }
        self.stage_labels["source"] = "원곡"
        self.stage_criteria = {
            value["key"]: value["criteria"] for value in self.stage_definitions
        }
        self.stage_criteria["source"] = (
            "처리 전 원곡을 들으며 누락과 잔류 여부를 확인합니다."
        )
        self.responses_path = Path(str(self.review["responses"])).expanduser().resolve()
        self.responses = load_incremental_responses(self.responses_path)
        self._stage = self.stages[0]
        self._position_ms = 0
        self._duration_ms = 0
        self._loading = False
        self._player = AudioPlayer()
        self._max_candidates = max(
            len(self._stage_candidates(clip, stage))
            for clip in self.clips
            for stage in self.stages
            if self._stage_candidates(clip, stage)
        )

        self.setWindowTitle(
            f"JJZero Audio - {self.review.get('title', '신규 분리 후보 비교')}"
        )
        self.resize(1180, 760)
        self.setMinimumSize(940, 680)
        self.setCentralWidget(self._build_content())

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._sync_playback)
        self._timer.start()
        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(
            self._toggle_playback
        )
        self._load_clip(0)

    def _build_content(self) -> QWidget:
        content = SurfaceFrame("background")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_group = QVBoxLayout()
        title = QLabel(str(self.review.get("title", "신규 분리 후보 비교")))
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            str(
                self.review.get(
                    "subtitle",
                    "이전 검수의 우승 결과 A를 기준으로 신규 후보의 차이만 판단합니다.",
                )
            )
        )
        subtitle.setObjectName("MutedText")
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header.addLayout(title_group, 1)
        header.addWidget(QLabel("테스트 곡"))
        self.clip_combo = QComboBox()
        self.clip_combo.setMinimumWidth(280)
        for clip in self.clips:
            self.clip_combo.addItem(str(clip.get("title", clip.get("clip_id", "곡"))))
        self.clip_combo.currentIndexChanged.connect(self._load_clip)
        header.addWidget(self.clip_combo)
        layout.addLayout(header)

        info_row = QHBoxLayout()
        self.role_label = QLabel()
        self.role_label.setObjectName("MutedText")
        self.role_label.setWordWrap(True)
        info_row.addWidget(self.role_label, 1)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("CardTitle")
        info_row.addWidget(self.progress_label)
        layout.addLayout(info_row)

        compare = SurfaceFrame("card")
        compare_layout = QVBoxLayout(compare)
        compare_layout.setContentsMargins(18, 14, 18, 16)
        compare_layout.setSpacing(10)

        control_row = QHBoxLayout()
        stage_frame, stage_layout = _segmented_frame()
        self.stage_group = QButtonGroup(self)
        for index, stage in enumerate(self.playback_stages):
            button = _segment_button(self.stage_labels[stage])
            button.setChecked(index == 0)
            self.stage_group.addButton(button, index)
            stage_layout.addWidget(button)
        self.stage_group.idClicked.connect(self._select_stage)
        control_row.addWidget(stage_frame)
        control_row.addSpacing(12)
        self.criteria_label = QLabel()
        self.criteria_label.setObjectName("MutedText")
        control_row.addWidget(self.criteria_label, 1)

        candidate_frame, candidate_layout = _segmented_frame()
        self.candidate_group = QButtonGroup(self)
        for index in range(self._max_candidates):
            button = _segment_button(chr(ord("A") + index))
            button.setMinimumWidth(84)
            self.candidate_group.addButton(button, index)
            candidate_layout.addWidget(button)
        self.candidate_group.idClicked.connect(self._select_candidate)
        control_row.addWidget(candidate_frame)
        compare_layout.addLayout(control_row)

        self.waveform = WaveformView()
        self.waveform.setMinimumHeight(150)
        self.waveform.seek_requested.connect(self._seek_ratio)
        compare_layout.addWidget(self.waveform, 1)

        self.transport = TransportControls()
        self.transport.set_shortcut_hint("Space")
        self.transport.play_toggled.connect(self._toggle_playback)
        self.transport.seek_requested.connect(self._seek)
        compare_layout.addWidget(self.transport)
        layout.addWidget(compare, 1)

        self.evaluation = SurfaceFrame("card")
        evaluation_layout = QVBoxLayout(self.evaluation)
        evaluation_layout.setContentsMargins(16, 14, 16, 14)
        evaluation_layout.setSpacing(10)
        evaluation_header = QHBoxLayout()
        evaluation_title = QLabel("기준 A와 비교")
        evaluation_title.setObjectName("CardTitle")
        evaluation_header.addWidget(evaluation_title)
        explanation = QLabel(
            "신규 후보마다 전체 질문지를 작성하지 않고 최종 차이만 선택합니다."
        )
        explanation.setObjectName("MutedText")
        evaluation_header.addWidget(explanation, 1)
        self.advance_label = QLabel()
        self.advance_label.setObjectName("MutedText")
        evaluation_header.addWidget(self.advance_label)
        evaluation_layout.addLayout(evaluation_header)

        self.comparison_rows: list[QWidget] = []
        self.comparison_labels: list[QLabel] = []
        self.comparison_groups: list[QButtonGroup] = []
        for row_index in range(max(0, self._max_candidates - 1)):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel()
            label.setMinimumWidth(110)
            label.setObjectName("CardTitle")
            row.addWidget(label)
            row.addStretch(1)
            frame, result_layout = _segmented_frame()
            group = QButtonGroup(self)
            for index, text in enumerate(_RESULT_LABELS):
                button = _segment_button(text)
                button.setFixedSize(86, 32)
                group.addButton(button, index)
                result_layout.addWidget(button)
            group.idClicked.connect(
                lambda _index, selected_row=row_index: self._save_comparison(
                    selected_row
                )
            )
            row.addWidget(frame)
            evaluation_layout.addWidget(row_widget)
            self.comparison_rows.append(row_widget)
            self.comparison_labels.append(label)
            self.comparison_groups.append(group)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("구간 메모"))
        self.notes = QPlainTextEdit()
        self.notes.setObjectName("ModelNotesInput")
        self.notes.setPlaceholderText("차이가 들린 시간과 특징만 간단히 기록하세요.")
        self.notes.setMaximumHeight(56)
        self.notes.textChanged.connect(self._save_notes)
        notes_row.addWidget(self.notes, 1)
        evaluation_layout.addLayout(notes_row)

        navigation = QHBoxLayout()
        self.save_label = QLabel()
        self.save_label.setObjectName("MutedText")
        navigation.addWidget(self.save_label, 1)
        self.previous_button = FeedbackButton("이전 곡")
        self.previous_button.clicked.connect(lambda: self._move_clip(-1))
        navigation.addWidget(self.previous_button)
        self.next_button = FeedbackButton("저장 후 다음 곡")
        self.next_button.setObjectName("PrimaryButton")
        self.next_button.clicked.connect(lambda: self._move_clip(1))
        navigation.addWidget(self.next_button)
        evaluation_layout.addLayout(navigation)
        layout.addWidget(self.evaluation)
        return content

    def set_theme_mode(self, theme_mode: str) -> None:
        self.waveform.set_theme_mode(theme_mode)
        self.transport.set_theme_mode(theme_mode)

    def _load_clip(self, index: int) -> None:
        if not 0 <= index < len(self.clips):
            return
        self._player.stop()
        self._position_ms = 0
        self.transport.set_playing(False)
        clip = self._current_clip()
        clip_id = str(clip.get("clip_id", ""))
        self.role_label.setText(
            _CLIP_ROLE_LABELS.get(clip_id, str(clip.get("role", "")))
        )
        self._sync_stage_buttons()
        self._load_stage(reset_position=True)
        self._update_status()

    def _select_stage(self, index: int) -> None:
        self._stage = self.playback_stages[index]
        self._load_stage(reset_position=False)

    def _sync_stage_buttons(self) -> None:
        clip = self._current_clip()
        available = {
            stage for stage in self.stages if self._stage_candidates(clip, stage)
        }
        if self._stage != "source" and self._stage not in available:
            self._stage = next(
                (stage for stage in self.stages if stage in available), "source"
            )
        for index, stage in enumerate(self.playback_stages):
            button = self.stage_group.button(index)
            button.setVisible(stage == "source" or stage in available)
            with QSignalBlocker(button):
                button.setChecked(stage == self._stage)

    def _load_stage(self, *, reset_position: bool) -> None:
        candidates = self._current_candidates()
        for index, button in enumerate(self.candidate_group.buttons()):
            visible = index < len(candidates)
            button.setVisible(visible)
            if visible:
                code = str(candidates[index]["code"])
                if self._stage == "source":
                    button.setText("원곡")
                else:
                    button.setText(
                        f"{code} · {'기준' if index == 0 else self.challenger_label}"
                    )
        self.candidate_group.button(0).setChecked(True)
        self.criteria_label.setText(
            f"확인 기준 · {self.stage_criteria[self._stage]}"
        )
        self.evaluation.setVisible(self._stage in self.stages)
        self._load_comparisons()
        self._refresh_track(reset_position=reset_position)

    def _load_comparisons(self) -> None:
        candidates = self._current_candidates()
        comparisons = self.responses.get("comparisons", {})
        comparisons = comparisons if isinstance(comparisons, Mapping) else {}
        self._loading = True
        try:
            if self._stage == "source":
                for row in self.comparison_rows:
                    row.setVisible(False)
                return
            for row_index, row in enumerate(self.comparison_rows):
                candidate_index = row_index + 1
                visible = candidate_index < len(candidates)
                row.setVisible(visible)
                _clear_group(self.comparison_groups[row_index])
                if not visible:
                    continue
                code = str(candidates[candidate_index]["code"])
                self.comparison_labels[row_index].setText(f"후보 {code}")
                value = str(comparisons.get(self._comparison_key(code), ""))
                _set_group_value(
                    self.comparison_groups[row_index], COMPARISON_VALUES, value
                )
            notes = self.responses.get("notes", {})
            notes = notes if isinstance(notes, Mapping) else {}
            with QSignalBlocker(self.notes):
                self.notes.setPlainText(str(notes.get(self._notes_key(), "")))
        finally:
            self._loading = False
        self._update_status()

    def _save_comparison(self, row_index: int) -> None:
        if self._loading:
            return
        candidates = self._current_candidates()
        candidate_index = row_index + 1
        if candidate_index >= len(candidates):
            return
        code = str(candidates[candidate_index]["code"])
        value = _group_value(self.comparison_groups[row_index], COMPARISON_VALUES)
        if not value:
            return
        comparisons = self.responses.setdefault("comparisons", {})
        if not isinstance(comparisons, dict):
            comparisons = {}
            self.responses["comparisons"] = comparisons
        comparisons[self._comparison_key(code)] = value
        self._persist()

    def _save_notes(self) -> None:
        if self._loading:
            return
        notes = self.responses.setdefault("notes", {})
        if not isinstance(notes, dict):
            notes = {}
            self.responses["notes"] = notes
        text = self.notes.toPlainText().strip()
        if text:
            notes[self._notes_key()] = text
        else:
            notes.pop(self._notes_key(), None)
        self._persist()

    def _persist(self) -> None:
        save_incremental_responses(self.responses_path, self.responses)
        self.save_label.setText(f"자동 저장됨 · {self.responses_path.name}")
        self._update_status()

    def _select_candidate(self, _index: int) -> None:
        if self._player.is_playing():
            self._player.set_volumes(self._candidate_volumes())
        self._refresh_waveform()

    def _move_clip(self, offset: int) -> None:
        target = max(
            0, min(len(self.clips) - 1, self.clip_combo.currentIndex() + offset)
        )
        self.clip_combo.setCurrentIndex(target)

    def _refresh_track(self, *, reset_position: bool) -> None:
        was_playing = self._player.is_playing()
        if reset_position:
            self._position_ms = 0
        elif was_playing:
            self._position_ms = self._player.position_ms()
        self._player.stop()
        path = self._selected_path()
        try:
            self._duration_ms = self._player.duration_ms(path)
        except AudioPlaybackError:
            self._duration_ms = 0
        self.transport.set_position(self._position_ms, self._duration_ms)
        self.transport.set_playing(False)
        self._refresh_waveform()
        if was_playing and self._duration_ms > 0:
            self._start_playback()

    def _toggle_playback(self) -> None:
        if self._player.is_playing():
            self._position_ms = self._player.position_ms()
            self._player.pause()
            self.transport.set_playing(False)
            return
        if self._duration_ms <= 0:
            return
        if self._position_ms >= self._duration_ms:
            self._position_ms = 0
        self._start_playback()

    def _start_playback(self) -> None:
        try:
            self._player.play(
                [Path(str(candidate["path"])) for candidate in self._current_candidates()],
                self._position_ms,
                self._candidate_volumes(),
            )
        except AudioPlaybackError as exc:
            self.save_label.setText(str(exc))
            return
        self.transport.set_playing(True)

    def _seek(self, position_ms: int) -> None:
        was_playing = self._player.is_playing()
        self._position_ms = max(0, min(position_ms, self._duration_ms))
        if was_playing:
            self._start_playback()
        else:
            self.transport.set_position(self._position_ms)
            self._refresh_waveform()

    def _seek_ratio(self, ratio: float) -> None:
        self._seek(round(self._duration_ms * max(0.0, min(1.0, ratio))))

    def _sync_playback(self) -> None:
        if self._player.is_playing():
            self._position_ms = self._player.position_ms()
            self.transport.set_position(self._position_ms)
            self.waveform.set_playhead_ratio(
                self._position_ms / self._duration_ms if self._duration_ms else 0.0
            )
            return
        if self.transport.play_button.icon_name() == "stop":
            self._position_ms = min(self._duration_ms, self._player.position_ms())
            self.transport.set_position(self._position_ms)
            self.transport.set_playing(False)

    def _refresh_waveform(self) -> None:
        self.waveform.set_path(self._selected_path())
        self.waveform.set_playhead_ratio(
            self._position_ms / self._duration_ms if self._duration_ms else 0.0
        )

    def _candidate_volumes(self) -> list[float]:
        selected = max(0, self.candidate_group.checkedId())
        return [
            1.0 if index == selected else 0.0
            for index in range(len(self._current_candidates()))
        ]

    def _selected_path(self) -> Path:
        index = max(0, self.candidate_group.checkedId())
        candidates = self._current_candidates()
        index = min(index, len(candidates) - 1)
        return Path(str(candidates[index]["path"]))

    def _current_clip(self) -> Mapping[str, object]:
        return self.clips[max(0, self.clip_combo.currentIndex())]

    def _current_candidates(self) -> tuple[Mapping[str, object], ...]:
        if self._stage == "source":
            return ({"code": "A", "path": self._current_clip()["source"]},)
        return self._stage_candidates(self._current_clip(), self._stage)

    @staticmethod
    def _stage_candidates(
        clip: Mapping[str, object], stage: str
    ) -> tuple[Mapping[str, object], ...]:
        stages = clip.get("stages", {})
        stage_data = stages.get(stage, {}) if isinstance(stages, Mapping) else {}
        candidates = (
            stage_data.get("candidates", {})
            if isinstance(stage_data, Mapping)
            else {}
        )
        if not isinstance(candidates, list):
            return ()
        return tuple(value for value in candidates if isinstance(value, Mapping))

    def _comparison_key(self, code: str) -> str:
        return f"{self._current_clip()['clip_id']}:{self._stage}:{code}"

    def _notes_key(self) -> str:
        return f"{self._current_clip()['clip_id']}:{self._stage}"

    def _update_status(self) -> None:
        comparisons = self.responses.get("comparisons", {})
        comparisons = comparisons if isinstance(comparisons, Mapping) else {}
        valid_keys = {
            f"{clip['clip_id']}:{stage}:{candidate['code']}"
            for clip in self.clips
            for stage in self.stages
            for candidate in self._stage_candidates(clip, stage)[1:]
        }
        complete = sum(
            1
            for key in valid_keys
            if comparisons.get(key) in COMPARISON_VALUES
        )
        advanced = sum(1 for key in valid_keys if comparisons.get(key) == "better")
        self.progress_label.setText(
            f"곡 {self.clip_combo.currentIndex() + 1} / {len(self.clips)} · "
            f"판단 {complete} / {len(valid_keys)}"
        )
        self.advance_label.setText(f"현재 우세 후보 {advanced}개")
        self.previous_button.setEnabled(self.clip_combo.currentIndex() > 0)
        self.next_button.setEnabled(self.clip_combo.currentIndex() < len(self.clips) - 1)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_notes()
        self._player.stop()
        super().closeEvent(event)


def _segmented_frame() -> tuple[QFrame, QHBoxLayout]:
    frame = QFrame()
    frame.setObjectName("SegmentedControl")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(4)
    return frame, layout


def _segment_button(label: str) -> FeedbackButton:
    button = FeedbackButton(label)
    button.setObjectName("SegmentButton")
    button.setCheckable(True)
    return button


def _clear_group(group: QButtonGroup) -> None:
    group.setExclusive(False)
    try:
        for button in group.buttons():
            with QSignalBlocker(button):
                button.setChecked(False)
    finally:
        group.setExclusive(True)


def _set_group_value(
    group: QButtonGroup, values: tuple[str, ...], value: str
) -> None:
    _clear_group(group)
    if value in values:
        button = group.button(values.index(value))
        if button is not None:
            with QSignalBlocker(button):
                button.setChecked(True)


def _group_value(group: QButtonGroup, values: tuple[str, ...]) -> str:
    index = group.checkedId()
    return values[index] if 0 <= index < len(values) else ""
