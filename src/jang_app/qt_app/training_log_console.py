from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_placeholder
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.i18n import tr


_MAX_VISIBLE_LINES = 3_000


@dataclass(frozen=True)
class TrainingLogLine:
    text: str
    category: str


class _TrainingLogHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self._formats = {
            "progress": _text_format("#72b59e"),
            "warning": _text_format("#d6ab4d"),
            "error": _text_format("#ef6c63"),
        }

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        line_format = self._formats.get(_classify_line(text))
        if line_format is not None:
            self.setFormat(0, len(text), line_format)


class TrainingLogConsole(QFrame):
    open_folder_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TrainingLogConsole")
        self.setMinimumHeight(170)
        self._lines: deque[TrainingLogLine] = deque(maxlen=_MAX_VISIBLE_LINES)
        self._pending: list[TrainingLogLine] = []
        self._new_line_count = 0
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(150)
        self._flush_timer.timeout.connect(self._flush_pending)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title_label = QLabel("Live Training Log")
        self.title_label.setObjectName("TrainingLogTitle")
        self.new_lines_label = QLabel()
        self.new_lines_label.setObjectName("TrainingLogNewLines")
        self.new_lines_label.hide()
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("TrainingLogFilter")
        self.filter_combo.addItem("All", "all")
        self.filter_combo.addItem("Progress", "progress")
        self.filter_combo.addItem("Warnings", "warning")
        self.filter_combo.addItem("Errors", "error")
        self.filter_combo.currentIndexChanged.connect(self._rebuild_visible_text)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("TrainingLogSearch")
        self.search_edit.setClearButtonEnabled(True)
        set_translated_placeholder(self.search_edit, "Search log")
        self.search_edit.textChanged.connect(self._rebuild_visible_text)
        self.auto_scroll_button = FeedbackButton("Auto Scroll")
        self.auto_scroll_button.setObjectName("TrainingLogToggleButton")
        self.auto_scroll_button.setCheckable(True)
        self.auto_scroll_button.setChecked(True)
        self.auto_scroll_button.toggled.connect(self._on_auto_scroll_changed)
        self.copy_button = FeedbackButton("Copy")
        self.copy_button.setObjectName("TrainingLogActionButton")
        self.copy_button.clicked.connect(self.copy_visible_log)
        self.open_button = FeedbackButton("Open Log Folder")
        self.open_button.setObjectName("TrainingLogActionButton")
        self.open_button.clicked.connect(self.open_folder_requested.emit)
        header.addWidget(self.title_label)
        header.addWidget(self.new_lines_label)
        header.addStretch(1)
        header.addWidget(self.filter_combo)
        header.addWidget(self.search_edit)
        header.addWidget(self.auto_scroll_button)
        header.addWidget(self.copy_button)
        header.addWidget(self.open_button)
        layout.addLayout(header)

        self.output = QPlainTextEdit()
        self.output.setObjectName("TrainingLogOutput")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.document().setMaximumBlockCount(_MAX_VISIBLE_LINES)
        self._highlighter = _TrainingLogHighlighter(self.output.document())
        self.output.verticalScrollBar().sliderPressed.connect(self._pause_auto_scroll)
        layout.addWidget(self.output, 1)

    def begin(self, model_title: str) -> None:
        self.clear()
        self.append_system(tr("Training started for {model}", model=model_title))

    def clear(self) -> None:
        self._lines.clear()
        self._pending.clear()
        self._new_line_count = 0
        self._flush_timer.stop()
        self.output.clear()
        self._sync_new_line_label()

    def append_batch(self, text: str) -> None:
        for raw_line in str(text).splitlines():
            line = raw_line.rstrip()
            if line:
                self._pending.append(TrainingLogLine(line, _classify_line(line)))
        if self._pending and not self._flush_timer.isActive():
            self._flush_timer.start()

    def append_system(self, text: str) -> None:
        line = str(text).strip()
        if not line:
            return
        self._pending.append(TrainingLogLine(f"[JJZero] {line}", "progress"))
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def copy_visible_log(self) -> None:
        QApplication.clipboard().setText(self.output.toPlainText())
        original = self.copy_button.text()
        self.copy_button.setText(tr("Copied"))
        QTimer.singleShot(1_600, lambda: self.copy_button.setText(original))

    def apply_language(self) -> None:
        current = self.filter_combo.currentData()
        labels = (
            ("All", "all"),
            ("Progress", "progress"),
            ("Warnings", "warning"),
            ("Errors", "error"),
        )
        for index, (label, data) in enumerate(labels):
            self.filter_combo.setItemText(index, tr(label))
            self.filter_combo.setItemData(index, data)
        match = self.filter_combo.findData(current)
        if match >= 0:
            self.filter_combo.setCurrentIndex(match)
        set_translated_placeholder(self.search_edit, "Search log")
        apply_widget_language(self)
        self._sync_new_line_label()

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        pending = tuple(self._pending)
        self._pending.clear()
        self._lines.extend(pending)
        visible = tuple(line for line in pending if self._line_is_visible(line))
        if not visible:
            return
        if self.search_edit.text().strip() or self.filter_combo.currentData() != "all":
            self._rebuild_visible_text()
            return
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText("\n".join(line.text for line in visible) + "\n")
        if self.auto_scroll_button.isChecked():
            self._scroll_to_end()
        else:
            self._new_line_count += len(visible)
            self._sync_new_line_label()

    def _rebuild_visible_text(self) -> None:
        visible = "\n".join(
            line.text for line in self._lines if self._line_is_visible(line)
        )
        self.output.setPlainText(visible)
        if self.auto_scroll_button.isChecked():
            self._scroll_to_end()

    def _line_is_visible(self, line: TrainingLogLine) -> bool:
        selected = self.filter_combo.currentData() or "all"
        if selected != "all" and line.category != selected:
            return False
        query = self.search_edit.text().strip().casefold()
        return not query or query in line.text.casefold()

    def _pause_auto_scroll(self) -> None:
        self.auto_scroll_button.setChecked(False)

    def _on_auto_scroll_changed(self, enabled: bool) -> None:
        if enabled:
            self._new_line_count = 0
            self._sync_new_line_label()
            self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _sync_new_line_label(self) -> None:
        self.new_lines_label.setVisible(self._new_line_count > 0)
        if self._new_line_count > 0:
            self.new_lines_label.setText(
                tr("{count} new lines", count=self._new_line_count)
            )


def _classify_line(line: str) -> str:
    lowered = line.casefold()
    if any(
        marker in lowered
        for marker in (
            "traceback",
            "exception",
            "error",
            "failed",
            "out of memory",
            "not available",
        )
    ):
        return "error"
    if any(
        marker in lowered
        for marker in ("warning", "warn", "fallback", "excluded", "retry")
    ):
        return "warning"
    if any(
        marker in lowered
        for marker in (
            "epoch",
            "progress",
            "preprocess",
            "extract",
            "saving",
            "building",
            "jjzero",
        )
    ):
        return "progress"
    return "output"


def _text_format(color: str) -> QTextCharFormat:
    text_format = QTextCharFormat()
    text_format.setForeground(QColor(color))
    return text_format
