from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.theme import theme_tokens
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.conversion_pitch_recommendation import (
    PitchRangeProfile,
    PitchRecommendation,
)
from jang_app.services.i18n import tr
from jang_app.services.pitch_profile import midi_note_name


class ConversionPitchGuide(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConversionPitchGuide")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme_mode = "white"
        self._state = "hidden"
        self._message_key = ""
        self._recommendation: PitchRecommendation | None = None
        self._current_pitch = 0
        self._expanded = False

        self.title_label = QLabel()
        self.title_label.setObjectName("PitchGuideTitle")
        self.status_label = QLabel()
        self.status_label.setObjectName("PitchGuideStatus")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.toggle_button = SvgIconButton("chevron_down", size=28)
        self.toggle_button.setObjectName("PitchGuideToggleButton")
        self.toggle_button.setCheckable(True)
        self.toggle_button.toggled.connect(self._set_expanded)

        summary = QHBoxLayout()
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(7)
        summary.addWidget(self.title_label)
        summary.addStretch(1)
        summary.addWidget(self.status_label, 1)
        summary.addWidget(self.toggle_button)

        self.range_view = PitchRangeMatchView()
        self.description_label = QLabel()
        self.description_label.setObjectName("PitchGuideDescription")
        self.description_label.setWordWrap(True)

        self.details = QFrame()
        self.details.setObjectName("PitchGuideDetails")
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(0, 4, 0, 0)
        details_layout.setSpacing(4)
        details_layout.addWidget(self.range_view)
        details_layout.addWidget(self.description_label)
        self.details.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(summary)
        layout.addWidget(self.details)

        self.apply_language()
        self.set_theme_mode(self._theme_mode)
        self.clear_context()

    def clear_context(self) -> None:
        self._state = "hidden"
        self._message_key = ""
        self._recommendation = None
        self.range_view.clear_profiles()
        self.hide()

    def set_analyzing(self) -> None:
        self._state = "analyzing"
        self._message_key = "Analyzing vocal range..."
        self._recommendation = None
        self.range_view.clear_profiles()
        self.show()
        self._sync_state()

    def set_unavailable(self, message_key: str) -> None:
        self._state = "unavailable"
        self._message_key = message_key
        self._recommendation = None
        self.range_view.clear_profiles()
        self.show()
        self._sync_state()

    def set_recommendation(
        self,
        recommendation: PitchRecommendation,
        *,
        current_pitch: int,
    ) -> None:
        self._state = "ready"
        self._message_key = ""
        self._recommendation = recommendation
        self._current_pitch = int(current_pitch)
        self.range_view.set_profiles(
            recommendation.source,
            recommendation.model,
            current_pitch=self._current_pitch,
        )
        self.show()
        self._sync_state()

    def set_current_pitch(self, pitch: int) -> None:
        self._current_pitch = int(pitch)
        if self._state == "ready":
            self.range_view.set_current_pitch(self._current_pitch)
            self._sync_state()

    def recommendation(self) -> PitchRecommendation | None:
        return self._recommendation

    def is_expanded(self) -> bool:
        return self._expanded

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.toggle_button.set_theme_mode(theme_mode)
        self.range_view.set_theme_mode(theme_mode)
        self.setStyleSheet(_guide_stylesheet(theme_mode))

    def apply_language(self) -> None:
        self.title_label.setText(tr("Pitch Match"))
        self.toggle_button.setToolTip(tr("Show pitch range details"))
        self.description_label.setText(
            tr(
                "This is a starting value that aligns the main ranges of the input vocal and model."
            )
        )
        self.range_view.apply_language()
        self._sync_state()

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.toggle_button.set_icon_name(
            "chevron_up" if self._expanded else "chevron_down"
        )
        self._sync_state()

    def _sync_state(self) -> None:
        ready = self._state == "ready" and self._recommendation is not None
        if ready:
            assert self._recommendation is not None
            recommendation = self._recommendation
            if recommendation.has_recommended_range:
                assert recommendation.recommended_low_pitch is not None
                assert recommendation.recommended_high_pitch is not None
                range_text = _pitch_range_text(
                    recommendation.recommended_low_pitch,
                    recommendation.recommended_high_pitch,
                )
                in_range = recommendation.contains_pitch(self._current_pitch)
                status_key = (
                    "Recommended {range} · In range"
                    if in_range
                    else "Recommended {range}"
                )
                status = tr(status_key).format(range=range_text)
                explanation = tr(
                    "Any value in this range keeps the input vocal range inside the model range."
                )
                if not in_range:
                    explanation = (
                        f"{explanation} "
                        f"{tr('Current pitch is outside the recommended range.')}"
                    )
            else:
                pitch_text = f"{recommendation.pitch:+d}"
                status = tr("Best fit {pitch} · {overlap}% covered").format(
                    pitch=pitch_text,
                    overlap=round(recommendation.overlap_ratio * 100),
                )
                explanation = tr(
                    "The input vocal range is wider than the model range. This value gives the largest overlap."
                )
            self.status_label.setText(status)
            if recommendation.is_large_shift:
                explanation = (
                    f"{explanation} {tr('A large pitch shift may reduce conversion quality.')}"
                )
            self.status_label.setToolTip(explanation)
            self.description_label.setText(explanation)
        else:
            self.status_label.setText(tr(self._message_key) if self._message_key else "")
            self.status_label.setToolTip(tr(self._message_key) if self._message_key else "")

        self.status_label.setProperty("ready", ready)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.toggle_button.setVisible(ready)
        self.details.setVisible(ready and self._expanded)


class PitchRangeMatchView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PitchRangeMatchView")
        self.setMinimumHeight(88)
        self._theme_mode = "white"
        self._source: PitchRangeProfile | None = None
        self._model: PitchRangeProfile | None = None
        self._current_pitch = 0
        self._input_label = ""
        self._model_label = ""
        self.apply_language()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, 88)

    def set_profiles(
        self,
        source: PitchRangeProfile,
        model: PitchRangeProfile,
        *,
        current_pitch: int = 0,
    ) -> None:
        self._source = source
        self._model = model
        self._current_pitch = int(current_pitch)
        self.update()

    def set_current_pitch(self, pitch: int) -> None:
        self._current_pitch = int(pitch)
        self.update()

    def clear_profiles(self) -> None:
        self._source = None
        self._model = None
        self._current_pitch = 0
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def apply_language(self) -> None:
        self._input_label = tr("Input vocal")
        self._model_label = tr("Selected model")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = theme_tokens(self._theme_mode)
        painter.setPen(QColor(tokens["muted"]))

        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        if self._source is None or self._model is None:
            return

        shifted_source = PitchRangeProfile(
            low_midi=self._source.low_midi + self._current_pitch,
            center_midi=self._source.center_midi + self._current_pitch,
            high_midi=self._source.high_midi + self._current_pitch,
            sample_count=self._source.sample_count,
        )
        axis_low = math.floor(min(shifted_source.low_midi, self._model.low_midi) - 2)
        axis_high = math.ceil(max(shifted_source.high_midi, self._model.high_midi) + 2)
        if axis_high - axis_low < 12:
            padding = 12 - (axis_high - axis_low)
            axis_low -= padding // 2
            axis_high += padding - padding // 2

        label_width = 70.0
        value_width = 52.0
        axis_left = label_width
        axis_right = max(axis_left + 30.0, self.width() - value_width)
        axis_width = axis_right - axis_left

        painter.drawText(QRectF(axis_left, 0, 42, 16), midi_note_name(axis_low))
        painter.drawText(
            QRectF(axis_right - 42, 0, 42, 16),
            Qt.AlignmentFlag.AlignRight,
            midi_note_name(axis_high),
        )

        rows = (
            (self._input_label, shifted_source, 31.0, QColor("#3da98a")),
            (
                self._model_label,
                self._model,
                62.0,
                QColor(tokens["pair_accent"]),
            ),
        )
        for label, profile, center_y, color in rows:
            painter.setPen(QColor(tokens["muted"]))
            painter.drawText(
                QRectF(0, center_y - 9, label_width - 8, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QPen(QColor(tokens["border"]), 2))
            painter.drawLine(
                int(axis_left),
                int(center_y),
                int(axis_right),
                int(center_y),
            )
            left = axis_left + axis_width * (profile.low_midi - axis_low) / (
                axis_high - axis_low
            )
            right = axis_left + axis_width * (profile.high_midi - axis_low) / (
                axis_high - axis_low
            )
            if right - left < 6:
                left -= 3
                right += 3
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(left, center_y - 4, right - left, 8), 4, 4)
            center_x = axis_left + axis_width * (profile.center_midi - axis_low) / (
                axis_high - axis_low
            )
            painter.setBrush(QColor(tokens["text"]))
            painter.drawEllipse(QRectF(center_x - 2, center_y - 2, 4, 4))
            painter.setPen(QColor(tokens["muted"]))
            range_text = f"{midi_note_name(profile.low_midi)}–{midi_note_name(profile.high_midi)}"
            painter.drawText(
                QRectF(axis_right + 7, center_y - 9, value_width - 7, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                range_text,
            )


def _pitch_range_text(low: int, high: int) -> str:
    if low == high:
        return f"{low:+d}"
    return f"{low:+d} ~ {high:+d}"


def _guide_stylesheet(theme_mode: str) -> str:
    tokens = theme_tokens(theme_mode)
    return f"""
        QFrame#ConversionPitchGuide {{
            background: transparent;
            border: none;
            border-top: 1px solid {tokens['border']};
        }}
        QFrame#PitchGuideDetails {{
            background: transparent;
            border: none;
        }}
        QLabel#PitchGuideTitle {{
            color: {tokens['text']};
            font-size: 11px;
            font-weight: 700;
        }}
        QLabel#PitchGuideStatus {{
            color: {tokens['muted']};
            font-size: 10px;
        }}
        QLabel#PitchGuideStatus[ready="true"] {{
            color: {tokens['pair_accent']};
            font-weight: 700;
        }}
        QLabel#PitchGuideDescription {{
            color: {tokens['muted']};
            font-size: 10px;
        }}
    """
