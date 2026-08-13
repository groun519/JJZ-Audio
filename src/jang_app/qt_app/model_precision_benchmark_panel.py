from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton, SurfaceFrame, TransparentContainer
from jang_app.services.i18n import tr
from jang_app.services.job_diagnostics import diagnostic_task
from jang_app.services.model_precision_benchmark import (
    ModelPrecisionBenchmarkError,
    ModelPrecisionBenchmark,
    ModelPrecisionBenchmarkPoint,
    benchmark_range_label,
    benchmark_shift_label,
    load_cached_model_precision_benchmark,
    run_model_precision_benchmark,
)
from jang_app.services.rvc_model_workspace import RvcModelRecord


BenchmarkTask = Callable[[Callable[[int, int, str], None]], object]


class ModelPrecisionBenchmarkWorker(QThread):
    progress_changed = Signal(int)
    stage_changed = Signal(str)
    detail_changed = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: BenchmarkTask) -> None:
        super().__init__()
        self._task = task
        self._diagnostic_task_id = ""

    def set_diagnostic_task_id(self, task_id: str) -> None:
        self._diagnostic_task_id = task_id

    def run(self) -> None:
        with diagnostic_task(self._diagnostic_task_id):
            try:
                self.succeeded.emit(self._task(self._emit_progress))
            except Exception:
                self.failed.emit(traceback.format_exc())

    def _emit_progress(self, completed: int, total: int, label: str) -> None:
        total_jobs = max(1, int(total))
        done = max(0, min(total_jobs, int(completed)))
        self.progress_changed.emit(round(done * 100 / total_jobs))
        self.detail_changed.emit(f"{done} / {total_jobs}")
        self.stage_changed.emit(label)


