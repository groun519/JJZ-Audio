from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.qt_app.widgets import (
    ScrollSafeSlider,
    SurfaceFrame,
    SvgIconButton,
    TransparentContainer,
)


CONTROL_SIZE = 32


class ClipEditorHeader(TransparentContainer):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ClipEditorHeader")

        self.title_label = QLabel("Clip Editor")
        self.title_label.setObjectName("DatasetEditorTitle")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("DatasetEditorMeta")
        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(2)
        identity.addWidget(self.title_label)
        identity.addWidget(self.detail_label)

        self.review_badge = QLabel("UNREVIEWED")
        self.review_badge.setObjectName("DatasetReviewBadge")
        self.review_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.zoom_label = QLabel("1x")
        self.zoom_label.setObjectName("DatasetEditorMeta")
        self.zoom_label.setFixedWidth(28)
        self.zoom_slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setObjectName("DatasetZoomSlider")
        self.zoom_slider.setRange(1, 12)
        self.zoom_slider.setValue(1)
        self.zoom_slider.setFixedWidth(140)

        self.navigation_group = QFrame()
        self.navigation_group.setObjectName("DatasetHeaderNavigation")
        navigation_layout = QHBoxLayout(self.navigation_group)
        navigation_layout.setContentsMargins(8, 2, 2, 2)
        navigation_layout.setSpacing(2)
        self.navigation_label = QLabel("-- / --")
        self.navigation_label.setObjectName("DatasetNavigationPosition")
        self.previous_button = _icon_button("arrow_left", "Previous training audio")
        self.previous_button.setObjectName("DatasetFlatIconButton")
        self.next_button = _icon_button("arrow_right", "Next training audio")
        self.next_button.setObjectName("DatasetFlatIconButton")
        navigation_layout.addWidget(self.navigation_label)
        navigation_layout.addWidget(self.previous_button)
        navigation_layout.addWidget(self.next_button)

        self.close_button = _icon_button("close", "Close editor")
        self.close_button.setObjectName("DatasetFlatIconButton")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(identity)
        layout.addWidget(self.review_badge)
        layout.addStretch(1)
        zoom_title = QLabel("ZOOM")
        zoom_title.setObjectName("DatasetAnalysisLabel")
        layout.addWidget(zoom_title)
        layout.addWidget(self.zoom_slider)
        layout.addWidget(self.zoom_label)
        layout.addWidget(_divider())
        layout.addWidget(self.navigation_group)
        layout.addWidget(self.close_button)

    def set_navigation(
        self,
        has_previous: bool,
        has_next: bool,
        current_number: int = 0,
        total_count: int = 0,
    ) -> None:
        self.previous_button.setEnabled(has_previous)
        self.next_button.setEnabled(has_next)
        self.navigation_label.setText(
            f"{current_number} / {total_count}"
            if current_number > 0 and total_count > 0
            else "-- / --"
        )

    def set_theme_mode(self, theme_mode: str) -> None:
        for button in (self.previous_button, self.next_button, self.close_button):
            button.set_theme_mode(theme_mode)


class ClipCommandBar(SurfaceFrame):
    def __init__(
        self,
        *,
        play_button: SvgIconButton,
        loop_button: SvgIconButton,
        position_label: QLabel,
        selection_label: QLabel,
        action_stack: QStackedWidget,
        review_actions: QWidget,
        ready_button: QWidget,
        split_button: SvgIconButton,
        more_button: SvgIconButton,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("surface", parent)
        self.setObjectName("DatasetCommandBar")

        playback_group = QFrame()
        playback_group.setObjectName("DatasetPlaybackGroup")
        playback_layout = QHBoxLayout(playback_group)
        playback_layout.setContentsMargins(2, 2, 2, 2)
        playback_layout.setSpacing(4)
        playback_layout.addWidget(play_button)
        self.play_shortcut_badge = QLabel("SPACE")
        self.play_shortcut_badge.setObjectName("DatasetShortcutKey")
        self.play_shortcut_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_translated_tooltip(
            self.play_shortcut_badge,
            "Preview selection (Space)",
        )
        playback_layout.addWidget(self.play_shortcut_badge)
        playback_layout.addWidget(loop_button)

        timing_group = QFrame()
        timing_group.setObjectName("DatasetTimingGroup")
        timing_layout = QHBoxLayout(timing_group)
        timing_layout.setContentsMargins(10, 0, 10, 0)
        timing_layout.setSpacing(8)
        timing_layout.addWidget(position_label)
        timing_layout.addWidget(_divider(14))
        timing_layout.addWidget(selection_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(7)
        layout.addWidget(playback_group)
        layout.addWidget(timing_group)
        layout.addWidget(action_stack)
        layout.addWidget(split_button)
        layout.addWidget(more_button)
        layout.addWidget(_divider())
        layout.addWidget(review_actions)
        layout.addWidget(_divider())
        layout.addWidget(ready_button)
        layout.addStretch(1)


def _icon_button(icon: str, tooltip: str) -> SvgIconButton:
    button = SvgIconButton(icon, size=CONTROL_SIZE)
    button.setObjectName("DatasetEditorIconButton")
    set_translated_tooltip(button, tooltip)
    return button


def _divider(height: int = 18) -> QFrame:
    divider = QFrame()
    divider.setObjectName("DatasetEditorDivider")
    divider.setFixedSize(1, height)
    return divider
