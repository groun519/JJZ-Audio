from __future__ import annotations

import atexit
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QValidator, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QLineEdit,
    QSlider,
    QSpinBox,
    QStyle,
    QStyleOptionSlider,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.services.i18n import tr
from jang_app.services.waveform import (
    build_waveform_peaks,
    waveform_cache_key,
    waveform_peak_cache,
)


COMPACT_ICON_BUTTON_SIZE = 26
_WAVEFORM_VIEW_EXECUTOR = ThreadPoolExecutor(
    max_workers=3,
    thread_name_prefix="workspace-waveform",
)
atexit.register(
    lambda: _WAVEFORM_VIEW_EXECUTOR.shutdown(wait=False, cancel_futures=True)
)


class TransparentContainer(QWidget):
    """Layout-only container that must never paint an opaque theme surface."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        object_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("surfaceRole", "transparent")
        if object_name:
            self.setObjectName(object_name)


class SurfaceFrame(QFrame):
    """Explicit theme surface used instead of relying on a global QWidget fill."""

    _ROLES = frozenset(("background", "surface", "card", "raised"))

    def __init__(
        self,
        role: str = "surface",
        parent: QWidget | None = None,
        *,
        object_name: str = "",
    ) -> None:
        if role not in self._ROLES:
            raise ValueError(f"Unsupported surface role: {role}")
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("surfaceRole", role)
        if object_name:
            self.setObjectName(object_name)


def attach_transparent_scroll_widget(
    scroll_area: QScrollArea,
    content: QWidget,
) -> None:
    """Attach layout content without exposing the platform viewport palette."""
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    for widget in (scroll_area, scroll_area.viewport(), content):
        widget.setAutoFillBackground(False)
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setProperty("surfaceRole", "transparent")
    scroll_area.setWidget(content)


def configure_two_line_status_text(
    container: QFrame,
    title: QLabel,
    detail: QLabel,
    *,
    spacing: int,
    detail_lines: int = 2,
) -> None:
    """Keep compact status cards readable when their parent is vertically constrained."""
    title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    detail.setWordWrap(True)
    detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    detail.setMinimumHeight(detail.fontMetrics().lineSpacing() * max(1, detail_lines))
    container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    layout = container.layout()
    if layout is None:
        return
    margins = layout.contentsMargins()
    container.setMinimumHeight(
        margins.top()
        + title.fontMetrics().lineSpacing()
        + spacing
        + detail.minimumHeight()
        + margins.bottom()
    )


class _ScrollSafeControl:
    def wheelEvent(self, event) -> None:  # noqa: N802
        scroll_area = _nearest_scroll_area(self)
        if scroll_area is None:
            event.ignore()
            return

        viewport = scroll_area.viewport()
        local_position = viewport.mapFromGlobal(event.globalPosition().toPoint())
        forwarded_event = QWheelEvent(
            QPointF(local_position),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
        )
        QApplication.sendEvent(viewport, forwarded_event)
        event.accept()


class ScrollSafeComboBox(_ScrollSafeControl, QComboBox):
    pass


class ScrollSafeSlider(_ScrollSafeControl, QSlider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._absolute_drag_active = False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            super().mousePressEvent(event)
            return
        option, handle = self._style_option_and_handle()
        if handle.contains(event.position().toPoint()):
            super().mousePressEvent(event)
            return
        self._absolute_drag_active = True
        self.setSliderDown(True)
        self._move_to_pointer(event.position(), option, handle)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._absolute_drag_active
            and event.buttons() & Qt.MouseButton.LeftButton
            and self.isEnabled()
        ):
            option, handle = self._style_option_and_handle()
            self._move_to_pointer(event.position(), option, handle)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._absolute_drag_active:
            self._absolute_drag_active = False
            if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
                option, handle = self._style_option_and_handle()
                self._move_to_pointer(event.position(), option, handle)
                if not self.hasTracking():
                    self.setValue(self.sliderPosition())
                self.setSliderDown(False)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def _style_option_and_handle(self) -> tuple[QStyleOptionSlider, QRect]:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        return option, handle

    def _move_to_pointer(
        self,
        position: QPointF,
        option: QStyleOptionSlider,
        handle: QRect,
    ) -> None:
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if self.orientation() == Qt.Orientation.Horizontal:
            slider_length = handle.width()
            slider_min = groove.left()
            slider_max = groove.right() - slider_length + 1
            pointer = round(position.x()) - slider_length // 2
        else:
            slider_length = handle.height()
            slider_min = groove.top()
            slider_max = groove.bottom() - slider_length + 1
            pointer = round(position.y()) - slider_length // 2
        span = max(0, slider_max - slider_min)
        slider_position = max(0, min(span, pointer - slider_min))
        value = QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            slider_position,
            span,
            option.upsideDown,
        )
        self.setSliderPosition(value)


class ScrollSafeSpinBox(_ScrollSafeControl, QSpinBox):
    pass


class ScrollSafeDoubleSpinBox(_ScrollSafeControl, QDoubleSpinBox):
    pass


class TimecodeSpinBox(ScrollSafeSpinBox):
    """Millisecond value editor presented as MM:SS.mmm or HH:MM:SS.mmm."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 86_400_000)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def textFromValue(self, value: int) -> str:  # noqa: N802
        total_ms = max(0, int(value))
        milliseconds = total_ms % 1_000
        total_seconds = total_ms // 1_000
        seconds = total_seconds % 60
        total_minutes = total_seconds // 60
        minutes = total_minutes % 60
        hours = total_minutes // 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        return f"{total_minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def valueFromText(self, text: str) -> int:  # noqa: N802
        normalized = text.strip().replace(",", ".")
        if not normalized:
            return 0
        try:
            parts = normalized.split(":")
            if len(parts) == 1:
                return max(0, round(float(parts[0]) * 1_000))
            if len(parts) == 2:
                minutes, seconds = parts
                return max(0, round((int(minutes) * 60 + float(seconds)) * 1_000))
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return max(
                    0,
                    round((int(hours) * 3_600 + int(minutes) * 60 + float(seconds)) * 1_000),
                )
        except ValueError:
            return self.value()
        return self.value()

    def validate(self, text: str, position: int):  # noqa: N802
        normalized = text.strip().replace(",", ".")
        complete = (
            re.fullmatch(r"\d+(?:\.\d{0,3})?", normalized)
            or re.fullmatch(r"\d+:[0-5]\d(?:\.\d{0,3})?", normalized)
            or re.fullmatch(r"\d+:[0-5]\d:[0-5]\d(?:\.\d{0,3})?", normalized)
        )
        if complete and self.minimum() <= self.valueFromText(normalized) <= self.maximum():
            return QValidator.State.Acceptable, text, position
        if not normalized or re.fullmatch(r"[\d:.,]*", normalized):
            return QValidator.State.Intermediate, text, position
        return QValidator.State.Invalid, text, position


class FeedbackButton(QPushButton):
    """Button with pointer feedback that reserves focus chrome for keyboard use."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setProperty("keyboardFocus", False)
        self.setProperty("pointerState", "normal")

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._set_keyboard_focus(event.reason() != Qt.FocusReason.MouseFocusReason)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._set_keyboard_focus(False)
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_keyboard_focus(False)
            focused = QApplication.focusWidget()
            if isinstance(focused, FeedbackButton):
                focused.clearFocus()
            self._set_pointer_state("pressed")
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        is_inside = self.rect().contains(event.position().toPoint())
        self._set_pointer_state("hover" if is_inside and self.isEnabled() else "normal")

    def enterEvent(self, event) -> None:  # noqa: N802
        self._set_pointer_state("pressed" if self.isDown() else "hover")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_pointer_state("normal")
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._set_pointer_state("normal")

    def _set_keyboard_focus(self, is_visible: bool) -> None:
        self._set_visual_property("keyboardFocus", is_visible)

    def _set_pointer_state(self, state: str) -> None:
        self._set_visual_property("pointerState", state)

    def _set_visual_property(self, name: str, value: object) -> None:
        if self.property(name) == value:
            return
        self.setProperty(name, value)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _is_pointer_hovered(self) -> bool:
        return self.property("pointerState") == "hover"

    def _is_pointer_pressed(self) -> bool:
        return self.property("pointerState") == "pressed"

    def _draw_keyboard_focus(self, painter: QPainter, rect: QRectF, radius: float) -> None:
        if not bool(self.property("keyboardFocus")):
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_keyboard_focus_color(getattr(self, "_theme_mode", "white")), 1))
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), max(2.0, radius - 2), max(2.0, radius - 2))


class InfoPopoverButton(FeedbackButton):
    """Compact help button that exposes the same content to pointer and keyboard users."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("i", parent)
        self.setObjectName("InfoPopoverButton")
        self.setFixedSize(18, 18)
        self.setAccessibleName("Information")
        self.clicked.connect(self.show_popover)

    def set_content(
        self,
        title: str,
        body: str,
        recommendation: str = "",
    ) -> None:
        sections = [f"<b>{title.strip()}</b>", body.strip()]
        if recommendation.strip():
            sections.append(recommendation.strip())
        self.setToolTip("<br><br>".join(section for section in sections if section))

    def show_popover(self) -> None:
        if not self.toolTip():
            return
        position = self.mapToGlobal(QPoint(self.width() + 6, self.height() + 2))
        QToolTip.showText(position, self.toolTip(), self)

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.show_popover()

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.show_popover()