class ModelPrecisionBenchmarkPanel(QWidget):
    benchmark_started = Signal(str, str)
    benchmark_progress_reported = Signal(int, str)
    benchmark_completed = Signal(str, str)
    benchmark_failed_reported = Signal(str, str, str)
    benchmark_finished_reported = Signal(str, str)

    def __init__(self, workspace_root: Path, execution_runtime_root: Path) -> None:
        super().__init__()
        self._workspace_root = workspace_root.expanduser().resolve()
        self._execution_runtime_root = execution_runtime_root.expanduser().resolve()
        self._record: RvcModelRecord | None = None
        self._report: ModelPrecisionBenchmark | None = None
        self._worker: ModelPrecisionBenchmarkWorker | None = None
        self._progress_stage_text = ""
        self._progress_detail_text = ""
        self._active_model_id = ""
        self._active_model_title = ""
        self._theme_mode = "white"
        self._build_ui()
        self.set_model(None)

    def _build_ui(self) -> None:
        self.run_button = FeedbackButton("Run Precise Evaluation")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.run_benchmark)

        self.status_label = QLabel("")
        self.status_label.setObjectName("DatasetAnalysisStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.status_label, 1)
        header.addWidget(self.run_button)

        self.scope_label = QLabel("")
        self.scope_label.setObjectName("DatasetAnalysisMeta")
        self.scope_label.setWordWrap(True)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DatasetAnalysisProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.progress_detail = QLabel("")
        self.progress_detail.setObjectName("DatasetAnalysisStatus")
        self.progress_detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_detail.hide()
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_detail)

        metrics = QHBoxLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(10)
        best_card, self.best_shift_value = _metric_card("Stability Center")
        recommended_card, self.recommended_value = _metric_card("Clean Range")
        usable_card, self.usable_value = _metric_card("Usable Range")
        stable_card, self.stable_value = _metric_card("Stable Steps")
        metrics.addWidget(best_card, 1)
        metrics.addWidget(recommended_card, 1)
        metrics.addWidget(usable_card, 1)
        metrics.addWidget(stable_card, 1)

        chart_panel = SurfaceFrame("raised", self)
        chart_panel.setObjectName("DatasetAnalysisSection")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(16, 14, 16, 14)
        chart_layout.setSpacing(10)
        chart_title = QLabel("Pitch Shift Stability")
        chart_title.setObjectName("DatasetAnalysisSectionTitle")
        self.chart_summary = QLabel("")
        self.chart_summary.setObjectName("DatasetAnalysisMeta")
        self.chart_view = PrecisionBenchmarkChartView()
        chart_layout.addWidget(chart_title)
        chart_layout.addWidget(self.chart_summary)
        chart_layout.addWidget(self.chart_view, 1)

        info_panel = SurfaceFrame("raised", self)
        info_panel.setObjectName("DatasetAnalysisSection")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_layout.setSpacing(10)
        info_title = QLabel("How to Read")
        info_title.setObjectName("DatasetAnalysisSectionTitle")
        self.benchmark_meta = QLabel("")
        self.benchmark_meta.setObjectName("DatasetAnalysisMeta")
        self.note_container = TransparentContainer(self, object_name="ModelBenchmarkNotes")
        self.note_layout = QVBoxLayout(self.note_container)
        self.note_layout.setContentsMargins(0, 0, 0, 0)
        self.note_layout.setSpacing(8)
        info_layout.addWidget(info_title)
        info_layout.addWidget(self.benchmark_meta)
        info_layout.addWidget(self.note_container)
        info_layout.addStretch(1)

        content = TransparentContainer(self, object_name="ModelPrecisionBenchmarkContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addLayout(header)
        content_layout.addWidget(self.scope_label)
        content_layout.addLayout(progress_row)
        content_layout.addLayout(metrics)
        content_layout.addWidget(chart_panel)
        content_layout.addWidget(info_panel)

        scroll = QScrollArea(self)
        scroll.setObjectName("DatasetAnalysisScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def set_model(self, record: RvcModelRecord | None) -> None:
        self._record = record
        self._report = (
            load_cached_model_precision_benchmark(self._workspace_root, record)
            if record is not None and record.can_convert
            else None
        )
        self._render()
        self.run_button.setEnabled(
            record is not None
            and record.can_convert
            and self._execution_runtime_root.is_dir()
            and self._worker is None
        )
        if record is None:
            self._set_status("")
        elif not record.can_convert:
            self._set_status("Add an inference checkpoint to use precise evaluation.")
        elif not self._execution_runtime_root.is_dir():
            self._set_status("Select a valid RVC runtime folder before running precise evaluation.")
        elif self._report is not None:
            self._set_status("Latest precise evaluation loaded.")
        else:
            self._set_status("Run precise evaluation to measure the usable pitch shift range.")

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.chart_view.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._render()

    def run_benchmark(self) -> None:
        record = self._record
        if record is None or not record.can_convert or self._worker is not None:
            return
        if not self._execution_runtime_root.is_dir():
            self._set_status("Select a valid RVC runtime folder before running precise evaluation.")
            return
        worker = ModelPrecisionBenchmarkWorker(
            lambda progress: run_model_precision_benchmark(
                self._workspace_root,
                record,
                progress=progress,
                execution_runtime_root=self._execution_runtime_root,
            )
        )
        worker.setParent(self)
        worker.progress_changed.connect(self._handle_progress_changed)
        worker.stage_changed.connect(self._handle_stage_changed)
        worker.detail_changed.connect(self._handle_detail_changed)
        worker.succeeded.connect(self._benchmark_succeeded)
        worker.failed.connect(self._benchmark_failed)
        worker.finished.connect(self._benchmark_finished)
        self._worker = worker
        self._progress_stage_text = tr("Preparing precise evaluation...")
        self._progress_detail_text = ""
        self._active_model_id = record.model_id
        self._active_model_title = record.title
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.progress_detail.setText("0 / 0")
        self.progress_detail.show()
        self.run_button.setEnabled(False)
        self._set_status("Preparing precise evaluation...")
        self.benchmark_started.emit(record.model_id, record.title)
        self._emit_benchmark_progress(0)
        worker.start()

    def _benchmark_succeeded(self, result: object) -> None:
        if not isinstance(result, ModelPrecisionBenchmark):
            return
        model_id = self._active_model_id or result.model_id
        model_title = self._active_model_title or (
            self._record.title if self._record is not None else result.model_id
        )
        self.benchmark_completed.emit(model_id, model_title)
        if self._record is None or result.model_id != self._record.model_id:
            return
        self._report = result
        self._render()
        self._set_status("Precise evaluation completed.")

    def _benchmark_failed(self, traceback_text: str) -> None:
        self._set_status(f"Evaluation failed: {_format_benchmark_error(traceback_text)}")
        model_id = self._active_model_id or (self._record.model_id if self._record is not None else "")
        model_title = self._active_model_title or (self._record.title if self._record is not None else "")
        if model_id:
            self.benchmark_failed_reported.emit(model_id, model_title, traceback_text)

    def _benchmark_finished(self) -> None:
        worker = self._worker
        model_id = self._active_model_id
        model_title = self._active_model_title
        self._worker = None
        self.progress_bar.hide()
        self.progress_detail.hide()
        self.run_button.setEnabled(
            self._record is not None
            and self._record.can_convert
            and self._execution_runtime_root.is_dir()
        )
        self._active_model_id = ""
        self._active_model_title = ""
        if model_id:
            self.benchmark_finished_reported.emit(model_id, model_title)
        if worker is not None:
            worker.deleteLater()

    def assign_diagnostic_task_id(self, task_id: str) -> None:
        if self._worker is not None:
            self._worker.set_diagnostic_task_id(task_id)

    def _handle_progress_changed(self, value: int) -> None:
        self.progress_bar.setValue(value)
        self._emit_benchmark_progress(value)

    def _handle_stage_changed(self, stage: str) -> None:
        if stage == "complete":
            self._progress_stage_text = tr("Precise evaluation completed.")
            self._set_status("Precise evaluation completed.")
            self._emit_benchmark_progress(self.progress_bar.value())
            return
        self._progress_stage_text = tr("Running precise evaluation: {stage}", stage=stage)
        self._set_status("Running precise evaluation: {stage}", stage=stage)
        self._emit_benchmark_progress(self.progress_bar.value())

    def _handle_detail_changed(self, detail: str) -> None:
        self._progress_detail_text = detail
        self.progress_detail.setText(detail)
        self._emit_benchmark_progress(self.progress_bar.value())

    def _emit_benchmark_progress(self, progress: int) -> None:
        detail = self._progress_stage_text or tr("Preparing precise evaluation...")
        if self._progress_detail_text:
            detail = f"{detail}  |  {self._progress_detail_text}"
        self.benchmark_progress_reported.emit(progress, detail)

    def _render(self) -> None:
        report = self._report
        if report is None:
            for label in (
                self.best_shift_value,
                self.recommended_value,
                self.usable_value,
                self.stable_value,
            ):
                label.setText("-")
            self.scope_label.setText(
                tr("This page measures model-level pitch-shift stability. It does not calculate song-specific pitch.")
            )
            self.chart_summary.setText(tr("Use one precise benchmark to test this model on every pitch shift."))
            self.benchmark_meta.setText(
                tr("3 built-in reference vocals  /  -24 to +24 semitones  /  1-semitone steps")
            )
            self.chart_view.set_points(())
            _reset_note_layout(self.note_layout)
            _add_note(self.note_layout, "The benchmark uses the same reference vocal for every model.")
            _add_note(self.note_layout, "The result shows which pitch shifts stay stable with this checkpoint.")
            _add_note(self.note_layout, "Compare this with training material analysis to see the model's recorded range.")
            return

        self.scope_label.setText(
            tr("This page measures model-level pitch-shift stability. It does not calculate song-specific pitch.")
        )
        self.best_shift_value.setText(benchmark_shift_label(report.best_shift_semitones))
        self.recommended_value.setText(
            benchmark_range_label(report.recommended_low_shift, report.recommended_high_shift)
        )
        self.usable_value.setText(
            benchmark_range_label(report.usable_low_shift, report.usable_high_shift)
        )
        self.stable_value.setText(f"{report.stable_point_count} / {len(report.points)}")
        self.chart_summary.setText(
            tr(
                "{success} of {total} pitch-shift renders completed  /  {failed} unstable",
                success=report.successful_jobs,
                total=report.total_jobs,
                failed=report.failed_jobs,
            )
        )
        self.benchmark_meta.setText(
            tr(
                "{references} reference vocals  /  model stability benchmark  /  version {version}",
                references=report.reference_count,
                version=report.benchmark_version,
            )
        )
        self.chart_view.set_points(report.points)
        _reset_note_layout(self.note_layout)
        for note in report.notes:
            _add_note(self.note_layout, note)

    def _set_status(self, template: str, **values: object) -> None:
        set_translated_text(self.status_label, template, **values)


class PrecisionBenchmarkChartView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PitchHistogram")
        self._points: tuple[ModelPrecisionBenchmarkPoint, ...] = ()
        self._theme_mode = "white"
        self.setMinimumHeight(220)

    def set_points(self, points: tuple[ModelPrecisionBenchmarkPoint, ...]) -> None:
        self._points = points
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        chart_rect = self.rect().adjusted(14, 14, -14, -26)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return

        if not self._points:
            painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("No precise evaluation data"))
            return

        baseline = chart_rect.bottom()
        text_pen = self.palette().color(QPalette.ColorRole.Text)
        faint_pen = self.palette().color(QPalette.ColorRole.Mid)
        painter.setPen(QPen(faint_pen, 1))
        painter.drawLine(chart_rect.left(), baseline, chart_rect.right(), baseline)

        bar_gap = 4.0
        total_gap = bar_gap * (len(self._points) - 1)
        bar_width = max(6.0, (chart_rect.width() - total_gap) / len(self._points))
        label_y = self.rect().bottom() - 6
        zero_x = 0.0

        for index, point in enumerate(self._points):
            left = chart_rect.left() + index * (bar_width + bar_gap)
            height = 12.0 + ((chart_rect.height() - 22.0) * point.score / 100.0)
            top = baseline - height
            rect = QRectF(left, top, bar_width, height)
            painter.setBrush(_status_color(point.status, self._theme_mode))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 3.0, 3.0)
            if point.shift_semitones == 0:
                zero_x = rect.center().x()
            if point.shift_semitones % 6 == 0:
                painter.setPen(text_pen)
                painter.drawText(
                    QRectF(left - 10.0, label_y - 12.0, bar_width + 20.0, 16.0),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    f"{point.shift_semitones:+d}",
                )
        painter.setPen(QPen(QColor("#f1d18a" if self._theme_mode == "dark" else "#a36a12"), 1.5))
        painter.drawLine(QPointF(zero_x, chart_rect.top()), QPointF(zero_x, baseline))


