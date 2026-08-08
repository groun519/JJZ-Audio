from __future__ import annotations

import math
from collections.abc import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import (
    FeedbackButton,
    SurfaceFrame,
    TransparentContainer,
    attach_list_item_widget,
)
from jang_app.qt_app.workers import TaskWorker
from jang_app.services.audio_metadata import format_duration
from jang_app.services.i18n import tr
from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.model_dataset_analysis import (
    DatasetAnalysisIssue,
    ModelDatasetAnalysis,
    PitchCoverageRange,
    PitchHistogramBin,
    analyze_model_dataset,
    load_cached_model_dataset_analysis,
    midi_note_name,
    recommended_pitch_shift,
)

_MALE_VOCAL_REFERENCE = (40, 72)
_FEMALE_VOCAL_REFERENCE = (53, 84)


class ModelDatasetAnalysisPanel(QWidget):
    edit_requested = Signal(str, str, int, int)

    def __init__(self, store: ModelDatasetStore) -> None:
        super().__init__()
        self._store = store
        self._model_id = ""
        self._report: ModelDatasetAnalysis | None = None
        self._worker: TaskWorker | None = None
        self._stale = False
        self._theme_mode = "white"
        self._build_ui()
        self.set_model(None)

    def _build_ui(self) -> None:
        self.analyze_button = FeedbackButton("Analyze Materials")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(self.analyze)
        self.status_label = QLabel("")
        self.status_label.setObjectName("DatasetAnalysisStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.status_label, 1)
        header.addWidget(self.analyze_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DatasetAnalysisProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()

        metrics = QHBoxLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(10)
        duration_card, self.duration_value = _metric_card("Usable Duration", self)
        pitch_card, self.pitch_value = _metric_card("Model Center", self)
        active_card, self.active_value = _metric_card("Voice Activity", self)
        issue_card, self.issue_value = _metric_card("Needs Attention", self)
        metrics.addWidget(duration_card, 1)
        metrics.addWidget(pitch_card, 1)
        metrics.addWidget(active_card, 1)
        metrics.addWidget(issue_card, 1)

        pitch_panel = SurfaceFrame("raised", self)
        pitch_panel.setObjectName("DatasetAnalysisSection")
        pitch_layout = QVBoxLayout(pitch_panel)
        pitch_layout.setContentsMargins(16, 14, 16, 14)
        pitch_layout.setSpacing(10)
        pitch_title = QLabel("Model Pitch Profile")
        pitch_title.setObjectName("DatasetAnalysisSectionTitle")
        self.pitch_summary = QLabel("")
        self.pitch_summary.setObjectName("DatasetAnalysisMeta")
        self.pitch_reference = QLabel("")
        self.pitch_reference.setObjectName("DatasetAnalysisMeta")
        self.pitch_chart = PitchHistogramView()
        pitch_layout.addWidget(pitch_title)
        pitch_layout.addWidget(self.pitch_summary)
        pitch_layout.addWidget(self.pitch_reference)
        pitch_layout.addWidget(self.pitch_chart, 1)

        quality_panel = SurfaceFrame("raised", self)
        quality_panel.setObjectName("DatasetAnalysisSection")
        quality_layout = QVBoxLayout(quality_panel)
        quality_layout.setContentsMargins(16, 14, 16, 14)
        quality_layout.setSpacing(0)
        quality_title = QLabel("Signal Overview")
        quality_title.setObjectName("DatasetAnalysisSectionTitle")
        quality_layout.addWidget(quality_title)
        self.level_row = _quality_row("Average Level", quality_panel)
        self.noise_row = _quality_row("Noise Contrast", quality_panel)
        self.clipping_row = _quality_row("Clipping", quality_panel)
        self.ready_row = _quality_row("Material Ready", quality_panel)
        for row in (self.level_row, self.noise_row, self.clipping_row, self.ready_row):
            quality_layout.addWidget(row)
        quality_layout.addStretch(1)

        overview = QHBoxLayout()
        overview.setContentsMargins(0, 0, 0, 0)
        overview.setSpacing(10)
        overview.addWidget(pitch_panel, 2)
        overview.addWidget(quality_panel, 1)

        issues_panel = SurfaceFrame("raised", self)
        issues_panel.setObjectName("DatasetAnalysisSection")
        issues_layout = QVBoxLayout(issues_panel)
        issues_layout.setContentsMargins(16, 14, 16, 14)
        issues_layout.setSpacing(10)
        issue_heading = QHBoxLayout()
        issue_title = QLabel("Review Items")
        issue_title.setObjectName("DatasetAnalysisSectionTitle")
        self.issue_count_label = QLabel("0")
        self.issue_count_label.setObjectName("DatasetCountBadge")
        self.issue_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        issue_heading.addWidget(issue_title)
        issue_heading.addWidget(self.issue_count_label)
        issue_heading.addStretch(1)
        self.issue_list = QListWidget()
        self.issue_list.setObjectName("DatasetIssueList")
        self.issue_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.issue_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.issue_list.setSpacing(4)
        self.issue_list.itemActivated.connect(self._open_issue)
        self.issue_list.itemClicked.connect(self._open_issue)
        issues_layout.addLayout(issue_heading)
        issues_layout.addWidget(self.issue_list)

        content = TransparentContainer(self, object_name="DatasetAnalysisContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addLayout(header)
        content_layout.addWidget(self.progress_bar)
        content_layout.addLayout(metrics)
        content_layout.addLayout(overview)
        content_layout.addWidget(issues_panel)

        scroll = QScrollArea(self)
        scroll.setObjectName("DatasetAnalysisScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def set_model(self, model_id: str | None) -> None:
        self._model_id = model_id or ""
        self._report = (
            load_cached_model_dataset_analysis(self._store, self._model_id)
            if self._model_id
            else None
        )
        self._stale = bool(self._model_id)
        self._render()
        self.analyze_button.setEnabled(bool(self._model_id) and self._worker is None)
        if self._report is not None:
            self._set_status("Checking material changes is recommended.")
        elif self._model_id:
            self._set_status("Run analysis to inspect the selected training material.")
        else:
            self._set_status("")

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.pitch_chart.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._render()

    def ensure_analysis(self) -> None:
        if self._model_id and self._worker is None and (self._report is None or self._stale):
            self.analyze()

    def mark_stale(self) -> None:
        if not self._model_id:
            return
        self._stale = True
        self._set_status("Training material changed. Analyze again to refresh the statistics.")

    def analyze(self) -> None:
        if not self._model_id or self._worker is not None:
            return
        model_id = self._model_id
        worker = TaskWorker(
            lambda progress: analyze_model_dataset(
                self._store,
                model_id,
                progress=progress,
            )
        )
        worker.setParent(self)
        worker.progress_changed.connect(self.progress_bar.setValue)
        worker.succeeded.connect(self._analysis_succeeded)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(self._analysis_finished)
        self._worker = worker
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.analyze_button.setEnabled(False)
        self._set_status("Analyzing training material...")
        worker.start()

    def _analysis_succeeded(self, result: object) -> None:
        if not isinstance(result, ModelDatasetAnalysis) or result.model_id != self._model_id:
            return
        self._report = result
        self._stale = False
        self._render()
        self._set_status(
            "{analyzed} assets analyzed  /  {cached} reused",
            analyzed=result.asset_count,
            cached=result.cached_asset_count,
        )

    def _analysis_failed(self, traceback_text: str) -> None:
        self._set_status(f"Analysis failed: {_last_error_line(traceback_text)}")

    def _analysis_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self.progress_bar.hide()
        self.analyze_button.setEnabled(bool(self._model_id))
        if worker is not None:
            worker.deleteLater()

    def _render(self) -> None:
        report = self._report
        if report is None:
            for label in (
                self.duration_value,
                self.pitch_value,
                self.active_value,
                self.issue_value,
            ):
                label.setText("-")
            self.pitch_summary.setText(tr("No analysis yet"))
            self.pitch_reference.setText(
                tr("Top scale: RVC Pitch required to align an input note with the model center")
            )
            self.pitch_chart.set_profile((), None, ())
            for row in (self.level_row, self.noise_row, self.clipping_row, self.ready_row):
                row.set_value("-")
            self._populate_issues(())
            return

        self.duration_value.setText(format_duration(report.duration_ms))
        self.pitch_value.setText(midi_note_name(report.pitch_center_midi))
        self.active_value.setText(f"{report.active_ratio * 100:.0f}%")
        self.issue_value.setText(str(report.attention_count))
        self.pitch_summary.setText(_coverage_summary(report.pitch_coverage_ranges))
        self.pitch_reference.setText(
            tr("Top scale: RVC Pitch required to align an input note with the model center")
        )
        self.pitch_chart.set_profile(
            report.pitch_histogram,
            report.pitch_center_midi,
            report.pitch_coverage_ranges,
        )
        self.level_row.set_value(f"{report.rms_db:.1f} dBFS")
        self.noise_row.set_value(
            f"{report.signal_contrast_db:.1f} dB"
            if report.signal_contrast_db is not None
            else tr("No quiet reference")
        )
        self.clipping_row.set_value(f"{report.clipping_ratio * 100:.3f}%")
        self.ready_row.set_value(f"{report.ready_item_count} / {report.selected_item_count}")
        self._populate_issues(report.issues)

    def _populate_issues(self, issues: Iterable[DatasetAnalysisIssue]) -> None:
        self.issue_list.clear()
        issue_items = tuple(issues)
        self.issue_count_label.setText(str(len(issue_items)))
        if not issue_items:
            empty = QListWidgetItem(tr("No review items found"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setSizeHint(QRectF(0, 0, 0, 58).size().toSize())
            self.issue_list.addItem(empty)
            return
        for issue in issue_items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, issue)
            row = DatasetIssueRow(issue, self.issue_list.viewport())
            if not issue.item_id:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            attach_list_item_widget(self.issue_list, item, row)

    def _open_issue(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(issue, DatasetAnalysisIssue) and issue.item_id:
            self.edit_requested.emit(
                issue.item_id,
                issue.clip_id,
                issue.start_ms,
                issue.end_ms,
            )

    def _set_status(self, source: str, **values: object) -> None:
        set_translated_text(self.status_label, source, **values)
        self.status_label.setVisible(bool(source))


class PitchHistogramView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._bins: tuple[PitchHistogramBin, ...] = ()
        self._center_midi: float | None = None
        self._coverage_ranges: tuple[PitchCoverageRange, ...] = ()
        self._theme_mode = "white"
        self.setObjectName("PitchHistogram")
        self.setMinimumHeight(230)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_profile(
        self,
        bins: Iterable[PitchHistogramBin],
        center_midi: float | None,
        coverage_ranges: Iterable[PitchCoverageRange],
    ) -> None:
        self._bins = tuple(bins)
        self._center_midi = center_midi
        self._coverage_ranges = tuple(coverage_ranges)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(12, 8, -12, -24)
        palette = self.palette()
        muted = palette.color(QPalette.ColorRole.Mid)
        text = palette.color(QPalette.ColorRole.PlaceholderText)
        bar_color = QColor("#efeee9" if self._theme_mode == "dark" else "#171714")
        center_color = QColor("#e59a63" if self._theme_mode == "dark" else "#ad4f1f")
        low_midi, high_midi = self._pitch_bounds()
        pitch_axis = QRectF(rect.left(), rect.top(), rect.width(), 22)
        female_lane = QRectF(rect.left(), pitch_axis.bottom() + 4, rect.width(), 18)
        male_lane = QRectF(rect.left(), female_lane.bottom() + 4, rect.width(), 18)
        histogram = QRectF(
            rect.left(),
            male_lane.bottom() + 10,
            rect.width(),
            max(20.0, rect.bottom() - male_lane.bottom() - 10),
        )
        self._paint_pitch_axis(painter, pitch_axis, low_midi, high_midi, text)
        self._paint_reference_lane(
            painter,
            female_lane,
            _FEMALE_VOCAL_REFERENCE,
            tr("Typical female song range"),
            QColor("#a98771"),
            low_midi,
            high_midi,
        )
        self._paint_reference_lane(
            painter,
            male_lane,
            _MALE_VOCAL_REFERENCE,
            tr("Typical male song range"),
            QColor("#758b9b"),
            low_midi,
            high_midi,
        )
        self._paint_coverage(
            painter,
            histogram,
            low_midi,
            high_midi,
            center_color,
        )
        painter.setPen(muted)
        painter.drawLine(histogram.bottomLeft(), histogram.bottomRight())
        if not self._bins:
            painter.setPen(text)
            painter.drawText(histogram, Qt.AlignmentFlag.AlignCenter, tr("No stable pitch data"))
            self._paint_note_axis(painter, histogram, low_midi, high_midi, text)
            return
        maximum = max(1, max(item.count for item in self._bins))
        slot = histogram.width() / max(1, high_midi - low_midi + 1)
        bar_width = max(2.0, slot * 0.62)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bar_color)
        for item in self._bins:
            height = histogram.height() * item.count / maximum
            x = self._note_x(
                item.midi_note,
                histogram,
                low_midi,
                high_midi,
            ) - bar_width / 2
            painter.drawRoundedRect(
                QRectF(x, histogram.bottom() - height, bar_width, height),
                min(3.0, bar_width / 2),
                min(3.0, bar_width / 2),
            )
        if self._center_midi is not None:
            center_x = self._note_x(
                self._center_midi,
                histogram,
                low_midi,
                high_midi,
            )
            painter.setPen(center_color)
            painter.drawLine(
                QPointF(center_x, histogram.top()),
                QPointF(center_x, histogram.bottom()),
            )
            painter.setBrush(center_color)
            painter.drawEllipse(QPointF(center_x, histogram.top() + 3), 3.5, 3.5)
        self._paint_note_axis(painter, histogram, low_midi, high_midi, text)

    def _pitch_bounds(self) -> tuple[int, int]:
        values = [36, 84, *_MALE_VOCAL_REFERENCE, *_FEMALE_VOCAL_REFERENCE]
        values.extend(item.midi_note for item in self._bins)
        low = math.floor(min(values) / 12) * 12
        high = math.ceil(max(values) / 12) * 12
        return low, max(low + 12, high)

    def _paint_pitch_axis(
        self,
        painter: QPainter,
        rect: QRectF,
        low_midi: int,
        high_midi: int,
        color: QColor,
    ) -> None:
        painter.setPen(color)
        if self._center_midi is None:
            return
        center_note = round(self._center_midi)
        for octave_offset in range(-6, 7):
            note = center_note + octave_offset * 12
            if not low_midi <= note <= high_midi:
                continue
            x = self._note_x(note, rect, low_midi, high_midi)
            shift = recommended_pitch_shift(self._center_midi, note)
            label = "0" if shift == 0 else f"{shift:+d}"
            painter.drawText(
                QRectF(x - 24, rect.top(), 48, rect.height()),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _paint_reference_lane(
        self,
        painter: QPainter,
        lane: QRectF,
        note_range: tuple[int, int],
        label: str,
        color: QColor,
        low_midi: int,
        high_midi: int,
    ) -> None:
        left = self._note_x(note_range[0], lane, low_midi, high_midi)
        right = self._note_x(note_range[1], lane, low_midi, high_midi)
        band = QRectF(left, lane.top(), max(2.0, right - left), lane.height())
        fill = QColor(color)
        fill.setAlpha(72 if self._theme_mode == "dark" else 46)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(band, 5, 5)
        painter.setPen(color)
        painter.drawText(band, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_coverage(
        self,
        painter: QPainter,
        rect: QRectF,
        low_midi: int,
        high_midi: int,
        center_color: QColor,
    ) -> None:
        for index, note_range in enumerate(self._coverage_ranges):
            left = self._note_x(note_range.low_midi - 0.5, rect, low_midi, high_midi)
            right = self._note_x(note_range.high_midi + 0.5, rect, low_midi, high_midi)
            fill = QColor(center_color if index == 0 else "#8b837b")
            fill.setAlpha(34 if index == 0 else 22)
            painter.fillRect(
                QRectF(left, rect.top(), max(2.0, right - left), rect.height()),
                fill,
            )

    def _paint_note_axis(
        self,
        painter: QPainter,
        rect: QRectF,
        low_midi: int,
        high_midi: int,
        color: QColor,
    ) -> None:
        painter.setPen(color)
        for note in range(math.ceil(low_midi / 12) * 12, high_midi + 1, 12):
            x = self._note_x(note, rect, low_midi, high_midi)
            painter.drawText(
                QRectF(x - 24, rect.bottom() + 4, 48, 18),
                Qt.AlignmentFlag.AlignCenter,
                midi_note_name(note),
            )

    @staticmethod
    def _note_x(
        note: float,
        rect: QRectF,
        low_midi: int,
        high_midi: int,
    ) -> float:
        ratio = (note - low_midi) / max(1, high_midi - low_midi)
        return rect.left() + max(0.0, min(1.0, ratio)) * rect.width()


class DatasetIssueRow(QWidget):
    def __init__(
        self,
        issue: DatasetAnalysisIssue,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DatasetIssueRow")
        self.setProperty("severity", issue.severity)

        title = QLabel(tr(issue.message), self)
        title.setObjectName("DatasetIssueTitle")
        title.setWordWrap(True)
        detail = QLabel(_issue_detail(issue), self)
        detail.setObjectName("DatasetAnalysisMeta")
        detail.setVisible(bool(detail.text()))
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        text.addWidget(title)
        text.addWidget(detail)

        badge = QLabel(
            tr("Attention" if issue.severity == "attention" else "Info"),
            self,
        )
        badge.setObjectName("DatasetIssueBadge")
        badge.setProperty("severity", issue.severity)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 10, 9)
        layout.setSpacing(10)
        layout.addLayout(text, 1)
        layout.addWidget(badge)


class _QualityRow(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DatasetQualityRow")
        self.label = QLabel(label)
        self.label.setObjectName("DatasetAnalysisMeta")
        self.value = QLabel("-")
        self.value.setObjectName("DatasetQualityValue")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 11, 0, 11)
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


def _metric_card(
    caption: str,
    parent: QWidget | None = None,
) -> tuple[QFrame, QLabel]:
    card = SurfaceFrame("raised", parent)
    card.setObjectName("DatasetAnalysisMetric")
    caption_label = QLabel(caption)
    caption_label.setObjectName("DatasetAnalysisMetricLabel")
    value_label = QLabel("-")
    value_label.setObjectName("DatasetAnalysisMetricValue")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(5)
    layout.addWidget(caption_label)
    layout.addWidget(value_label)
    return card, value_label


def _quality_row(label: str, parent: QWidget | None = None) -> _QualityRow:
    return _QualityRow(label, parent)


def _coverage_summary(ranges: tuple[PitchCoverageRange, ...]) -> str:
    if not ranges:
        return tr("No reliable range")
    primary = _coverage_range_text(ranges[0])
    secondary = ", ".join(_coverage_range_text(item) for item in ranges[1:])
    if not secondary:
        return tr("Primary range {range}", range=primary)
    return tr(
        "Primary range {primary}  /  Secondary range {secondary}",
        primary=primary,
        secondary=secondary,
    )


def _coverage_range_text(note_range: PitchCoverageRange) -> str:
    return f"{midi_note_name(note_range.low_midi)} - {midi_note_name(note_range.high_midi)}"


def _issue_detail(issue: DatasetAnalysisIssue) -> str:
    if not issue.source_name:
        return ""
    if issue.end_ms <= issue.start_ms:
        return issue.source_name
    return f"{issue.source_name}  /  {format_duration(issue.start_ms)} - {format_duration(issue.end_ms)}"


def _last_error_line(value: object) -> str:
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    return lines[-1] if lines else tr("Unknown error")