def _nearest_scroll_area(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


class WindowTitleBar(QFrame):
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        title: str,
        logo_path: Path,
        *,
        version_text: str = "",
        allow_minimize: bool = True,
        allow_maximize: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName("WindowTitleBar")
        self.setFixedHeight(46)
        self._drag_position: QPoint | None = None

        logo = QLabel()
        logo.setObjectName("AppLogo")
        logo.setFixedSize(28, 28)
        logo.setPixmap(QIcon(str(logo_path)).pixmap(28, 28))

        title_label = QLabel(title)
        title_label.setObjectName("AppTitle")

        self.version_label = QLabel(version_text.strip(), self)
        self.version_label.setObjectName("AppVersion")
        if not self.version_label.text():
            self.version_label.hide()

        brand_text_layout = QHBoxLayout()
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(7)
        brand_text_layout.addWidget(title_label, 0)
        brand_text_layout.addWidget(self.version_label, 0)

        brand_layout = QHBoxLayout()
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(12)
        brand_layout.addWidget(logo, 0)
        brand_layout.addLayout(brand_text_layout, 0)

        self.center_widget = QWidget()
        self.center_widget.setObjectName("TitleBarCenter")
        self.center_layout = QHBoxLayout(self.center_widget)
        self.center_layout.setContentsMargins(0, 0, 0, 0)
        self.center_layout.setSpacing(8)

        self.action_widget = QWidget()
        self.action_widget.setObjectName("TitleBarActions")
        self.action_layout = QHBoxLayout(self.action_widget)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(4)

        self.minimize_button = _window_control_button("minimize", "Minimize")
        self.maximize_button = _window_control_button("maximize", "Maximize")
        self.close_button = _window_control_button("close", "Close")
        self.close_button.setObjectName("WindowCloseButton")
        self.minimize_button.clicked.connect(self.minimize_requested.emit)
        self.maximize_button.clicked.connect(self.maximize_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)

        self.window_control_group = QFrame()
        self.window_control_group.setObjectName("WindowControlGroup")
        compact_controls = not (allow_minimize or allow_maximize)
        self.window_control_group.setProperty("compactControls", compact_controls)
        window_controls = QHBoxLayout(self.window_control_group)
        if compact_controls:
            window_controls.setContentsMargins(0, 0, 0, 0)
        else:
            window_controls.setContentsMargins(5, 2, 5, 2)
        window_controls.setSpacing(2)
        window_controls.addWidget(self.action_widget)
        self.control_divider = _titlebar_control_divider()
        window_controls.addWidget(self.control_divider)
        window_controls.addWidget(self.minimize_button)
        window_controls.addWidget(self.maximize_button)
        window_controls.addWidget(self.close_button)
        self.minimize_button.setVisible(allow_minimize)
        self.maximize_button.setVisible(allow_maximize)
        self.control_divider.setVisible(allow_minimize or allow_maximize)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 10, 6)
        layout.setSpacing(12)
        layout.addLayout(brand_layout, 0)
        layout.addStretch(1)
        layout.addWidget(self.center_widget, 0)
        layout.addStretch(1)
        layout.addWidget(self.window_control_group, 0)

    def add_navigation_widget(self, widget: QWidget) -> None:
        self.center_layout.addWidget(widget)

    def add_action_widget(self, widget: QWidget) -> None:
        self.action_layout.addWidget(widget)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.minimize_button.set_theme_mode(theme_mode)
        self.maximize_button.set_theme_mode(theme_mode)
        self.close_button.set_theme_mode(theme_mode)

    def set_maximized(self, is_maximized: bool) -> None:
        self.maximize_button.set_icon_name("restore" if is_maximized else "maximize")
        set_translated_tooltip(self.maximize_button, "Restore" if is_maximized else "Maximize")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._is_interactive_position(event.position().toPoint())
        ):
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._drag_position = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_position is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._is_interactive_position(event.position().toPoint())
        ):
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _is_interactive_position(self, position: QPoint) -> bool:
        child = self.childAt(position)
        while child is not None:
            if isinstance(child, QPushButton):
                return True
            child = child.parentWidget()
        return False


def _window_control_button(icon_name: str, tooltip: str) -> QPushButton:
    button = SvgIconButton(icon_name, size=26)
    button.setObjectName("WindowControlButton")
    set_translated_tooltip(button, tooltip)
    button.lock_outer_size(30)
    return button


def _titlebar_control_divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("TitleBarControlDivider")
    divider.setFixedSize(1, 16)
    return divider