def _metric_card(label: str) -> tuple[QFrame, QLabel]:
    card = SurfaceFrame("raised")
    card.setObjectName("DatasetAnalysisMetric")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(4)
    title = QLabel(label)
    title.setObjectName("DatasetAnalysisMetricLabel")
    value = QLabel("-")
    value.setObjectName("DatasetAnalysisMetricValue")
    layout.addWidget(title)
    layout.addWidget(value)
    return card, value


def _add_note(layout: QVBoxLayout, text: str) -> None:
    label = QLabel(tr(text))
    label.setObjectName("DatasetAnalysisMeta")
    label.setWordWrap(True)
    layout.addWidget(label)


def _reset_note_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _status_color(status: str, theme_mode: str) -> QColor:
    if status == "stable":
        return QColor("#48b48d" if theme_mode == "dark" else "#2c8d6d")
    if status == "caution":
        return QColor("#c99a4f" if theme_mode == "dark" else "#b5781c")
    return QColor("#53575e" if theme_mode == "dark" else "#8e939b")


def _last_error_line(traceback_text: str) -> str:
    lines = [line.strip() for line in traceback_text.splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"


def _format_benchmark_error(traceback_text: str) -> str:
    line = _last_error_line(traceback_text)
    if "The selected RVC runtime root does not exist." in line:
        return tr("The selected RVC runtime folder could not be found.")
    if "This model does not have an inference checkpoint." in line:
        return tr("This model needs an inference checkpoint before precise evaluation can run.")
    if "The selected model did not produce a usable benchmark render." in line:
        return tr("The model could not produce a usable benchmark result.")
    if "The selected model could not complete the benchmark conversion." in line:
        return tr("Benchmark conversion stopped before any stable result was produced.")
    if ":" in line:
        return line.split(":", 1)[1].strip()
    return line
