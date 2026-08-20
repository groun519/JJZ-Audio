from __future__ import annotations

import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.model_precision_benchmark_views import (
    BenchmarkNoteRangeView,
    PrecisionBenchmarkNoteChart,
    benchmark_note_label,
    benchmark_note_range_label,
    benchmark_shift_range_label,
)
from jang_app.qt_app.widgets import FeedbackButton, SurfaceFrame, TransparentContainer
from jang_app.services.i18n import tr
from jang_app.services.job_diagnostics import diagnostic_task
from jang_app.services.model_precision_benchmark import (
    ModelPrecisionBenchmark,
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
        self._narrow_layout = False
        self._build_ui()
        self.set_model(None)

    def _build_ui(self) -> None:
        self.run_button = FeedbackButton("Run Precise Evaluation")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.run_benchmark)

        self.status_label = QLabel("")
        self.status_label.setObjectName("ModelBenchmarkStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.generated_label = QLabel("")
        self.generated_label.setObjectName("ModelBenchmarkGenerated")
        self.generated_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(9)
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.generated_label)
        status_row.addStretch(1)

        self.headline_label = QLabel("")
        self.headline_label.setObjectName("ModelBenchmarkHeadline")
        self.headline_label.setWordWrap(True)

        self.scope_label = QLabel("")
        self.scope_label.setObjectName("ModelBenchmarkDescription")
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
        self.progress_detail.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.progress_detail.hide()
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_detail)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.addWidget(self.run_button)
        actions.addStretch(1)

        summary_copy = QVBoxLayout()
        summary_copy.setContentsMargins(0, 0, 0, 0)
        summary_copy.setSpacing(8)
        summary_copy.addLayout(status_row)
        summary_copy.addWidget(self.headline_label)
        summary_copy.addWidget(self.scope_label)
        summary_copy.addLayout(progress_row)
        summary_copy.addLayout(actions)

        stable_card, self.recommended_value = _metric_card(
            "Stable Note Range",
            primary=True,
        )
        self.recommended_hint = QLabel("")
        self.recommended_hint.setObjectName("ModelBenchmarkMetricHint")
        stable_card.layout().addWidget(self.recommended_hint)
        usable_card, self.usable_value = _metric_card("Extended Note Range")
        count_card, self.stable_value = _metric_card("Stable Notes")

        secondary_metrics = QVBoxLayout()
        secondary_metrics.setContentsMargins(0, 0, 0, 0)
        secondary_metrics.setSpacing(9)
        secondary_metrics.addWidget(usable_card)
        secondary_metrics.addWidget(count_card)

        self.metrics_container = TransparentContainer(
            self,
            object_name="ModelBenchmarkMetrics",
        )
        metrics = QHBoxLayout(self.metrics_container)
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(9)
        metrics.addWidget(stable_card, 1)
        metrics.addLayout(secondary_metrics, 1)

        summary_card = SurfaceFrame("raised", self)
        summary_card.setObjectName("ModelBenchmarkSummaryCard")
        self.summary_layout = QHBoxLayout(summary_card)
        self.summary_layout.setContentsMargins(22, 20, 22, 20)
        self.summary_layout.setSpacing(24)
        self.summary_layout.addLayout(summary_copy, 5)
        self.summary_layout.addWidget(self.metrics_container, 3)

        chart_panel = SurfaceFrame("raised", self)
        chart_panel.setObjectName("ModelBenchmarkChartPanel")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(18, 16, 18, 16)
        chart_layout.setSpacing(11)

        self.chart_heading = QHBoxLayout()
        self.chart_heading.setContentsMargins(0, 0, 0, 0)
        self.chart_heading.setSpacing(12)
        chart_copy = QVBoxLayout()
        chart_copy.setContentsMargins(0, 0, 0, 0)
        chart_copy.setSpacing(3)
        chart_title = QLabel("Note Range Stability")
        chart_title.setObjectName("DatasetAnalysisSectionTitle")
        self.chart_summary = QLabel("")
        self.chart_summary.setObjectName("DatasetAnalysisMeta")
        chart_copy.addWidget(chart_title)
        chart_copy.addWidget(self.chart_summary)
        self.legend_label = QLabel("")
        self.legend_label.setObjectName("ModelBenchmarkLegend")
        self.legend_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        self.chart_heading.addLayout(chart_copy, 1)
        self.chart_heading.addWidget(self.legend_label)

        range_panel = QFrame()
        range_panel.setObjectName("ModelBenchmarkRangePanel")
        range_layout = QVBoxLayout(range_panel)
        range_layout.setContentsMargins(12, 10, 12, 8)
        range_layout.setSpacing(3)
        self.range_header = QHBoxLayout()
        self.range_header.setContentsMargins(0, 0, 0, 0)
        range_title = QLabel("Stable Note Range at a Glance")
        range_title.setObjectName("ModelBenchmarkRangeTitle")
        self.range_summary = QLabel("")
        self.range_summary.setObjectName("DatasetAnalysisMeta")
        self.range_summary.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.range_header.addWidget(range_title)
        self.range_header.addWidget(self.range_summary, 1)
        self.range_view = BenchmarkNoteRangeView()
        self.range_legend = QLabel("")
        self.range_legend.setObjectName("ModelBenchmarkRangeLegend")
        range_layout.addLayout(self.range_header)
        range_layout.addWidget(self.range_view)
        range_layout.addWidget(self.range_legend)

        self.chart_view = PrecisionBenchmarkNoteChart()
        chart_layout.addLayout(self.chart_heading)
        chart_layout.addWidget(range_panel)
        chart_layout.addWidget(self.chart_view, 1)

        self.info_panel = SurfaceFrame("raised", self)
        self.info_panel.setObjectName("ModelBenchmarkInterpretationPanel")
        self.info_panel.setMinimumWidth(245)
        self.info_panel.setMaximumWidth(330)
        info_layout = QVBoxLayout(self.info_panel)
        info_layout.setContentsMargins(17, 16, 17, 16)
        info_layout.setSpacing(9)
        info_title = QLabel("Result Guide")
        info_title.setObjectName("DatasetAnalysisSectionTitle")
        info_subtitle = QLabel("Key information to know before using this model.")
        info_subtitle.setObjectName("DatasetAnalysisMeta")
        info_subtitle.setWordWrap(True)
        interpretation_card = QFrame()
        interpretation_card.setObjectName("ModelBenchmarkInterpretationCard")
        interpretation_layout = QVBoxLayout(interpretation_card)
        interpretation_layout.setContentsMargins(12, 12, 12, 12)
        interpretation_layout.setSpacing(6)
        interpretation_kicker = QLabel("Evaluation Summary")
        interpretation_kicker.setObjectName("ModelBenchmarkInterpretationKicker")
        self.interpretation_main = QLabel("")
        self.interpretation_main.setObjectName("ModelBenchmarkInterpretationMain")
        self.interpretation_main.setWordWrap(True)
        self.interpretation_sub = QLabel("")
        self.interpretation_sub.setObjectName("DatasetAnalysisMeta")
        self.interpretation_sub.setWordWrap(True)
        interpretation_layout.addWidget(interpretation_kicker)
        interpretation_layout.addWidget(self.interpretation_main)
        interpretation_layout.addWidget(self.interpretation_sub)

        self.scope_notice = QLabel("")
        self.scope_notice.setObjectName("ModelBenchmarkScopeNotice")
        self.scope_notice.setWordWrap(True)
        self.technical_button = FeedbackButton("Evaluation Criteria and Technical Details")
        self.technical_button.setObjectName("ModelBenchmarkDetailsButton")
        self.technical_button.setCheckable(True)
        self.technical_button.toggled.connect(self._toggle_technical_details)
        self.benchmark_meta = QLabel("")
        self.benchmark_meta.setObjectName("ModelBenchmarkTechnicalDetails")
        self.benchmark_meta.setWordWrap(True)
        self.benchmark_meta.hide()
        info_layout.addWidget(info_title)
        info_layout.addWidget(info_subtitle)
        info_layout.addWidget(interpretation_card)
        info_layout.addWidget(self.scope_notice)
        info_layout.addStretch(1)
        info_layout.addWidget(self.technical_button)
        info_layout.addWidget(self.benchmark_meta)

        self.results_container = TransparentContainer(
            self,
            object_name="ModelBenchmarkResults",
        )
        self.results_layout = QHBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(12)
        self.results_layout.addWidget(chart_panel, 1)
        self.results_layout.addWidget(self.info_panel)

        content = TransparentContainer(self, object_name="ModelPrecisionBenchmarkContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(summary_card)
        content_layout.addWidget(self.results_container, 1)

        scroll = QScrollArea(self)
        scroll.setObjectName("DatasetAnalysisScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_responsive_layout(event.size().width())

    def _apply_responsive_layout(self, width: int) -> None:
        narrow = width < 1160
        if narrow == self._narrow_layout:
            return
        self._narrow_layout = narrow
        direction = (
            QBoxLayout.Direction.TopToBottom
            if narrow
            else QBoxLayout.Direction.LeftToRight
        )
        self.summary_layout.setDirection(direction)
        self.results_layout.setDirection(direction)
        self.chart_heading.setDirection(direction)
        self.range_header.setDirection(direction)
        if narrow:
            self.info_panel.setMinimumWidth(0)
            self.info_panel.setMaximumWidth(16_777_215)
            self.legend_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.range_summary.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        else:
            self.info_panel.setMinimumWidth(245)
            self.info_panel.setMaximumWidth(330)
            self.legend_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
            )
            self.range_summary.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

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
            self._set_status("Run precise evaluation to measure the stable note range.")

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.range_view.set_theme_mode(theme_mode)
        self.chart_view.set_theme_mode(theme_mode)
        self._sync_legends()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._toggle_technical_details(self.technical_button.isChecked())
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
        self._render_running_state()
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
        self._render()
        self._set_status(f"Evaluation failed: {_format_benchmark_error(traceback_text)}")
        if self._report is None:
            self.headline_label.setText(tr("The evaluation could not be completed."))
        model_id = self._active_model_id or (
            self._record.model_id if self._record is not None else ""
        )
        model_title = self._active_model_title or (
            self._record.title if self._record is not None else ""
        )
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
        self.headline_label.setText(
            tr("Evaluating each note from C2 to C6: {stage}", stage=stage)
        )
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
        self.progress_bar.hide()
        self.progress_detail.hide()
        self.range_view.set_report(report)
        self.chart_view.set_report(report)
        self._sync_legends()
        if report is None:
            self.metrics_container.hide()
            self.results_container.hide()
            self.generated_label.hide()
            self.headline_label.setText(tr("Find the note range where this model stays stable."))
            self.scope_label.setText(
                tr(
                    "The same three reference vocals are tested from C2 to C6 "
                    "in half-step intervals."
                )
            )
            return

        self.metrics_container.show()
        self.results_container.show()
        self.generated_label.setText(
            tr(
                "{date}  /  {references} reference vocals",
                date=_format_generated_at(report.generated_at),
                references=report.reference_count,
            )
        )
        self.generated_label.show()
        stable_range = benchmark_note_range_label(
            report.recommended_low_shift,
            report.recommended_high_shift,
        )
        usable_range = benchmark_note_range_label(
            report.usable_low_shift,
            report.usable_high_shift,
        )
        center_note = benchmark_note_label(report.best_shift_semitones)
        if (
            report.recommended_low_shift is not None
            and report.recommended_high_shift is not None
        ):
            self.headline_label.setText(
                tr(
                    "This model is stable from {low} to {high}.",
                    low=benchmark_note_label(report.recommended_low_shift),
                    high=benchmark_note_label(report.recommended_high_shift),
                )
            )
        else:
            self.headline_label.setText(
                tr("No continuous stable note range was detected.")
            )
        self.scope_label.setText(
            tr(
                "This is the model's note-by-note conversion stability measured "
                "with the same reference vocals. Song-specific pitch is shown in Convert."
            )
        )
        self.recommended_value.setText(stable_range)
        self.recommended_hint.setText(
            tr(
                "Reference C4: {range} pitch",
                range=benchmark_shift_range_label(
                    report.recommended_low_shift,
                    report.recommended_high_shift,
                ),
            )
        )
        self.usable_value.setText(usable_range)
        self.stable_value.setText(f"{report.stable_point_count} / {len(report.points)}")
        self.chart_summary.setText(
            tr("Higher bars mean cleaner and more accurate conversion at that note.")
        )
        self.range_summary.setText(
            tr(
                "Stability center {note}  /  measured in half-step intervals",
                note=center_note,
            )
        )
        if (
            report.recommended_low_shift is not None
            and report.recommended_high_shift is not None
        ):
            self.interpretation_main.setText(
                tr(
                    "The model maintained stable conversion from {low} to {high}.",
                    low=benchmark_note_label(report.recommended_low_shift),
                    high=benchmark_note_label(report.recommended_high_shift),
                )
            )
        else:
            self.interpretation_main.setText(
                tr("No continuous stable note range was detected.")
            )
        self.interpretation_sub.setText(_interpretation_detail(report))
        self.scope_notice.setText(
            tr(
                "This result is not the singer's absolute range or the best pitch "
                "for a specific song. Check training range in Material Analysis."
            )
        )
        self.benchmark_meta.setText(_technical_details(report))

    def _render_running_state(self) -> None:
        self.metrics_container.hide()
        self.results_container.hide()
        self.generated_label.hide()
        self.headline_label.setText(tr("Evaluating each note from C2 to C6..."))
        self.scope_label.setText(
            tr(
                "Three reference vocals are being converted in half-step intervals. "
                "You can leave this page while the evaluation continues."
            )
        )
        self.progress_bar.show()
        self.progress_detail.show()

    def _toggle_technical_details(self, expanded: bool) -> None:
        self.benchmark_meta.setVisible(bool(expanded))
        self.technical_button.setText(
            tr("Hide Evaluation Details")
            if expanded
            else tr("Evaluation Criteria and Technical Details")
        )

    def _sync_legends(self) -> None:
        stable_color = "#48b48d" if self._theme_mode == "dark" else "#2c8d6d"
        caution_color = "#c99a4f" if self._theme_mode == "dark" else "#b5781c"
        avoid_color = "#757973" if self._theme_mode == "dark" else "#8e939b"
        self.legend_label.setText(
            "  ".join(
                (
                    _legend_item(stable_color, tr("Stable 82+")),
                    _legend_item(caution_color, tr("Caution 58-81")),
                    _legend_item(avoid_color, tr("Unstable 0-57")),
                )
            )
        )
        self.range_legend.setText(
            "  ".join(
                (
                    _legend_item(stable_color, tr("Stable note range")),
                    _legend_item(caution_color, tr("Extended note range")),
                )
            )
        )

    def _set_status(self, template: str, **values: object) -> None:
        set_translated_text(self.status_label, template, **values)
        self.status_label.setVisible(bool(template))
        if template.startswith("Evaluation failed"):
            tone = "danger"
        elif template in ("Latest precise evaluation loaded.", "Precise evaluation completed."):
            tone = "success"
        else:
            tone = "neutral"
        self.status_label.setProperty("tone", tone)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


def _metric_card(label: str, *, primary: bool = False) -> tuple[QFrame, QLabel]:
    card = SurfaceFrame("raised")
    card.setObjectName(
        "ModelBenchmarkPrimaryMetric" if primary else "ModelBenchmarkMetric"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(4)
    title = QLabel(label)
    title.setObjectName("ModelBenchmarkMetricLabel")
    value = QLabel("-")
    value.setObjectName(
        "ModelBenchmarkPrimaryMetricValue"
        if primary
        else "ModelBenchmarkMetricValue"
    )
    layout.addWidget(title)
    layout.addWidget(value)
    return card, value


def _format_generated_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y.%m.%d %H:%M")
    except ValueError:
        return value


def _interpretation_detail(report: ModelPrecisionBenchmark) -> str:
    stable_high = report.recommended_high_shift
    usable_high = report.usable_high_shift
    if stable_high is None:
        return tr("No continuous stable note range was detected. Review the graph before use.")
    if usable_high is not None and usable_high > stable_high:
        return tr(
            "Quality begins to drop at {note}. Notes above the extended range require extra care.",
            note=benchmark_note_label(stable_high + 1),
        )
    return tr("No additional caution range was detected beyond the stable note range.")


def _technical_details(report: ModelPrecisionBenchmark) -> str:
    metadata = tr(
        "{references} reference vocals  /  {success} of {total} renders completed  /  "
        "version {version}",
        references=report.reference_count,
        success=report.successful_jobs,
        total=report.total_jobs,
        version=report.benchmark_version,
    )
    translated_notes = tuple(tr(note) for note in report.notes)
    return "\n".join((metadata, *(f"• {note}" for note in translated_notes)))


def _legend_item(color: str, label: str) -> str:
    return f'<span style="color:{color}">●</span> {label}'


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
