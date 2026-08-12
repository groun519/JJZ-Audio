from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from jang_app.version import __version__


class StartupSplash(QWidget):
    close_requested = Signal()

    def __init__(self, logo_path: Path) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("StartupSplash")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(720, 400)
        self._progress = 0.04
        self._animation_group: QParallelAnimationGroup | None = None

        self.logo_label = QLabel(self)
        self.logo_label.setGeometry(46, 38, 56, 56)
        self.logo_label.setPixmap(QIcon(str(logo_path)).pixmap(56, 56))

        self.brand_label = QLabel("JJZERO", self)
        self.brand_label.setGeometry(116, 42, 92, 18)
        self.brand_label.setFont(_font(11, QFont.Weight.Bold, 2))
        self.brand_label.setStyleSheet("color: #d6d4cc; background: transparent;")

        self.descriptor_label = QLabel("AUDIO WORKSPACE", self)
        self.descriptor_label.setGeometry(116, 66, 138, 18)
        self.descriptor_label.setFont(_font(9, QFont.Weight.DemiBold, 1))
        self.descriptor_label.setStyleSheet("color: #74736d; background: transparent;")

        self.version_label = QLabel(f"v{__version__}", self)
        self.version_label.setObjectName("SplashVersion")
        self.version_label.setGeometry(222, 40, 66, 22)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setFont(_font(9, QFont.Weight.DemiBold))
        self.version_label.setStyleSheet(
            "color: #aaa8a1; background: #292927; border: 1px solid #3d3c38; "
            "border-radius: 10px; padding-bottom: 1px;"
        )

        self.title_label = QLabel("JJZero Audio", self)
        self.title_label.setGeometry(46, 116, 300, 48)
        self.title_label.setFont(_font(31, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #efeee9; background: transparent;")

        self.subtitle_label = QLabel("Voice, sound, and motion in one workspace.", self)
        self.subtitle_label.setGeometry(48, 167, 300, 24)
        self.subtitle_label.setFont(_font(10, QFont.Weight.Normal))
        self.subtitle_label.setStyleSheet("color: #898780; background: transparent;")

        self.stage_label = QLabel("STARTING", self)
        self.stage_label.setGeometry(48, 304, 520, 18)
        self.stage_label.setFont(_font(9, QFont.Weight.Bold, 1))
        self.stage_label.setStyleSheet("color: #ecebe7; background: transparent;")

        self.detail_label = QLabel("Preparing application", self)
        self.detail_label.setGeometry(48, 326, 590, 28)
        self.detail_label.setFont(_font(10, QFont.Weight.Normal))
        self.detail_label.setStyleSheet("color: #898780; background: transparent;")

        self.close_button = QPushButton("Close", self)
        self.close_button.setGeometry(596, 316, 76, 32)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setStyleSheet(
            "QPushButton { color: #ecebe7; background: #30302e; border: 1px solid #484843; "
            "border-radius: 9px; font-weight: 700; }"
            "QPushButton:hover { background: #3a3a37; }"
            "QPushButton:pressed { background: #444440; }"
        )
        self.close_button.clicked.connect(self.close_requested.emit)
        self.close_button.hide()

    @property
    def progress(self) -> float:
        return self._progress

    def show_centered(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(available.center() - self.rect().center())
        self.show()
        self.raise_()

    def set_stage(self, message: str, progress: float) -> None:
        self.stage_label.setText("LOADING")
        self.detail_label.setText(message.strip())
        self.detail_label.setStyleSheet("color: #898780; background: transparent;")
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def show_error(self, message: str) -> None:
        self.stage_label.setText("STARTUP FAILED")
        self.detail_label.setText(message.strip() or "JJZero Audio could not start.")
        self.detail_label.setStyleSheet("color: #d98b78; background: transparent;")
        self.close_button.show()
        self._progress = 1.0
        self.show_centered()
        self.update()

    def finish(self, main_window: QWidget) -> None:
        self.stage_label.setText("READY")
        self.detail_label.setText("Opening workspace")
        self._progress = 1.0
        self.update()

        main_window.setWindowOpacity(0.0)
        main_window.show()
        self.raise_()

        splash_fade = QPropertyAnimation(self, b"windowOpacity", self)
        splash_fade.setDuration(180)
        splash_fade.setStartValue(1.0)
        splash_fade.setEndValue(0.0)
        splash_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        window_fade = QPropertyAnimation(main_window, b"windowOpacity", self)
        window_fade.setDuration(180)
        window_fade.setStartValue(0.0)
        window_fade.setEndValue(1.0)
        window_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(splash_fade)
        group.addAnimation(window_fade)
        group.finished.connect(lambda: self._complete_transition(main_window))
        self._animation_group = group
        group.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        background = QLinearGradient(outer.topLeft(), outer.bottomRight())
        background.setColorAt(0.0, QColor("#181817"))
        background.setColorAt(0.58, QColor("#1d1d1c"))
        background.setColorAt(1.0, QColor("#252523"))
        painter.setPen(QPen(QColor("#3a3a37"), 1))
        painter.setBrush(background)
        painter.drawRoundedRect(outer, 18, 18)

        painter.setPen(QPen(QColor("#343432"), 1))
        painter.drawLine(352, 30, 352, 286)
        self._draw_audio_field(painter)

        track = QRectF(48, 370, 624, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#343432"))
        painter.drawRoundedRect(track, 1.5, 1.5)
        fill = QRectF(track.left(), track.top(), track.width() * self._progress, track.height())
        painter.setBrush(QColor("#d8d7d1"))
        painter.drawRoundedRect(fill, 1.5, 1.5)

    def _draw_audio_field(self, painter: QPainter) -> None:
        center_y = 163.0
        painter.setPen(QPen(QColor("#3d3d3a"), 1))
        painter.drawLine(382, int(center_y), 680, int(center_y))
        for index in range(54):
            ratio = index / 53
            x = 382 + ratio * 298
            envelope = 0.22 + 0.78 * abs(math.sin(ratio * math.pi * 2.35))
            texture = 0.62 + 0.38 * abs(math.sin(index * 1.73))
            height = 16 + 82 * envelope * texture
            tone = QColor("#77756f" if index % 5 else "#b8b7b1")
            tone.setAlpha(150 if index % 5 else 215)
            painter.setPen(QPen(tone, 1.2))
            painter.drawLine(int(x), int(center_y - height), int(x), int(center_y + height))

        painter.setPen(QPen(QColor("#efeee9"), 2))
        painter.drawLine(536, 72, 536, 254)
        painter.setBrush(QColor("#efeee9"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(532, center_y - 4, 8, 8))

    def _complete_transition(self, main_window: QWidget) -> None:
        main_window.setWindowOpacity(1.0)
        self.hide()
        self._animation_group = None


def _font(pixel_size: int, weight: QFont.Weight, letter_spacing: int = 0) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    if letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return font
