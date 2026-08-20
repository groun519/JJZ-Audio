from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.widgets import ScrollSafeSlider, SvgIconButton
from jang_app.services.i18n import tr
from jang_app.services.studio_zoom import (
    STUDIO_BASE_PIXELS_PER_SECOND,
    STUDIO_MAX_PIXELS_PER_SECOND,
    STUDIO_MIN_PIXELS_PER_SECOND,
    studio_zoom_label,
)


class StudioTransportBar(QFrame):
    play_toggled = Signal()
    seek_requested = Signal(int)
    zoom_changed = Signal(int)
    split_mode_changed = Signal(bool)
    snapping_changed = Signal(bool)
    undo_requested = Signal()
    redo_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StudioTransportBar")
        self.setFixedHeight(56)

        self.transport = TransportControls()
        self.transport.set_shortcut_hint("Space")
        self.transport.play_toggled.connect(self.play_toggled.emit)
        self.transport.seek_requested.connect(self.seek_requested.emit)

        self.zoom_label = QLabel()
        self.zoom_label.setObjectName("StudioTransportToolLabel")
        self.zoom_slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setObjectName("StudioZoomSlider")
        self.zoom_slider.setRange(
            STUDIO_MIN_PIXELS_PER_SECOND,
            STUDIO_MAX_PIXELS_PER_SECOND,
        )
        self.zoom_slider.setValue(STUDIO_BASE_PIXELS_PER_SECOND)
        self.zoom_slider.setFixedWidth(130)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)

        self.split_button = SvgIconButton("split", size=34)
        self.split_button.setObjectName("StudioSplitButton")
        self.split_button.setCheckable(True)
        self.split_button.setEnabled(False)
        self.split_button.toggled.connect(self._on_split_mode_toggled)

        self.snap_button = SvgIconButton("magnet", size=34)
        self.snap_button.setObjectName("StudioSnapButton")
        self.snap_button.setCheckable(True)
        self.snap_button.setChecked(True)
        self.snap_button.toggled.connect(self.snapping_changed.emit)

        self.undo_button = SvgIconButton("undo", size=34)
        self.undo_button.setObjectName("StudioUndoButton")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.redo_button = SvgIconButton("redo", size=34)
        self.redo_button.setObjectName("StudioRedoButton")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self.redo_requested.emit)

        self.split_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.split_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.split_shortcut.activated.connect(self._toggle_split_mode)
        self.exit_split_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.exit_split_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.exit_split_shortcut.activated.connect(self._exit_split_mode)
        self.snap_shortcut = QShortcut(QKeySequence("N"), self)
        self.snap_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.snap_shortcut.activated.connect(self._toggle_snapping)

        transport_divider = _divider()
        zoom_divider = _divider()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)
        layout.addWidget(self.transport, 1)
        layout.addWidget(transport_divider)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addWidget(self.split_button)
        layout.addWidget(self.snap_button)
        layout.addWidget(zoom_divider)
        layout.addWidget(self.zoom_label)
        layout.addWidget(self.zoom_slider)
        self.apply_language()

    def set_queue(self, duration_ms: int) -> None:
        self.transport.set_position(0, duration_ms)

    def clear(self) -> None:
        self.transport.clear()

    def set_playing(self, is_playing: bool) -> None:
        self.transport.set_playing(is_playing)

    def set_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        self.transport.set_position(position_ms, duration_ms)

    def set_zoom(self, value: int) -> None:
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(
            max(self.zoom_slider.minimum(), min(value, self.zoom_slider.maximum()))
        )
        self.zoom_slider.blockSignals(False)
        self._sync_zoom_label()

    def zoom_value(self) -> int:
        return self.zoom_slider.value()

    def set_split_enabled(self, enabled: bool) -> None:
        if not enabled and self.split_button.isChecked():
            self.split_button.setChecked(False)
        self.split_button.setEnabled(enabled)

    def set_split_mode(self, enabled: bool) -> None:
        self.split_button.blockSignals(True)
        self.split_button.setChecked(bool(enabled) and self.split_button.isEnabled())
        self.split_button.blockSignals(False)
        self._sync_split_tooltip()
        self.split_button.update()

    def set_snapping(self, enabled: bool) -> None:
        self.snap_button.blockSignals(True)
        self.snap_button.setChecked(bool(enabled))
        self.snap_button.blockSignals(False)
        self.snap_button.update()

    def set_history_available(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)

    def _toggle_split_mode(self) -> None:
        if self.split_button.isEnabled():
            self.split_button.toggle()

    def _exit_split_mode(self) -> None:
        if self.split_button.isChecked():
            self.split_button.setChecked(False)

    def _on_split_mode_toggled(self, enabled: bool) -> None:
        self._sync_split_tooltip(enabled)
        self.split_mode_changed.emit(enabled)

    def _toggle_snapping(self) -> None:
        if isinstance(
            QApplication.focusWidget(),
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox),
        ):
            return
        self.snap_button.toggle()

    def _on_zoom_changed(self, pixels_per_second: int) -> None:
        self._sync_zoom_label(pixels_per_second)
        self.zoom_changed.emit(pixels_per_second)

    def _sync_zoom_label(self, pixels_per_second: int | None = None) -> None:
        value = (
            self.zoom_slider.value()
            if pixels_per_second is None
            else pixels_per_second
        )
        self.zoom_label.setText(f"{tr('Zoom')}  {studio_zoom_label(value)}")

    def _sync_split_tooltip(self, enabled: bool | None = None) -> None:
        is_active = self.split_button.isChecked() if enabled is None else bool(enabled)
        set_translated_tooltip(
            self.split_button,
            (
                "Cut Tool Active (click or Esc to exit)"
                if is_active
                else "Cut Tool (Ctrl+B, Esc to exit)"
            ),
        )

    def set_theme_mode(self, theme_mode: str) -> None:
        self.transport.set_theme_mode(theme_mode)
        self.split_button.set_theme_mode(theme_mode)
        self.snap_button.set_theme_mode(theme_mode)
        self.undo_button.set_theme_mode(theme_mode)
        self.redo_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.transport.apply_language()
        self._sync_zoom_label()
        set_translated_tooltip(self.undo_button, "Undo Studio edit (Ctrl+Z)")
        set_translated_tooltip(self.redo_button, "Redo Studio edit (Ctrl+Y)")
        set_translated_tooltip(self.snap_button, "Snapping (N, hold Alt to bypass)")
        self._sync_split_tooltip()


def _divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("StudioTransportDivider")
    divider.setFixedSize(1, 26)
    return divider