class FileDropCard(QFrame):
    files_dropped = Signal(object)
    browse_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragging", False)
        self.setMinimumHeight(140)

        self.file_button = SvgIconButton("file_plus", size=58)
        self.file_button.setObjectName("DropFileButton")
        set_translated_tooltip(self.file_button, "Add audio file")
        self.file_button.clicked.connect(self.browse_requested.emit)

        self.selected_label = QLabel("")
        self.selected_label.setObjectName("DropFileName")
        self.selected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_label.setWordWrap(True)
        self.selected_label.hide()

        self.title_label = QLabel("Drop File")
        self.title_label.setObjectName("DropTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(9)
        layout.addStretch(1)
        layout.addWidget(self.file_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.selected_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def set_selected_path(self, path: Path | None) -> None:
        self._set_selected_text(path.name if path else "")

    def set_selected_text(self, text: str) -> None:
        self._set_selected_text(text)

    def set_compact_mode(self, compact: bool) -> None:
        layout = self.layout()
        if compact:
            self.file_button.lock_outer_size(36)
            layout.setContentsMargins(12, 6, 12, 6)
            layout.setSpacing(3)
            return
        self.file_button.lock_outer_size(58)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(9)

    def _set_selected_text(self, text: str) -> None:
        value = text.strip()
        self.selected_label.setText(value)
        self.selected_label.setVisible(bool(value))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _event_has_files(event):
            event.acceptProposedAction()
            self._set_dragging(True)
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _event_has_files(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_dragging(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_dragging(False)
        paths = _paths_from_drop(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
            return
        event.ignore()

    def _set_dragging(self, is_dragging: bool) -> None:
        self.setProperty("dragging", is_dragging)
        self.style().unpolish(self)
        self.style().polish(self)


class UrlDownloadCard(QFrame):
    download_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")

        title = QLabel("YouTube")
        title.setObjectName("CardTitle")

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("YouTube URL")
        self.url_edit.returnPressed.connect(self._emit_download_requested)

        self.download_button = FeedbackButton("Download")
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.clicked.connect(self._emit_download_requested)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()

        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_row.addWidget(self.url_edit, 1)
        input_row.addWidget(self.download_button, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(input_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

    def url(self) -> str:
        return self.url_edit.text().strip()

    def set_running(self, is_running: bool) -> None:
        self.url_edit.setDisabled(is_running)
        self.download_button.setDisabled(is_running)

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, value))
        self.progress_bar.setValue(progress)
        self.progress_bar.setVisible(progress > 0)

    def set_status(self, text: str) -> None:
        value = text.strip()
        set_translated_text(self.status_label, value)
        self.status_label.setToolTip("")
        self.status_label.setVisible(bool(value))

    def set_action_enabled(self, is_enabled: bool) -> None:
        self.download_button.setEnabled(is_enabled)

    def _emit_download_requested(self) -> None:
        self.download_requested.emit(self.url())


class TaskActionWidget(QFrame):
    triggered = Signal()

    def __init__(self, title: str, button_text: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._action_enabled = True
        self._running = False

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.button = FeedbackButton(button_text)
        self.button.setObjectName("PrimaryButton")
        self.button.setMinimumWidth(112)
        self.button.clicked.connect(self.triggered.emit)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setObjectName("ActionProgress")

        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ProgressValue")

        header = QHBoxLayout()
        header.addWidget(self.title_label, 1)
        header.addWidget(self.button, 0)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.percent_label, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addLayout(progress_row)
        layout.addWidget(self.status_label)

    def set_button_text(self, text: str) -> None:
        set_translated_text(self.button, text)

    def set_running(self, is_running: bool) -> None:
        self._running = is_running
        self._sync_button_enabled()

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, value))
        self.progress_bar.setValue(progress)
        self.percent_label.setText(f"{progress}%")

    def set_status(self, text: str) -> None:
        value = text.strip()
        set_translated_text(self.status_label, value)
        self.status_label.setToolTip("")
        self.status_label.setVisible(bool(value))

    def set_action_enabled(self, is_enabled: bool) -> None:
        self._action_enabled = is_enabled
        self._sync_button_enabled()

    def _sync_button_enabled(self) -> None:
        self.button.setEnabled(self._action_enabled and not self._running)


class WaveformView(QWidget):
    seek_requested = Signal(float)
    _peaks_ready = Signal(object, object, str)

    def __init__(self) -> None:
        super().__init__()
        self._path: Path | None = None
        self._peaks: list[float] = []
        self._playhead_ratio = 0.0
        self._muted = False
        self._theme_mode = "white"
        self._error = ""
        self._is_loading = False
        self._cache_key: tuple[str, int, int, int] | None = None
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._peaks_ready.connect(self._apply_loaded_peaks)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self._playhead_ratio = 0.0
        self._error = ""
        self._peaks = []
        self._is_loading = False
        self._cache_key = None
        if path is None:
            self.update()
            return

        try:
            point_count = max(360, self.width() - 36)
            cache_key = waveform_cache_key(path, point_count)
        except Exception as exc:
            self._error = str(exc)
            self.update()
            return

        self._cache_key = cache_key
        cached = waveform_peak_cache.normalized(cache_key)
        if cached is not None:
            self._peaks = cached
            self.update()
            return

        self._is_loading = True
        future = _WAVEFORM_VIEW_EXECUTOR.submit(
            build_waveform_peaks,
            path,
            point_count,
        )
        future.add_done_callback(
            lambda completed, key=cache_key: self._emit_loaded_peaks(key, completed)
        )
        self.update()

    def _emit_loaded_peaks(self, cache_key, completed) -> None:
        error = ""
        try:
            peaks = completed.result()
        except Exception as exc:
            peaks = []
            error = str(exc)
        try:
            self._peaks_ready.emit(cache_key, peaks, error)
        except RuntimeError:
            pass

    def _apply_loaded_peaks(
        self,
        cache_key: tuple[str, int, int, int],
        peaks: list[float],
        error: str,
    ) -> None:
        if cache_key != self._cache_key:
            return
        if peaks:
            waveform_peak_cache.store_normalized(cache_key, peaks)
        self._peaks = peaks
        self._error = error
        self._is_loading = False
        self.update()

    def set_muted(self, is_muted: bool) -> None:
        self._muted = is_muted
        self.update()

    def set_playhead_ratio(self, ratio: float) -> None:
        self._playhead_ratio = _clamp(ratio)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        palette = _waveform_palette(self._theme_mode, self._muted)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.fillRect(outer, palette["background"])
        painter.setPen(QPen(palette["border"], 1))
        painter.drawRect(outer)

        content = outer.adjusted(18, 14, -18, -14)
        center_y = content.center().y()
        painter.setPen(QPen(palette["midline"], 1))
        painter.drawLine(QPointF(content.left(), center_y), QPointF(content.right(), center_y))

        if not self._peaks:
            painter.setPen(QPen(palette["muted"], 1))
            placeholder = self._error or (
                tr("Loading waveform...") if self._is_loading else tr("No waveform loaded")
            )
            painter.drawText(content, Qt.AlignmentFlag.AlignCenter, placeholder)
            return

        painter.setPen(QPen(palette["wave"], 1))
        step = content.width() / max(1, len(self._peaks) - 1)
        max_height = content.height() * 0.46
        for index, peak in enumerate(self._peaks):
            x = content.left() + index * step
            height = max(1.0, peak * max_height)
            painter.drawLine(QPointF(x, center_y - height), QPointF(x, center_y + height))

        head_x = content.left() + content.width() * self._playhead_ratio
        painter.setPen(QPen(palette["playhead"], 2))
        painter.drawLine(QPointF(head_x, content.top()), QPointF(head_x, content.bottom()))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._seek_to_position(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_to_position(event.position().x())

    def _seek_to_position(self, x_position: float) -> None:
        content = QRectF(self.rect()).adjusted(19, 15, -19, -15)
        if content.width() <= 0 or not self._path:
            return
        ratio = _clamp((x_position - content.left()) / content.width())
        self.set_playhead_ratio(ratio)
        self.seek_requested.emit(ratio)


class SvgIconButton(FeedbackButton):
    def __init__(
        self,
        icon_name: str,
        size: int = 26,
        *,
        paint_inset: int = 1,
    ) -> None:
        super().__init__()
        self._icon_name = icon_name
        self._icon_size = size
        self._paint_inset = max(1, int(paint_inset))
        self._theme_mode = "white"
        self.setText("")
        self.setObjectName("SvgIconButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # QSS applies the global 34 px button minimum after construction.
        # Lock icon controls inline so their requested square geometry wins.
        self.lock_outer_size(size)

    def lock_outer_size(self, width: int, height: int | None = None) -> None:
        locked_height = width if height is None else height
        self.setFixedSize(width, locked_height)
        self.setStyleSheet(
            "QPushButton { "
            f"min-width: {width}px; max-width: {width}px; "
            f"min-height: {locked_height}px; max-height: {locked_height}px; "
            "padding: 0; border: 0; margin: 0; }"
        )

    def set_icon_name(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.update()

    def icon_name(self) -> str:
        return self._icon_name

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self._button_palette()

        inset = self._paint_inset
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        background_rect = QRectF(rect)
        if self.objectName() == "WindowCloseButton":
            background_rect.translate(0, -1)
        border = palette.get("border", QColor(0, 0, 0, 0))
        painter.setPen(QPen(border, 1) if border.alpha() else Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(palette["background"]))
        painter.drawRoundedRect(background_rect, 9, 9)
        padding = max(6, int(self._icon_size * 0.25))
        icon_rect = rect.adjusted(padding, padding, -padding, -padding)
        render_app_icon(
            painter,
            icon_rect,
            self._icon_key(),
            palette["icon"],
        )
        self._draw_keyboard_focus(painter, rect, 9)

    def _button_palette(self) -> dict[str, QColor]:
        is_hovered = self._is_pointer_hovered()
        if self.objectName() == "DangerIconButton":
            is_hovered = (
                is_hovered
                or self.property("contextHover") is True
                or self.property("persistentDanger") is True
            )
        return _track_button_palette(
            self._theme_mode,
            self.isChecked(),
            self.isEnabled(),
            is_hovered,
            self._is_pointer_pressed() or self.isDown(),
            self.objectName(),
        )

    def _icon_key(self) -> str:
        if self._icon_name == "speaker":
            return "volume_x" if self.isChecked() else "volume_2"
        if self._icon_name == "folder":
            return "folder"
        if self._icon_name == "download":
            return "download"
        return self._icon_name


class DangerIconButton(SvgIconButton):
    def __init__(
        self,
        size: int = 30,
        *,
        paint_inset: int = 1,
    ) -> None:
        super().__init__("trash", size=size, paint_inset=paint_inset)
        self.setObjectName("DangerIconButton")
        self.setProperty("persistentDanger", True)
        self.lock_outer_size(size)


class ToggleSwitchButton(FeedbackButton):
    """Compact on/off switch without embedding state text in the control."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._theme_mode = "white"
        self.setText("")
        self.setObjectName("ToggleSwitchButton")
        self.setCheckable(True)
        self.setFixedSize(42, 24)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = _toggle_switch_palette(
            self._theme_mode,
            self.isChecked(),
            self.isEnabled(),
            self._is_pointer_hovered(),
            self._is_pointer_pressed() or self.isDown(),
        )
        track = QRectF(self.rect()).adjusted(1.5, 3.5, -1.5, -3.5)
        painter.setPen(QPen(colors["border"], 1))
        painter.setBrush(QBrush(colors["track"]))
        painter.drawRoundedRect(track, 8.5, 8.5)

        diameter = 13.0
        knob_x = (
            track.right() - diameter - 2
            if self.isChecked()
            else track.left() + 2
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colors["knob"]))
        painter.drawEllipse(
            QRectF(knob_x, track.center().y() - diameter / 2, diameter, diameter)
        )
        self._draw_keyboard_focus(painter, QRectF(self.rect()), 10)


class ThemeToggleButton(FeedbackButton):
    def __init__(self) -> None:
        super().__init__()
        self._theme_mode = "white"
        self.setText("")
        self.setObjectName("ThemeToggleButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedSize(66, 26)
        set_translated_tooltip(self, "Switch theme")

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.setChecked(theme_mode == "dark")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = _theme_toggle_palette(
            self._theme_mode,
            self._is_pointer_hovered(),
            self._is_pointer_pressed() or self.isDown(),
        )

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colors["surface"]))
        painter.drawRoundedRect(outer, 10, 10)

        render_app_icon(
            painter,
            QRectF(7, 5, 16, 16),
            "moon" if self.isChecked() else "sun",
            colors["icon"],
        )

        track = QRectF(31, 7, 28, 12)
        painter.setPen(QPen(colors["border"], 1))
        painter.setBrush(QBrush(colors["track"]))
        painter.drawRoundedRect(track, 6, 6)

        knob_x = track.right() - 10 if self.isChecked() else track.left() + 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colors["knob"]))
        painter.drawEllipse(QRectF(knob_x, track.top() + 2, 8, 8))
        self._draw_keyboard_focus(painter, outer, 10)


class TrackMixControl(QFrame):
    settings_changed = Signal()

    def __init__(self, *, compact: bool = False) -> None:
        super().__init__()
        self.setObjectName("TrackMixerStrip")
        self.setFixedHeight(43 if compact else 34)
        self._is_loading = False
        self._compact = compact

        self.mixer_label = QLabel("LEVEL")
        self.mixer_label.setObjectName("TrackMixerLabel")
        self.mixer_label.setFixedWidth(42)
        self.mixer_label.setVisible(not compact)

        self.mute_button = SvgIconButton("speaker", size=26)
        self.mute_button.setObjectName("TrackMuteButton")
        self.mute_button.setCheckable(True)
        set_translated_tooltip(self.mute_button, "Mute this track")
        self.mute_button.clicked.connect(self._on_mute_changed)

        self.volume_slider = VolumeSlider()
        self.volume_slider.setMinimumWidth(42 if compact else 72)
        self.volume_slider.setMaximumWidth(1000 if compact else 180)
        self.volume_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.volume_slider.setRange(0, 200)
        self.volume_slider.setValue(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("VolumeValue")
        self.volume_label.setFixedWidth(38 if compact else 45)
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if compact:
            value_row = QHBoxLayout()
            value_row.setContentsMargins(0, 0, 0, 0)
            value_row.addStretch(1)
            value_row.addWidget(self.volume_label, 0)

            control_row = QHBoxLayout()
            control_row.setContentsMargins(0, 0, 0, 0)
            control_row.setSpacing(5)
            control_row.addWidget(self.mute_button, 0)
            control_row.addWidget(self.volume_slider, 1)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addLayout(value_row, 0)
            layout.addLayout(control_row, 0)
        else:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(10, 4, 10, 4)
            layout.setSpacing(8)
            layout.addStretch(1)
            layout.addWidget(self.mixer_label, 0)
            layout.addWidget(self.mute_button, 0)
            layout.addWidget(self.volume_slider, 1)
            layout.addWidget(self.volume_label, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.mixer_label.setVisible(not self._compact and event.size().width() >= 300)
        super().resizeEvent(event)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.mute_button.set_theme_mode(theme_mode)
        self.volume_slider.set_theme_mode(theme_mode)

    def is_muted(self) -> bool:
        return self.mute_button.isChecked()

    def volume(self) -> float:
        return self.volume_slider.value() / 100

    def volume_percent(self) -> int:
        return self.volume_slider.value()

    def set_mix_state(self, *, muted: bool, volume_percent: int) -> None:
        self._is_loading = True
        self.mute_button.setChecked(muted)
        set_translated_tooltip(
            self.mute_button,
            "Unmute this track" if muted else "Mute this track",
        )
        volume = max(0, min(200, volume_percent))
        self.volume_slider.setValue(volume)
        self.volume_label.setText(f"{volume}%")
        self._is_loading = False

    def set_controls_enabled(self, enabled: bool) -> None:
        self.mute_button.setEnabled(enabled)
        self.volume_slider.setEnabled(enabled)

    def _on_mute_changed(self) -> None:
        set_translated_tooltip(
            self.mute_button,
            "Unmute this track" if self.is_muted() else "Mute this track",
        )
        if not self._is_loading:
            self.settings_changed.emit()

    def _on_volume_changed(self, value: int) -> None:
        self.volume_label.setText(f"{value}%")
        if not self._is_loading:
            self.settings_changed.emit()


class TrackRow(QFrame):
    export_requested = Signal(object)
    open_location_requested = Signal(object)
    seek_requested = Signal(float)
    playback_settings_changed = Signal()
    source_changed = Signal()

    def __init__(self, title: str, allow_selection: bool = False) -> None:
        super().__init__()
        self.setObjectName("TrackCard")
        self._title = title
        self._paths_by_label: dict[str, Path] = {}
        self._theme_mode = "white"
        self._is_loading = False

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")

        self.path_combo = ScrollSafeComboBox()
        self.path_combo.setObjectName("TrackVersionCombo")
        self.path_combo.setMinimumWidth(220)
        self.path_combo.setMaximumWidth(440)
        if not allow_selection:
            self.path_combo.hide()
        self.path_combo.currentIndexChanged.connect(self._on_combo_changed)

        self.open_location_button = SvgIconButton("folder", size=26)
        self.open_location_button.setObjectName("TrackActionButton")
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.open_location_button.clicked.connect(self._emit_open_location_requested)

        self.export_button = SvgIconButton("download", size=26)
        self.export_button.setObjectName("TrackActionButton")
        set_translated_tooltip(self.export_button, "Save a copy of this track")
        self.export_button.clicked.connect(self._emit_export_requested)

        self.mix_control = TrackMixControl()
        self.mix_control.settings_changed.connect(self._on_mix_settings_changed)

        self.waveform = WaveformView()
        self.waveform.seek_requested.connect(self.seek_requested.emit)

        action_group = QFrame()
        action_group.setObjectName("TrackActionGroup")
        action_group.setFixedHeight(32)
        action_layout = QHBoxLayout(action_group)
        action_layout.setContentsMargins(3, 3, 3, 3)
        action_layout.setSpacing(3)
        action_layout.addWidget(self.open_location_button)
        action_layout.addWidget(_track_action_divider())
        action_layout.addWidget(self.export_button)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.path_combo, 1)
        header.addStretch(1)
        header.addWidget(action_group, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.waveform, 1)
        layout.addWidget(self.mix_control, 0)

        self.set_loaded(False)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.waveform.set_theme_mode(theme_mode)
        self.open_location_button.set_theme_mode(theme_mode)
        self.export_button.set_theme_mode(theme_mode)
        self.mix_control.set_theme_mode(theme_mode)

    def set_single_path(self, path: Path | None) -> None:
        self._is_loading = True
        self._paths_by_label = {}
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        self.path_combo.setVisible(False)
        self.path_combo.blockSignals(False)
        self._set_current_path(path)
        self._is_loading = False

    def set_options(self, paths: list[Path], selected_path: Path | None = None) -> None:
        self._is_loading = True
        self._paths_by_label = {_display_name(path): path for path in paths}
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        for label, path in self._paths_by_label.items():
            self.path_combo.addItem(label, str(path))
        self.path_combo.setVisible(len(paths) > 1)
        selected_index = self._path_index(selected_path)
        self.path_combo.setCurrentIndex(selected_index if selected_index >= 0 else (0 if paths else -1))
        self.path_combo.blockSignals(False)
        self._set_current_path(self.current_path())
        self._is_loading = False

    def select_path(self, path: Path | None, *, emit: bool = False) -> bool:
        index = self._path_index(path)
        if index < 0:
            return False
        was_loading = self._is_loading
        self._is_loading = not emit
        was_blocked = self.path_combo.signalsBlocked()
        if not emit:
            self.path_combo.blockSignals(True)
        self.path_combo.setCurrentIndex(index)
        if not emit:
            self.path_combo.blockSignals(was_blocked)
        self._set_current_path(self.current_path())
        self._is_loading = was_loading
        return True

    def current_path(self) -> Path | None:
        if self.path_combo.count() > 0:
            data = self.path_combo.currentData()
            return Path(data) if data else None
        return next(iter(self._paths_by_label.values()), None)

    def is_muted(self) -> bool:
        return self.mix_control.is_muted()

    def volume(self) -> float:
        return self.mix_control.volume()

    def volume_percent(self) -> int:
        return self.mix_control.volume_percent()

    def set_mix_state(self, *, muted: bool, volume_percent: int) -> None:
        self.mix_control.set_mix_state(muted=muted, volume_percent=volume_percent)
        self.waveform.set_muted(muted)

    def set_playhead_ratio(self, ratio: float) -> None:
        self.waveform.set_playhead_ratio(ratio)

    def set_loaded(self, is_loaded: bool) -> None:
        self.open_location_button.setEnabled(is_loaded)
        self.export_button.setEnabled(is_loaded)
        self.mix_control.set_controls_enabled(is_loaded)

    def _set_current_path(self, path: Path | None) -> None:
        if path is None:
            self._paths_by_label = {}
            self.waveform.set_path(None)
            self.path_combo.setToolTip("")
            self.waveform.setToolTip("")
            self.set_loaded(False)
            return

        self._paths_by_label.setdefault(_display_name(path), path)
        self.waveform.set_path(path)
        self.path_combo.setToolTip(str(path))
        self.waveform.setToolTip(str(path))
        self.set_loaded(True)

    def _on_combo_changed(self) -> None:
        self._set_current_path(self.current_path())
        if not self._is_loading:
            self.source_changed.emit()

    def _path_index(self, path: Path | None) -> int:
        if path is None:
            return -1
        resolved = path.expanduser().resolve()
        for index in range(self.path_combo.count()):
            data = self.path_combo.itemData(index)
            if data and Path(data).expanduser().resolve() == resolved:
                return index
        return -1

    def _on_mix_settings_changed(self) -> None:
        self.waveform.set_muted(self.is_muted())
        self._emit_playback_settings_changed()

    def _emit_export_requested(self) -> None:
        path = self.current_path()
        if path is not None:
            self.export_requested.emit(path)

    def _emit_open_location_requested(self) -> None:
        path = self.current_path()
        if path is not None:
            self.open_location_requested.emit(path)

    def _emit_playback_settings_changed(self) -> None:
        if not self._is_loading:
            self.playback_settings_changed.emit()


def attach_list_item_widget(
    list_widget: QListWidget,
    item: QListWidgetItem,
    row: QWidget,
) -> None:
    """Attach a row before measuring it so Qt never treats it as a window."""
    row.setParent(list_widget.viewport())
    item.setSizeHint(row.sizeHint())
    list_widget.addItem(item)
    list_widget.setItemWidget(item, row)


class ValueSlider(ScrollSafeSlider):
    def __init__(
        self,
        *,
        unity_value: int = 0,
        width: int = 180,
        object_name: str = "ValueSlider",
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self._theme_mode = "white"
        self._unity_value = unity_value
        self.setObjectName(object_name)
        self.setFixedWidth(width)
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = _volume_slider_palette(self._theme_mode, self.isEnabled())

        radius = 7
        center_y = self.height() / 2
        left = radius
        right = self.width() - radius
        width = max(1, right - left)
        ratio = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        knob_x = left + width * max(0.0, min(1.0, ratio))

        track = QRectF(left, center_y - 2, width, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(palette["track"]))
        painter.drawRoundedRect(track, 2, 2)

        unity_ratio = (self._unity_value - self.minimum()) / max(1, self.maximum() - self.minimum())
        unity_x = left + width * max(0.0, min(1.0, unity_ratio))
        painter.setPen(QPen(palette["unity"], 1))
        painter.drawLine(QPointF(unity_x, center_y - 5), QPointF(unity_x, center_y + 5))

        fill = QRectF(left, center_y - 2, max(0.0, knob_x - left), 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(palette["fill"]))
        painter.drawRoundedRect(fill, 2, 2)

        knob = QRectF(knob_x - radius, center_y - radius, radius * 2, radius * 2)
        painter.setPen(QPen(palette["knob_border"], 1))
        painter.setBrush(QBrush(palette["knob"]))
        painter.drawEllipse(knob)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._set_value_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self.isEnabled():
            self._set_value_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _set_value_from_x(self, x_position: float) -> None:
        radius = 7
        left = radius
        width = max(1, self.width() - radius * 2)
        ratio = max(0.0, min(1.0, (x_position - left) / width))
        self.setValue(round(self.minimum() + ratio * (self.maximum() - self.minimum())))


class VolumeSlider(ValueSlider):
    def __init__(self) -> None:
        super().__init__(unity_value=100, object_name="TrackVolumeSlider")


def _track_action_divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("TrackActionDivider")
    divider.setFixedSize(1, 16)
    return divider


def _track_button_palette(
    theme_mode: str,
    is_checked: bool,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
    object_name: str = "",
) -> dict[str, QColor]:
    if object_name in {"WindowControlButton", "WindowCloseButton"}:
        return _window_control_palette(theme_mode, object_name, is_enabled, is_hovered, is_pressed)
    if object_name == "DropFileButton":
        return _drop_file_button_palette(theme_mode, is_enabled, is_hovered, is_pressed)
    if object_name in {"EmbeddedActionButton", "VideoOriginalUrlButton"}:
        return _embedded_action_button_palette(theme_mode, is_enabled, is_hovered, is_pressed)
    if object_name in {"TrackActionButton", "TrackMuteButton"}:
        return _track_icon_button_palette(theme_mode, is_checked, is_enabled, is_hovered, is_pressed)
    if object_name == "RowSharedButton":
        return _shared_icon_button_palette(theme_mode, is_enabled, is_hovered, is_pressed)
    if object_name == "DangerIconButton":
        return _danger_icon_button_palette(theme_mode, is_enabled, is_hovered, is_pressed)
    if object_name in {
        "SeparationPairButton",
        "StudioSplitButton",
        "VocalReferenceModeButton",
        "WorkSongRevealButton",
    }:
        return _separation_pair_button_palette(
            theme_mode,
            is_checked,
            is_enabled,
            is_hovered,
            is_pressed,
        )

    if object_name == "StudioSnapButton":
        return _studio_snap_button_palette(
            theme_mode,
            is_checked,
            is_enabled,
            is_hovered,
            is_pressed,
        )

    if object_name in {"DatasetTransportButton", "DatasetFlatIconButton"}:
        return _transport_group_button_palette(
            theme_mode,
            is_checked,
            is_enabled,
            is_hovered,
            is_pressed,
        )

    if theme_mode == "dark":
        colors = {
            "background": QColor(0, 0, 0, 0),
            "hover": QColor("#30302e"),
            "pressed": QColor("#3a3a37"),
            "active": QColor("#30302e"),
            "active_pressed": QColor("#444440"),
            "border": QColor("#484843"),
            "hover_border": QColor("#5a5a55"),
            "icon": QColor("#ecebe7"),
            "active_icon": QColor("#ecebe7"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "background": QColor(0, 0, 0, 0),
            "hover": QColor("#e7e1d5"),
            "pressed": QColor("#d1c8b8"),
            "active": QColor("#10100e"),
            "active_pressed": QColor("#46443e"),
            "border": QColor("#d8d0c2"),
            "hover_border": QColor("#10100e"),
            "icon": QColor("#10100e"),
            "active_icon": QColor("#fffdf7"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {"background": colors["background"], "border": colors["border"], "icon": colors["disabled"]}
    if is_pressed:
        background = colors["active_pressed"] if is_checked else colors["pressed"]
        icon = colors["active_icon"] if is_checked else colors["icon"]
        return {"background": background, "border": background, "icon": icon}
    if is_checked:
        return {"background": colors["active"], "border": colors["active"], "icon": colors["active_icon"]}
    if is_hovered:
        return {"background": colors["hover"], "border": colors["hover_border"], "icon": colors["icon"]}
    return {"background": colors["background"], "border": colors["border"], "icon": colors["icon"]}


def _separation_pair_button_palette(
    theme_mode: str,
    is_checked: bool,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    transparent = QColor(0, 0, 0, 0)
    if theme_mode == "dark":
        colors = {
            "idle": transparent,
            "idle_border": QColor("#484843"),
            "idle_icon": QColor("#aaa8a1"),
            "idle_hover": QColor("#30302e"),
            "active": QColor("#342b18"),
            "active_hover": QColor("#40351d"),
            "active_pressed": QColor("#4a3d21"),
            "active_border": QColor("#8c6d27"),
            "active_icon": QColor("#f2c45c"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "idle": transparent,
            "idle_border": QColor("#d8d0c2"),
            "idle_icon": QColor("#6e6a61"),
            "idle_hover": QColor("#e7e1d5"),
            "active": QColor("#fff1bf"),
            "active_hover": QColor("#f9e6a3"),
            "active_pressed": QColor("#efd27b"),
            "active_border": QColor("#c38d13"),
            "active_icon": QColor("#8a6200"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {
            "background": colors["idle"],
            "border": colors["idle_border"],
            "icon": colors["disabled"],
        }
    if is_checked:
        background = (
            colors["active_pressed"]
            if is_pressed
            else colors["active_hover"]
            if is_hovered
            else colors["active"]
        )
        return {
            "background": background,
            "border": colors["active_border"],
            "icon": colors["active_icon"],
        }
    return {
        "background": colors["idle_hover"] if is_hovered or is_pressed else colors["idle"],
        "border": colors["idle_border"],
        "icon": colors["idle_icon"],
    }


def _studio_snap_button_palette(
    theme_mode: str,
    is_checked: bool,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    transparent = QColor(0, 0, 0, 0)
    if theme_mode == "dark":
        colors = {
            "idle": transparent,
            "idle_border": QColor("#484843"),
            "idle_icon": QColor("#aaa8a1"),
            "idle_hover": QColor("#30302e"),
            "active": QColor("#183a35"),
            "active_hover": QColor("#204941"),
            "active_pressed": QColor("#28564c"),
            "active_border": QColor("#4f8f7d"),
            "active_icon": QColor("#75d9bc"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "idle": transparent,
            "idle_border": QColor("#d8d0c2"),
            "idle_icon": QColor("#6e6a61"),
            "idle_hover": QColor("#e7e1d5"),
            "active": QColor("#dcefe8"),
            "active_hover": QColor("#cbe5dc"),
            "active_pressed": QColor("#b8d9ce"),
            "active_border": QColor("#70a995"),
            "active_icon": QColor("#236b58"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {
            "background": colors["idle"],
            "border": colors["idle_border"],
            "icon": colors["disabled"],
        }
    if is_checked:
        background = (
            colors["active_pressed"]
            if is_pressed
            else colors["active_hover"]
            if is_hovered
            else colors["active"]
        )
        return {
            "background": background,
            "border": colors["active_border"],
            "icon": colors["active_icon"],
        }
    return {
        "background": colors["idle_hover"] if is_hovered or is_pressed else colors["idle"],
        "border": colors["idle_border"],
        "icon": colors["idle_icon"],
    }


def _transport_group_button_palette(
    theme_mode: str,
    is_checked: bool,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    transparent = QColor(0, 0, 0, 0)
    if theme_mode == "dark":
        colors = {
            "hover": QColor("#30302e"),
            "pressed": QColor("#3a3a37"),
            "active": QColor("#ecebe7"),
            "active_icon": QColor("#171717"),
            "icon": QColor("#ecebe7"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "hover": QColor("#e7e1d5"),
            "pressed": QColor("#d1c8b8"),
            "active": QColor("#10100e"),
            "active_icon": QColor("#fffdf7"),
            "icon": QColor("#10100e"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {"background": transparent, "border": transparent, "icon": colors["disabled"]}
    if is_pressed:
        return {
            "background": colors["pressed"],
            "border": transparent,
            "icon": colors["active_icon"] if is_checked else colors["icon"],
        }
    if is_checked:
        return {
            "background": colors["active"],
            "border": transparent,
            "icon": colors["active_icon"],
        }
    if is_hovered:
        return {"background": colors["hover"], "border": transparent, "icon": colors["icon"]}
    return {"background": transparent, "border": transparent, "icon": colors["icon"]}


def _shared_icon_button_palette(
    theme_mode: str,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    transparent = QColor(0, 0, 0, 0)
    if theme_mode == "dark":
        colors = {
            "background": transparent,
            "hover": QColor("#1f3128"),
            "pressed": QColor("#294234"),
            "border": QColor("#3f6b53"),
            "icon": QColor("#b9dfc9"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "background": transparent,
            "hover": QColor("#e2f0e8"),
            "pressed": QColor("#cbe2d5"),
            "border": QColor("#9abda8"),
            "icon": QColor("#24543c"),
            "disabled": QColor("#aaa397"),
        }
    if not is_enabled:
        return {
            "background": colors["background"],
            "border": colors["background"],
            "icon": colors["disabled"],
        }
    if is_pressed:
        return {
            "background": colors["pressed"],
            "border": colors["border"],
            "icon": colors["icon"],
        }
    if is_hovered:
        return {
            "background": colors["hover"],
            "border": colors["border"],
            "icon": colors["icon"],
        }
    return {
        "background": colors["background"],
        "border": colors["background"],
        "icon": colors["icon"],
    }


def _danger_icon_button_palette(
    theme_mode: str,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    transparent = QColor(0, 0, 0, 0)
    if theme_mode == "dark":
        colors = {
            "background": transparent,
            "hover": QColor("#3a2022"),
            "pressed": QColor("#52272a"),
            "border": QColor("#7a3a3f"),
            "icon": QColor("#c77b7b"),
            "active_icon": QColor("#f0b4b4"),
            "disabled_background": QColor("#212120"),
            "disabled_border": QColor("#484843"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "background": transparent,
            "hover": QColor("#f6e4e4"),
            "pressed": QColor("#eccfd0"),
            "border": QColor("#d7a2a5"),
            "icon": QColor("#8a2930"),
            "active_icon": QColor("#8a2930"),
            "disabled_background": QColor("#ebe7dd"),
            "disabled_border": QColor("#d8d0c2"),
            "disabled": QColor("#aaa397"),
        }
    if not is_enabled:
        return {
            "background": colors["disabled_background"],
            "border": colors["disabled_border"],
            "icon": colors["disabled"],
        }
    if is_pressed:
        return {
            "background": colors["pressed"],
            "border": colors["border"],
            "icon": colors["active_icon"],
        }
    if is_hovered:
        return {
            "background": colors["hover"],
            "border": colors["border"],
            "icon": colors["active_icon"],
        }
    return {
        "background": colors["background"],
        "border": colors["background"],
        "icon": colors["icon"],
    }


def danger_icon_button_palette(
    theme_mode: str,
    *,
    is_enabled: bool = True,
    is_hovered: bool = True,
    is_pressed: bool = False,
) -> dict[str, QColor]:
    return _danger_icon_button_palette(
        theme_mode,
        is_enabled,
        is_hovered,
        is_pressed,
    )


def _window_control_palette(
    theme_mode: str,
    object_name: str,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "background": QColor(0, 0, 0, 0),
            "hover": QColor("#30302e"),
            "pressed": QColor("#3a3a37"),
            "icon": QColor("#aaa8a1"),
            "hover_icon": QColor("#ecebe7"),
            "disabled": QColor("#6c6b66"),
            "close_background": QColor("#2d2020"),
            "close_icon": QColor("#d9a0a0"),
        }
    else:
        colors = {
            "background": QColor(0, 0, 0, 0),
            "hover": QColor("#e7e1d5"),
            "pressed": QColor("#d1c8b8"),
            "icon": QColor("#6e6a61"),
            "hover_icon": QColor("#10100e"),
            "disabled": QColor("#aaa397"),
            "close_background": QColor("#f5e5e5"),
            "close_icon": QColor("#8a2930"),
        }

    if not is_enabled:
        return {"background": colors["background"], "border": colors["background"], "icon": colors["disabled"]}
    if object_name == "WindowCloseButton" and is_pressed:
        return {"background": QColor("#9f2929"), "border": QColor("#9f2929"), "icon": QColor("#fffdf7")}
    if object_name == "WindowCloseButton" and is_hovered:
        return {"background": QColor("#c93d3d"), "border": QColor("#c93d3d"), "icon": QColor("#fffdf7")}
    if object_name == "WindowCloseButton":
        return {
            "background": colors["close_background"],
            "border": colors["close_background"],
            "icon": colors["close_icon"],
        }
    if is_pressed:
        return {"background": colors["pressed"], "border": colors["pressed"], "icon": colors["hover_icon"]}
    if is_hovered:
        return {"background": colors["hover"], "border": colors["hover"], "icon": colors["hover_icon"]}
    return {"background": colors["background"], "border": colors["background"], "icon": colors["icon"]}


def _embedded_action_button_palette(
    theme_mode: str,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "background": QColor("#ecebe7"),
            "hover": QColor("#fffdf7"),
            "pressed": QColor("#aaa8a1"),
            "icon": QColor("#10100e"),
            "disabled_background": QColor(0, 0, 0, 0),
            "disabled_border": QColor("#484843"),
            "disabled_icon": QColor("#6c6b66"),
        }
    else:
        colors = {
            "background": QColor("#10100e"),
            "hover": QColor("#292824"),
            "pressed": QColor("#46443e"),
            "icon": QColor("#fffdf7"),
            "disabled_background": QColor(0, 0, 0, 0),
            "disabled_border": QColor("#d8d0c2"),
            "disabled_icon": QColor("#aaa397"),
        }
    if not is_enabled:
        return {
            "background": colors["disabled_background"],
            "border": colors["disabled_border"],
            "icon": colors["disabled_icon"],
        }
    background = colors["pressed"] if is_pressed else colors["hover"] if is_hovered else colors["background"]
    return {"background": background, "border": background, "icon": colors["icon"]}


def _track_icon_button_palette(
    theme_mode: str,
    is_checked: bool,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "background": QColor(0, 0, 0, 0),
            "hover": QColor("#30302e"),
            "pressed": QColor("#3a3a37"),
            "active": QColor("#30302e"),
            "active_pressed": QColor("#444440"),
            "icon": QColor("#ecebe7"),
            "muted_icon": QColor("#ecebe7"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "background": QColor(0, 0, 0, 0),
            "hover": QColor("#e7e1d5"),
            "pressed": QColor("#d1c8b8"),
            "active": QColor("#10100e"),
            "active_pressed": QColor("#46443e"),
            "icon": QColor("#10100e"),
            "muted_icon": QColor("#fffdf7"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {"background": colors["background"], "border": colors["background"], "icon": colors["disabled"]}
    if is_pressed:
        background = colors["active_pressed"] if is_checked else colors["pressed"]
        icon = colors["muted_icon"] if is_checked else colors["icon"]
        return {"background": background, "border": background, "icon": icon}
    if is_checked:
        return {"background": colors["active"], "border": colors["active"], "icon": colors["muted_icon"]}
    if is_hovered:
        return {"background": colors["hover"], "border": colors["hover"], "icon": colors["icon"]}
    return {"background": colors["background"], "border": colors["background"], "icon": colors["icon"]}


def _volume_slider_palette(theme_mode: str, is_enabled: bool) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "track": QColor("#484843"),
            "fill": QColor("#ecebe7"),
            "knob": QColor("#ecebe7"),
            "knob_border": QColor("#212120"),
            "unity": QColor("#898780"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "track": QColor("#d8d0c2"),
            "fill": QColor("#10100e"),
            "knob": QColor("#10100e"),
            "knob_border": QColor("#fffdf7"),
            "unity": QColor("#8e887e"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {
            "track": colors["track"],
            "fill": colors["disabled"],
            "knob": colors["disabled"],
            "knob_border": colors["track"],
            "unity": colors["disabled"],
        }
    return colors


def _drop_file_button_palette(
    theme_mode: str,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "background": QColor("#272725"),
            "hover": QColor("#30302e"),
            "pressed": QColor("#3a3a37"),
            "border": QColor("#484843"),
            "hover_border": QColor("#5a5a55"),
            "icon": QColor("#ecebe7"),
            "hover_icon": QColor("#ecebe7"),
            "disabled": QColor("#6c6b66"),
        }
    else:
        colors = {
            "background": QColor("#fffdf7"),
            "hover": QColor("#10100e"),
            "pressed": QColor("#46443e"),
            "border": QColor("#d8d0c2"),
            "hover_border": QColor("#10100e"),
            "icon": QColor("#10100e"),
            "hover_icon": QColor("#fffdf7"),
            "disabled": QColor("#aaa397"),
        }

    if not is_enabled:
        return {"background": colors["background"], "border": colors["border"], "icon": colors["disabled"]}
    if is_pressed:
        return {"background": colors["pressed"], "border": colors["hover_border"], "icon": colors["hover_icon"]}
    if is_hovered:
        return {"background": colors["hover"], "border": colors["hover_border"], "icon": colors["hover_icon"]}
    return {"background": colors["background"], "border": colors["border"], "icon": colors["icon"]}


def _theme_toggle_palette(theme_mode: str, is_hovered: bool, is_pressed: bool) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "surface": QColor(0, 0, 0, 0),
            "hover_surface": QColor("#30302e"),
            "pressed_surface": QColor("#3a3a37"),
            "track": QColor("#151515"),
            "hover_track": QColor("#272725"),
            "border": QColor("#6c6b66"),
            "knob": QColor("#ecebe7"),
            "icon": QColor("#ecebe7"),
        }
    else:
        colors = {
            "surface": QColor(0, 0, 0, 0),
            "hover_surface": QColor("#e7e1d5"),
            "pressed_surface": QColor("#d1c8b8"),
            "track": QColor("#fffdf7"),
            "hover_track": QColor("#fffdf7"),
            "border": QColor("#d8d0c2"),
            "knob": QColor("#10100e"),
            "icon": QColor("#10100e"),
        }
    return {
        "surface": (
            colors["pressed_surface"]
            if is_pressed
            else colors["hover_surface"] if is_hovered else colors["surface"]
        ),
        "track": colors["hover_track"] if is_hovered else colors["track"],
        "border": colors["border"],
        "knob": colors["knob"],
        "icon": colors["icon"],
    }


def _toggle_switch_palette(
    theme_mode: str,
    is_checked: bool,
    is_enabled: bool,
    is_hovered: bool,
    is_pressed: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        off_track = QColor("#151515")
        off_border = QColor("#5c5b57")
        off_knob = QColor("#aaa8a1")
        on_track = QColor("#3f6b53")
        on_border = QColor("#6e9a7d")
        on_knob = QColor("#ecebe7")
    else:
        off_track = QColor("#ebe7dd")
        off_border = QColor("#aaa397")
        off_knob = QColor("#6e6a61")
        on_track = QColor("#3f6b53")
        on_border = QColor("#315642")
        on_knob = QColor("#fffdf7")

    track = on_track if is_checked else off_track
    border = on_border if is_checked else off_border
    knob = on_knob if is_checked else off_knob
    if not is_enabled:
        track.setAlpha(100)
        border.setAlpha(100)
        knob.setAlpha(120)
    elif is_pressed:
        track = track.lighter(125)
    elif is_hovered:
        border = border.lighter(135)
    return {"track": track, "border": border, "knob": knob}


def _keyboard_focus_color(theme_mode: str) -> QColor:
    return QColor("#898780" if theme_mode == "dark" else "#6e6a61")


def render_app_icon(painter: QPainter, rect: QRectF, icon_key: str, color: QColor) -> None:
    svg_template = _TRACK_ICON_SVGS.get(icon_key, _TRACK_ICON_SVGS["missing"])
    svg = svg_template.replace("{color}", color.name())
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(painter, rect)


_TRACK_ICON_SVGS = {
    "missing": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 9v4"/>'
        '<path d="M12 17h.01"/>'
        '<path d="M10.3 3.9 2.8 17a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
        "</svg>"
    ),
    "minimize": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 12h12"/>'
        "</svg>"
    ),
    "maximize": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 7h10v10H7z"/>'
        "</svg>"
    ),
    "restore": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8 8h9v9H8z"/>'
        '<path d="M6 14H5V5h9v1"/>'
        "</svg>"
    ),
    "close": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 7l10 10"/>'
        '<path d="M17 7 7 17"/>'
        "</svg>"
    ),
    "sun": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3.4"/>'
        '<path d="M12 2.5v2.2"/>'
        '<path d="M12 19.3v2.2"/>'
        '<path d="M4.7 4.7l1.6 1.6"/>'
        '<path d="M17.7 17.7l1.6 1.6"/>'
        '<path d="M2.5 12h2.2"/>'
        '<path d="M19.3 12h2.2"/>'
        '<path d="M4.7 19.3l1.6-1.6"/>'
        '<path d="M17.7 6.3l1.6-1.6"/>'
        "</svg>"
    ),
    "moon": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 15.4A8 8 0 0 1 8.6 4a7 7 0 1 0 11.4 11.4z"/>'
        "</svg>"
    ),
    "settings": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/>'
        "</svg>"
    ),
    "file_plus": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z"/>'
        '<path d="M14 2v5h5"/>'
        '<path d="M12 11v6"/>'
        '<path d="M9 14h6"/>'
        "</svg>"
    ),
    "grid": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4" y="4" width="6" height="6" rx="1"/>'
        '<rect x="14" y="4" width="6" height="6" rx="1"/>'
        '<rect x="4" y="14" width="6" height="6" rx="1"/>'
        '<rect x="14" y="14" width="6" height="6" rx="1"/>'
        "</svg>"
    ),
    "list": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 6h11M9 12h11M9 18h11"/>'
        '<circle cx="5" cy="6" r="1" fill="{color}" stroke="none"/>'
        '<circle cx="5" cy="12" r="1" fill="{color}" stroke="none"/>'
        '<circle cx="5" cy="18" r="1" fill="{color}" stroke="none"/>'
        "</svg>"
    ),
    "edit": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 20h9"/>'
        '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'
        "</svg>"
    ),
    "trash": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 6h18"/>'
        '<path d="M8 6V4h8v2"/>'
        '<path d="M19 6l-1 14H6L5 6"/>'
        '<path d="M10 11v5"/>'
        '<path d="M14 11v5"/>'
        "</svg>"
    ),
    "undo": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 7 4 12l5 5"/>'
        '<path d="M5 12h8a6 6 0 0 1 6 6"/>'
        "</svg>"
    ),
    "redo": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m15 7 5 5-5 5"/>'
        '<path d="M19 12h-8a6 6 0 0 0-6 6"/>'
        "</svg>"
    ),
    "more_horizontal": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="{color}" stroke="none">'
        '<circle cx="5" cy="12" r="1.7"/>'
        '<circle cx="12" cy="12" r="1.7"/>'
        '<circle cx="19" cy="12" r="1.7"/>'
        "</svg>"
    ),
    "repeat": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m17 2 4 4-4 4"/>'
        '<path d="M3 11V9a3 3 0 0 1 3-3h15"/>'
        '<path d="m7 22-4-4 4-4"/>'
        '<path d="M21 13v2a3 3 0 0 1-3 3H3"/>'
        "</svg>"
    ),
    "globe": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M3 12h18"/>'
        '<path d="M12 3a14 14 0 0 1 0 18"/>'
        '<path d="M12 3a14 14 0 0 0 0 18"/>'
        "</svg>"
    ),
    "youtube": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3" y="6" width="18" height="12" rx="4"/>'
        '<path d="m10 9 5 3-5 3z" fill="{color}" stroke="none"/>'
        "</svg>"
    ),
    "link": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.1 1.1"/>'
        '<path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.1-1.1"/>'
        "</svg>"
    ),
    "magnet": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m6 15-4-4 6.5-6.5a7.07 7.07 0 0 1 10 10L12 21l-4-4 '
        '6.5-6.5a1.41 1.41 0 0 0-2-2z"/>'
        '<path d="m5 8 4 4"/>'
        '<path d="m12 15 4 4"/>'
        "</svg>"
    ),
    "cloud_check": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M17.5 18H7a5 5 0 1 1 1.4-9.8A6 6 0 0 1 20 10.5a3.8 3.8 0 0 1-2.5 7.5z"/>'
        '<path d="m9.5 13 1.8 1.8 3.7-3.7"/>'
        "</svg>"
    ),
    "split": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="6" cy="7" r="3"/>'
        '<circle cx="6" cy="17" r="3"/>'
        '<path d="m8.6 8.5 11.4 7"/>'
        '<path d="m8.6 15.5 4-2.5"/>'
        '<path d="m15.2 9.4 4.8-3"/>'
        "</svg>"
    ),
    "range": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 5v14"/>'
        '<path d="M19 5v14"/>'
        '<path d="M8 8h8"/>'
        '<path d="m8 8 2-2"/>'
        '<path d="m8 8 2 2"/>'
        '<path d="m16 8-2-2"/>'
        '<path d="m16 8-2 2"/>'
        "</svg>"
    ),
    "play": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8 5v14l11-7z"/>'
        "</svg>"
    ),
    "stop": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 7h10v10H7z"/>'
        "</svg>"
    ),
    "pause": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8 5h3v14H8z"/>'
        '<path d="M13 5h3v14h-3z"/>'
        "</svg>"
    ),
    "arrow_right": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 12h14"/>'
        '<path d="m13 6 6 6-6 6"/>'
        "</svg>"
    ),
    "arrow_left": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M19 12H5"/>'
        '<path d="m11 6-6 6 6 6"/>'
        "</svg>"
    ),
    "chevron_up": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m7 14 5-5 5 5"/>'
        "</svg>"
    ),
    "chevron_down": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m7 10 5 5 5-5"/>'
        "</svg>"
    ),
    "logs": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 5h14"/>'
        '<path d="M5 12h14"/>'
        '<path d="M5 19h10"/>'
        "</svg>"
    ),
    "database": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
        '<path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
        '<path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'
        "</svg>"
    ),
    "pin": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.1" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m14 4 6 6-3 1-4 4-1 4-7-7 4-1 4-4z"/>'
        '<path d="m9 15-5 5"/>'
        "</svg>"
    ),
    "pin_filled": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m14 4 6 6-3 1-4 4-1 4-7-7 4-1 4-4z" fill="{color}"/>'
        '<path d="m9 15-5 5"/>'
        "</svg>"
    ),
    "model": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="8" y="8" width="8" height="8" rx="2"/>'
        '<path d="M12 3v5M12 16v5M3 12h5M16 12h5"/>'
        '<circle cx="12" cy="3" r="1" fill="{color}" stroke="none"/>'
        '<circle cx="12" cy="21" r="1" fill="{color}" stroke="none"/>'
        '<circle cx="3" cy="12" r="1" fill="{color}" stroke="none"/>'
        '<circle cx="21" cy="12" r="1" fill="{color}" stroke="none"/>'
        "</svg>"
    ),
    "vocal": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 12h2l2-5 3 10 3-12 3 7h3"/>'
        '<path d="M4 20h16" opacity=".45"/>'
        "</svg>"
    ),
    "studio": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 4v16M12 4v16M18 4v16"/>'
        '<path d="M3 9h6M9 15h6M15 8h6"/>'
        '<circle cx="6" cy="9" r="2" fill="{color}" stroke="none"/>'
        '<circle cx="12" cy="15" r="2" fill="{color}" stroke="none"/>'
        '<circle cx="18" cy="8" r="2" fill="{color}" stroke="none"/>'
        "</svg>"
    ),
    "refresh": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 12a9 9 0 0 1-15.5 6.3"/>'
        '<path d="M3 12A9 9 0 0 1 18.5 5.7"/>'
        '<path d="M18 2v4h4"/>'
        '<path d="M6 22v-4H2"/>'
        "</svg>"
    ),
    "folder": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 7.5a2 2 0 0 1 2-2h4.5l2 2H19a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        "</svg>"
    ),
    "download": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<path d="M7 10l5 5 5-5"/>'
        '<path d="M12 15V3"/>'
        "</svg>"
    ),
    "volume_2": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M11 5 6 9H2v6h4l5 4V5z"/>'
        '<path d="M15.5 8.5a5 5 0 0 1 0 7"/>'
        '<path d="M19 5a9 9 0 0 1 0 14"/>'
        "</svg>"
    ),
    "volume_x": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M11 5 6 9H2v6h4l5 4V5z"/>'
        '<path d="m22 9-6 6"/>'
        '<path d="m16 9 6 6"/>'
        "</svg>"
    ),
}


def _event_has_files(event) -> bool:
    return event.mimeData().hasUrls()


def _paths_from_drop(event) -> list[Path]:
    paths: list[Path] = []
    for url in event.mimeData().urls():
        if url.isLocalFile():
            paths.append(Path(url.toLocalFile()))
    return paths


def _display_name(path: Path) -> str:
    return path.stem


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _waveform_palette(theme_mode: str, is_muted: bool) -> dict[str, QColor]:
    if theme_mode == "dark":
        palette = {
            "background": QColor("#191919"),
            "border": QColor("#383835"),
            "midline": QColor("#55544f"),
            "wave": QColor("#deddd8"),
            "playhead": QColor("#efeee9"),
            "muted": QColor("#898780"),
        }
    else:
        palette = {
            "background": QColor("#fffdf7"),
            "border": QColor("#d8d0c2"),
            "midline": QColor("#c2baad"),
            "wave": QColor("#11110f"),
            "playhead": QColor("#11110f"),
            "muted": QColor("#8b857a"),
        }
    if is_muted:
        palette["wave"] = palette["muted"]
        palette["playhead"] = palette["muted"]
    return palette
