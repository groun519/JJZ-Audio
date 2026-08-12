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
from jang_app.services.separation_benchmark_review import (
    REVIEW_TYPE_CONVERSION,
    REVIEW_TYPE_HYBRID,
    load_blind_review,
    load_review_responses,
    save_review_responses,
)


_CLIP_ROLE_LABELS = {
    "dracula-easy": "쉬운 보컬과 과도한 처리 여부를 확인하는 기준 구간",
    "popin2-artifact": "금속성·갈라짐·고주파 잡음을 확인하는 구간",
    "999999-synthetic": "기계음 보컬의 음색과 빠른 음정 변화를 확인하는 구간",
    "o3ohn-effects": "리버브·효과음·작은 보컬·반주 유입을 확인하는 구간",
}
_VOCAL_QUESTIONS = (
    ("vocal_missing", "보컬이 빠지거나 작아진 부분이 있나요?"),
    ("vocal_unwanted_sound", "악기나 불필요한 소리가 남았나요?"),
    ("vocal_effect_residue", "리버브·딜레이·겹보컬 같은 효과가 남았나요?"),
    ("vocal_damage", "목소리가 갈라지거나 인공적으로 변했나요?"),
)
_INSTRUMENTAL_QUESTIONS = (
    ("instrumental_vocal_residue", "원래 보컬이 남았나요?"),
    ("instrumental_effect_residue", "보컬의 잔향·딜레이·코러스가 남았나요?"),
    ("instrumental_damage", "악기가 잘리거나 약해졌나요?"),
    ("instrumental_artifacts", "울렁임·금속성·펌핑 같은 잡음이 생겼나요?"),
)
_CONVERTED_QUESTIONS = (
    ("converted_missing", "변환 후 보컬이 빠지거나 작아진 부분이 있나요?"),
    ("converted_pitch", "음정이 흔들리거나 잘못 따라가는 부분이 있나요?"),
    ("converted_timbre", "목소리의 음색이 구간마다 불안정한가요?"),
    ("converted_artifacts", "갈라짐·금속성·물먹은 소리 같은 잡음이 있나요?"),
)
_MIX_QUESTIONS = (
    ("mix_original_vocal", "원래 가수의 목소리가 겹쳐 들리나요?"),
    ("mix_vocal_clarity", "변환 보컬이 반주에 묻히거나 알아듣기 어려운가요?"),
    ("mix_balance", "보컬과 반주의 음량 균형이 어색한가요?"),
    ("mix_naturalness", "완성곡으로 들었을 때 부자연스러운 부분이 있나요?"),
)
_ANSWER_VALUES = ("none", "some", "severe")
_DECISION_VALUES = ("keep", "repair", "reject")
_SEPARATION_STAGES = (
    ("vocals", "보컬"),
    ("instrumental", "반주"),
    ("source", "원곡"),
)
_CONVERSION_STAGES = (
    ("converted_vocals", "변환 보컬"),
    ("final_mix", "최종 믹스"),
    ("vocals", "분리 보컬"),
    ("instrumental", "반주"),
    ("source", "원곡"),
)
_HYBRID_STAGES = (
    ("final_mix", "최종 믹스"),
    ("converted_vocals", "변환 보컬"),
    ("instrumental", "반주"),
    ("source", "원곡"),
)
_WINDOW_TITLES = {
    REVIEW_TYPE_CONVERSION: "JJZero Audio - 블라인드 변환 결과 비교",
    REVIEW_TYPE_HYBRID: "JJZero Audio - 블라인드 하이브리드 비교",
}
_PAGE_TITLES = {
    REVIEW_TYPE_CONVERSION: "블라인드 변환 결과 비교",
    REVIEW_TYPE_HYBRID: "블라인드 하이브리드 비교",
}
_PAGE_SUBTITLES = {
    REVIEW_TYPE_CONVERSION: "같은 pq-a 설정으로 변환된 보컬과 최종 믹스를 듣고 평가합니다.",
    REVIEW_TYPE_HYBRID: (
        "최종 믹스를 먼저 평가하고, 필요할 때 같은 위치의 변환 보컬과 반주를 확인합니다."
    ),
}


class SeparationBenchmarkReviewWindow(QMainWindow):
    def __init__(self, review_path: Path) -> None:
        super().__init__()
        self.review_path = review_path.expanduser().resolve()
        self.review = load_blind_review(self.review_path)
        self.clips = tuple(self.review["clips"])
        self.review_type = str(self.review.get("review_type", "separation"))
        self.stage_specs = _stage_specs(self.review_type)
        self.question_sections = _question_sections(self.review_type)
        self.question_ids = tuple(
            key
            for _title, _hint, questions, _stage in self.question_sections
            for key, _label in questions
        )
        self.decision_stages = tuple(section[3] for section in self.question_sections)
        self.responses_path = Path(str(self.review["responses"])).expanduser().resolve()
        self.responses = load_review_responses(self.responses_path)
        self._loading_response = False
        self._position_ms = 0
        self._duration_ms = 0
        self._stage = self.stage_specs[0][0]
        self._player = AudioPlayer()

        self.setWindowTitle(
            _WINDOW_TITLES.get(
                self.review_type, "JJZero Audio - 블라인드 분리 결과 비교"
            )
        )
        self.resize(1240, 900)
        self.setMinimumSize(980, 720)
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

        title = QLabel(
            _PAGE_TITLES.get(self.review_type, "블라인드 분리 결과 비교")
        )
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            _PAGE_SUBTITLES.get(
                self.review_type,
                "각 구간의 A/B/C를 같은 위치에서 듣고, 실제로 들리는 문제만 기록합니다.",
            )
        )
        subtitle.setObjectName("MutedText")
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)

        self.clip_combo = QComboBox()
        self.clip_combo.setMinimumWidth(300)
        for clip in self.clips:
            self.clip_combo.addItem(str(clip.get("title", clip.get("clip_id", "구간"))))
        self.clip_combo.currentIndexChanged.connect(self._load_clip)
        header = QHBoxLayout()
        header.addLayout(title_group, 1)
        header.addWidget(QLabel("테스트 구간"))
        header.addWidget(self.clip_combo)
        layout.addLayout(header)

        info_row = QHBoxLayout()
        self.role_label = QLabel()
        self.role_label.setObjectName("MutedText")
        self.role_label.setWordWrap(True)
        info_row.addWidget(self.role_label, 1)
        self.combination_label = QLabel()
        self.combination_label.setObjectName("CardTitle")
        info_row.addWidget(self.combination_label)
        layout.addLayout(info_row)

        compare = SurfaceFrame("card")
        compare_layout = QVBoxLayout(compare)
        compare_layout.setContentsMargins(18, 14, 18, 16)
        compare_layout.setSpacing(10)

        stage_row = QHBoxLayout()
        stage_row.addWidget(QLabel("듣기"))
        stage_frame, stage_layout = _segmented_frame()
        self.stage_group = QButtonGroup(self)
        self.stage_group.setExclusive(True)
        for index, (_stage, label) in enumerate(self.stage_specs):
            button = _segment_button(label)
            button.setChecked(index == 0)
            self.stage_group.addButton(button, index)
            stage_layout.addWidget(button)
        self.stage_group.idClicked.connect(self._select_stage)
        stage_row.addWidget(stage_frame)
        stage_row.addStretch(1)

        candidate_frame, candidate_layout = _segmented_frame()
        self.candidate_group = QButtonGroup(self)
        self.candidate_group.setExclusive(True)
        candidate_count = len(self.clips[0]["candidates"])
        for index in range(candidate_count):
            button = _segment_button(chr(ord("A") + index))
            button.setChecked(index == 0)
            self.candidate_group.addButton(button, index)
            candidate_layout.addWidget(button, 1)
        self.candidate_group.idClicked.connect(self._select_candidate)
        stage_row.addWidget(candidate_frame)
        compare_layout.addLayout(stage_row)

        self.waveform = WaveformView()
        self.waveform.setMinimumHeight(120)
        self.waveform.seek_requested.connect(self._seek_ratio)
        compare_layout.addWidget(self.waveform, 1)

        self.transport = TransportControls()
        self.transport.set_shortcut_hint("Space")
        self.transport.play_toggled.connect(self._toggle_playback)
        self.transport.seek_requested.connect(self._seek)
        compare_layout.addWidget(self.transport)
        layout.addWidget(compare, 1)

        evaluation = SurfaceFrame("card")
        evaluation_layout = QVBoxLayout(evaluation)
        evaluation_layout.setContentsMargins(16, 14, 16, 14)
        evaluation_layout.setSpacing(10)
        evaluation_header = QHBoxLayout()
        evaluation_title = QLabel("현재 조합 평가")
        evaluation_title.setObjectName("CardTitle")
        evaluation_header.addWidget(evaluation_title)
        evaluation_header.addStretch(1)
        evaluation_header.addWidget(QLabel("문제 정도:  없음 / 조금 / 심함"))
        evaluation_layout.addLayout(evaluation_header)

        self.issue_groups: dict[str, QButtonGroup] = {}
        self.decision_groups: dict[str, QButtonGroup] = {}
        question_row = QHBoxLayout()
        question_row.setSpacing(12)
        for section_title, hint, questions, stage in self.question_sections:
            question_row.addWidget(
                self._build_question_section(section_title, hint, questions, stage),
                1,
            )
        evaluation_layout.addLayout(question_row)

        winner_row = QHBoxLayout()
        winner_row.addWidget(QLabel("이 구간에서 가장 나은 결과"))
        winner_frame, winner_layout = _segmented_frame()
        self.winner_group = QButtonGroup(self)
        self.winner_group.setExclusive(True)
        for index in range(candidate_count):
            button = _segment_button(chr(ord("A") + index))
            self.winner_group.addButton(button, index)
            winner_layout.addWidget(button)
        no_difference = _segment_button("차이 없음")
        self.winner_group.addButton(no_difference, candidate_count)
        winner_layout.addWidget(no_difference)
        self.winner_group.idClicked.connect(self._save_clip_winner)
        winner_row.addWidget(winner_frame)
        self.winner_hint = QLabel()
        self.winner_hint.setObjectName("MutedText")
        winner_row.addWidget(self.winner_hint, 1)
        evaluation_layout.addLayout(winner_row)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("조합 메모"))
        self.notes = QPlainTextEdit()
        self.notes.setObjectName("ModelNotesInput")
        self.notes.setPlaceholderText("문제가 들린 시간과 특징을 기록하세요")
        self.notes.setMaximumHeight(58)
        self.notes.textChanged.connect(self._save_current_response)
        notes_row.addWidget(self.notes, 1)
        evaluation_layout.addLayout(notes_row)

        navigation = QHBoxLayout()
        self.save_label = QLabel()
        self.save_label.setObjectName("MutedText")
        navigation.addWidget(self.save_label, 1)
        self.previous_button = FeedbackButton("이전 조합")
        self.previous_button.clicked.connect(lambda: self._move_combination(-1))
        navigation.addWidget(self.previous_button)
        self.next_button = FeedbackButton("저장 후 다음 조합")
        self.next_button.setObjectName("PrimaryButton")
        self.next_button.clicked.connect(lambda: self._move_combination(1))
        navigation.addWidget(self.next_button)
        evaluation_layout.addLayout(navigation)
        layout.addWidget(evaluation)
        return content

    def _build_question_section(
        self,
        title: str,
        hint: str,
        questions: tuple[tuple[str, str], ...],
        stage: str,
    ) -> QFrame:
        section = SurfaceFrame("raised")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(6)
        title_row = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        title_row.addWidget(title_label)
        hint_label = QLabel(hint)
        hint_label.setObjectName("MutedText")
        title_row.addWidget(hint_label, 1)
        section_layout.addLayout(title_row)

        for question_id, question in questions:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(question)
            label.setWordWrap(True)
            row.addWidget(label, 1)
            answer_frame, answer_layout = _segmented_frame()
            group = QButtonGroup(self)
            group.setExclusive(True)
            for index, answer in enumerate(("없음", "조금", "심함")):
                button = _compact_segment_button(answer, width=54)
                group.addButton(button, index)
                answer_layout.addWidget(button)
            group.idClicked.connect(
                lambda _index, selected_stage=stage: self._answer_changed(selected_stage)
            )
            self.issue_groups[question_id] = group
            row.addWidget(answer_frame)
            section_layout.addLayout(row)

        decision_row = QHBoxLayout()
        decision_row.addWidget(QLabel("이 파일을 다음 작업에 사용할 수 있나요?"), 1)
        decision_frame, decision_layout = _segmented_frame()
        decision_group = QButtonGroup(self)
        decision_group.setExclusive(True)
        for index, answer in enumerate(("바로 사용", "수정 필요", "사용 불가")):
            button = _compact_segment_button(answer, width=72)
            decision_group.addButton(button, index)
            decision_layout.addWidget(button)
        decision_group.idClicked.connect(
            lambda _index, selected_stage=stage: self._answer_changed(selected_stage)
        )
        self.decision_groups[stage] = decision_group
        decision_row.addWidget(decision_frame)
        section_layout.addLayout(decision_row)
        return section

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
        self._refresh_track(reset_position=True)
        self._load_current_response()
        self._load_clip_winner()
        self._update_evaluation_status()

    def _select_candidate(self, _index: int) -> None:
        if self._stage != "source" and self._player.is_playing():
            self._player.set_volumes(self._candidate_volumes())
        self._refresh_waveform()
        self._load_current_response()
        self._update_evaluation_status()

    def _select_stage(self, index: int) -> None:
        self._set_stage(self.stage_specs[index][0])

    def _set_stage(self, stage: str) -> None:
        stages = tuple(value for value, _label in self.stage_specs)
        if stage not in stages:
            return
        self._stage = stage
        stage_index = stages.index(stage)
        self.stage_group.button(stage_index).setChecked(True)
        enabled = stage != "source"
        for button in self.candidate_group.buttons():
            button.setEnabled(enabled)
        self._refresh_track(reset_position=False)

    def _answer_changed(self, stage: str) -> None:
        if self._stage != stage:
            self._set_stage(stage)
        self._save_current_response()

    def _move_combination(self, offset: int) -> None:
        self._save_current_response()
        candidate_count = len(self.candidate_group.buttons())
        current = self.clip_combo.currentIndex() * candidate_count + max(
            0,
            self.candidate_group.checkedId(),
        )
        target = max(0, min(len(self.clips) * candidate_count - 1, current + offset))
        target_clip, target_candidate = divmod(target, candidate_count)
        with QSignalBlocker(self.clip_combo):
            self.clip_combo.setCurrentIndex(target_clip)
        self.candidate_group.button(target_candidate).setChecked(True)
        self._load_clip(target_clip)

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

    def _refresh_waveform(self) -> None:
        self.waveform.set_path(self._selected_path())
        self.waveform.set_playhead_ratio(
            self._position_ms / self._duration_ms if self._duration_ms else 0.0
        )

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
                self._playback_paths(),
                self._position_ms,
                self._playback_volumes(),
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
            self.waveform.set_playhead_ratio(
                self._position_ms / self._duration_ms if self._duration_ms else 0.0
            )

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

    def _playback_paths(self) -> list[Path]:
        clip = self._current_clip()
        if self._stage == "source":
            return [Path(str(clip["source"]))]
        return [Path(str(candidate[self._stage])) for candidate in clip["candidates"]]

    def _playback_volumes(self) -> list[float]:
        return [1.0] if self._stage == "source" else self._candidate_volumes()

    def _candidate_volumes(self) -> list[float]:
        selected = max(0, self.candidate_group.checkedId())
        return [
            1.0 if index == selected else 0.0
            for index in range(len(self.candidate_group.buttons()))
        ]

    def _selected_path(self) -> Path:
        clip = self._current_clip()
        if self._stage == "source":
            return Path(str(clip["source"]))
        candidates = clip["candidates"]
        index = max(0, self.candidate_group.checkedId())
        return Path(str(candidates[index][self._stage]))

    def _current_clip(self) -> Mapping[str, object]:
        return self.clips[max(0, self.clip_combo.currentIndex())]

    def _response_key(self) -> str:
        clip_id = self._current_clip()["clip_id"]
        candidate = self._current_clip()["candidates"][
            max(0, self.candidate_group.checkedId())
        ]
        return f"{clip_id}:{candidate['code']}"

    def _current_record(self) -> Mapping[str, object]:
        ratings = self.responses.get("ratings", {})
        if not isinstance(ratings, Mapping):
            return {}
        record = ratings.get(self._response_key(), {})
        return record if isinstance(record, Mapping) else {}

    def _load_current_response(self) -> None:
        record = self._current_record()
        issues = record.get("issues", {}) if isinstance(record, Mapping) else {}
        decisions = record.get("decisions", {}) if isinstance(record, Mapping) else {}
        self._loading_response = True
        try:
            for question_id, group in self.issue_groups.items():
                value = issues.get(question_id, "") if isinstance(issues, Mapping) else ""
                _set_group_value(group, _ANSWER_VALUES, str(value))
            for stage, group in self.decision_groups.items():
                value = decisions.get(stage, "") if isinstance(decisions, Mapping) else ""
                _set_group_value(group, _DECISION_VALUES, str(value))
            with QSignalBlocker(self.notes):
                self.notes.setPlainText(str(record.get("notes", "")))
        finally:
            self._loading_response = False
        self.save_label.setText("")

    def _save_current_response(self, *_args) -> None:
        if self._loading_response:
            return
        ratings = self.responses.setdefault("ratings", {})
        if not isinstance(ratings, dict):
            ratings = {}
            self.responses["ratings"] = ratings
        candidate = self._current_clip()["candidates"][
            max(0, self.candidate_group.checkedId())
        ]
        issues = {
            question_id: _group_value(group, _ANSWER_VALUES)
            for question_id, group in self.issue_groups.items()
            if _group_value(group, _ANSWER_VALUES)
        }
        decisions = {
            stage: _group_value(group, _DECISION_VALUES)
            for stage, group in self.decision_groups.items()
            if _group_value(group, _DECISION_VALUES)
        }
        notes = self.notes.toPlainText().strip()
        response_key = self._response_key()
        if not issues and not decisions and not notes and response_key not in ratings:
            return
        ratings[response_key] = {
            "clip_id": self._current_clip()["clip_id"],
            "candidate_code": candidate["code"],
            "issues": issues,
            "decisions": decisions,
            "notes": notes,
        }
        save_review_responses(self.responses_path, self.responses)
        self.save_label.setText(f"저장됨 · {self.responses_path.name}")
        self._update_evaluation_status()

    def _load_clip_winner(self) -> None:
        winners = self.responses.get("winners", {})
        clip_id = str(self._current_clip()["clip_id"])
        value = winners.get(clip_id, "") if isinstance(winners, Mapping) else ""
        values = tuple(
            str(candidate["code"]) for candidate in self._current_clip()["candidates"]
        ) + ("same",)
        _set_group_value(self.winner_group, values, str(value))

    def _save_clip_winner(self, *_args) -> None:
        values = tuple(
            str(candidate["code"]) for candidate in self._current_clip()["candidates"]
        ) + ("same",)
        value = _group_value(self.winner_group, values)
        if not value:
            return
        winners = self.responses.setdefault("winners", {})
        if not isinstance(winners, dict):
            winners = {}
            self.responses["winners"] = winners
        winners[str(self._current_clip()["clip_id"])] = value
        save_review_responses(self.responses_path, self.responses)
        self.save_label.setText(f"구간 최종 선택 저장됨 · {value}")

    def _update_evaluation_status(self) -> None:
        ratings = self.responses.get("ratings", {})
        ratings = ratings if isinstance(ratings, Mapping) else {}
        candidate_count = len(self.candidate_group.buttons())
        total = len(self.clips) * candidate_count
        complete_count = sum(
            1 for record in ratings.values() if self._record_is_complete(record)
        )
        current_index = self.clip_combo.currentIndex() * candidate_count + max(
            0,
            self.candidate_group.checkedId(),
        )
        current_code = self._current_clip()["candidates"][
            max(0, self.candidate_group.checkedId())
        ]["code"]
        self.combination_label.setText(
            f"현재 평가 {current_index + 1} / {total} · 후보 {current_code} · 완료 {complete_count}"
        )
        self.previous_button.setEnabled(current_index > 0)
        self.next_button.setEnabled(current_index < total - 1)

        clip_complete = True
        for index, candidate in enumerate(self._current_clip()["candidates"]):
            key = f"{self._current_clip()['clip_id']}:{candidate['code']}"
            record = ratings.get(key, {})
            status = "완료" if self._record_is_complete(record) else (
                "진행 중" if _record_has_progress(record) else "미평가"
            )
            self.candidate_group.button(index).setText(f"{candidate['code']} · {status}")
            clip_complete = clip_complete and self._record_is_complete(record)
        for button in self.winner_group.buttons():
            button.setEnabled(clip_complete)
        self.winner_hint.setText(
            "세 후보 평가 완료 후 선택할 수 있습니다." if not clip_complete else ""
        )

    def _record_is_complete(self, record: object) -> bool:
        if not isinstance(record, Mapping):
            return False
        issues = record.get("issues")
        decisions = record.get("decisions")
        return (
            isinstance(issues, Mapping)
            and all(
                issues.get(question_id) in _ANSWER_VALUES
                for question_id in self.question_ids
            )
            and isinstance(decisions, Mapping)
            and all(
                decisions.get(stage) in _DECISION_VALUES
                for stage in self.decision_stages
            )
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_current_response()
        self._player.stop()
        super().closeEvent(event)


def _segmented_frame() -> tuple[QFrame, QHBoxLayout]:
    frame = QFrame()
    frame.setObjectName("SegmentedControl")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(4)
    return frame, layout


def _stage_specs(review_type: str) -> tuple[tuple[str, str], ...]:
    if review_type == REVIEW_TYPE_CONVERSION:
        return _CONVERSION_STAGES
    if review_type == REVIEW_TYPE_HYBRID:
        return _HYBRID_STAGES
    return _SEPARATION_STAGES


def _question_sections(
    review_type: str,
) -> tuple[
    tuple[str, str, tuple[tuple[str, str], ...], str], ...
]:
    if review_type == REVIEW_TYPE_CONVERSION:
        return (
            (
                "변환 보컬",
                "분리 보컬이 pq-a를 통과한 결과입니다.",
                _CONVERTED_QUESTIONS,
                "converted_vocals",
            ),
            (
                "최종 믹스",
                "변환 보컬과 해당 후보의 반주를 합친 결과입니다.",
                _MIX_QUESTIONS,
                "final_mix",
            ),
        )
    if review_type == REVIEW_TYPE_HYBRID:
        return (
            (
                "최종 믹스",
                "완성곡을 기준으로 평가하고 이상한 부분은 위의 개별 음원으로 확인합니다.",
                _MIX_QUESTIONS,
                "final_mix",
            ),
        )
    return (
        (
            "보컬 결과",
            "보컬을 선택해 듣고 평가합니다.",
            _VOCAL_QUESTIONS,
            "vocals",
        ),
        (
            "반주 결과",
            "반주를 선택해 듣고 평가합니다.",
            _INSTRUMENTAL_QUESTIONS,
            "instrumental",
        ),
    )


def _segment_button(label: str) -> FeedbackButton:
    button = FeedbackButton(label)
    button.setObjectName("SegmentButton")
    button.setCheckable(True)
    return button


def _compact_segment_button(label: str, *, width: int) -> FeedbackButton:
    button = _segment_button(label)
    button.setFixedSize(width, 30)
    button.setStyleSheet(
        f"min-width: {width}px; max-width: {width}px; "
        "min-height: 30px; max-height: 30px; padding: 0;"
    )
    return button


def _set_group_value(
    group: QButtonGroup,
    values: tuple[str, ...],
    value: str,
) -> None:
    group.setExclusive(False)
    try:
        for button in group.buttons():
            with QSignalBlocker(button):
                button.setChecked(False)
        if value in values:
            button = group.button(values.index(value))
            if button is not None:
                with QSignalBlocker(button):
                    button.setChecked(True)
    finally:
        group.setExclusive(True)


def _group_value(group: QButtonGroup, values: tuple[str, ...]) -> str:
    index = group.checkedId()
    return values[index] if 0 <= index < len(values) else ""


def _record_has_progress(record: object) -> bool:
    if not isinstance(record, Mapping):
        return False
    issues = record.get("issues")
    decisions = record.get("decisions")
    return (
        isinstance(issues, Mapping)
        and any(value in _ANSWER_VALUES for value in issues.values())
    ) or (
        isinstance(decisions, Mapping)
        and any(value in _DECISION_VALUES for value in decisions.values())
    ) or bool(str(record.get("notes", "")).strip())
