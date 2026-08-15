from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QPointF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.services.i18n import tr
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_runtime import RvcTrainingRuntimeInspection
from jang_app.services.rvc_training_telemetry import (
    RvcTrainingHealth,
    RvcTrainingTelemetryHistory,
    RvcTrainingTelemetryProbe,
    RvcTrainingTelemetrySnapshot,
    append_telemetry_snapshot,
    assess_rvc_training_performance,
)


class TrainingTelemetryWorker(QThread):
    snapshot_ready = Signal(object)

    def __init__(
        self,
        backend: RvcComputeBackend,
        *,
        diagnostic_folder: Path | None = None,
        interval_seconds: float = 1.5,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._diagnostic_folder = diagnostic_folder
        self._interval_seconds = max(0.5, float(interval_seconds))
        self._stop_event = Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        probe = RvcTrainingTelemetryProbe(self._backend)
        while not self._stop_event.is_set():
            snapshot = probe.sample()
            append_telemetry_snapshot(self._diagnostic_folder, snapshot)
            self.snapshot_ready.emit(snapshot)
            self._stop_event.wait(self._interval_seconds)


class TrainingTelemetryGraph(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._samples: tuple[RvcTrainingTelemetrySnapshot, ...] = ()
        self.setObjectName("TrainingTelemetryGraph")
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_samples(self, samples: tuple[RvcTrainingTelemetrySnapshot, ...]) -> None:
        self._samples = samples[-90:]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(10, 10, -10, -10)
        if rect.width() <= 1 or rect.height() <= 1:
            return

        grid = QColor(self.palette().color(self.foregroundRole()))
        grid.setAlpha(24)
        painter.setPen(QPen(grid, 1))
        for fraction in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * fraction
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        gpu_values = tuple(sample.gpu_utilization_percent for sample in self._samples)
        memory_values = tuple(sample.gpu_memory_percent for sample in self._samples)
        self._draw_series(painter, rect, gpu_values, self._series_color("gpu"), 2.0)
        self._draw_series(painter, rect, memory_values, self._series_color("memory"), 1.4)

    def _draw_series(
        self,
        painter: QPainter,
        rect,
        values: tuple[float | None, ...],
        color: QColor,
        width: float,
    ) -> None:
        if len(values) < 2 or not any(value is not None for value in values):
            return
        path = QPainterPath()
        started = False
        denominator = max(1, len(values) - 1)
        for index, value in enumerate(values):
            if value is None:
                started = False
                continue
            x = rect.left() + rect.width() * index / denominator
            y = rect.bottom() - rect.height() * max(0.0, min(100.0, value)) / 100.0
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(color, width))
        painter.drawPath(path)

    def _series_color(self, series: str) -> QColor:
        color = QColor(self.palette().color(self.foregroundRole()))
        if series == "gpu":
            color.setRgb(86, 188, 151)
        else:
            color.setRgb(216, 171, 77)
        return color


class TrainingMonitorWidget(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TrainingMonitorCard")
        self._backend = RvcComputeBackend.CPU
        self._adapter_name = ""
        self._batch_size = 0
        self._workers: int | None = None
        self._precision = "-"
        self._current_epoch_seconds = 0.0
        self._average_epoch_seconds = 0.0
        self._history = RvcTrainingTelemetryHistory(120)
        self._build_ui()
        self.reset()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("Training Monitor")
        self.title_label.setObjectName("TrainingCardTitle")
        self.runtime_label = QLabel("Waiting for runtime information")
        self.runtime_label.setObjectName("TrainingMonitorRuntime")
        self.runtime_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.runtime_label)
        layout.addLayout(header)

        metrics = QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(8)
        self._metric_widgets: dict[str, tuple[QLabel, QProgressBar]] = {}
        for index, (key, label) in enumerate(
            (
                ("gpu", "GPU Usage"),
                ("vram", "VRAM"),
                ("cpu", "CPU Usage"),
                ("ram", "System Memory"),
            )
        ):
            card, value_label, progress = _metric_card(label)
            self._metric_widgets[key] = (value_label, progress)
            metrics.addWidget(card, index // 2, index % 2)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        layout.addLayout(metrics)

        performance = QFrame()
        performance.setObjectName("TrainingPerformanceStrip")
        performance_layout = QHBoxLayout(performance)
        performance_layout.setContentsMargins(12, 9, 12, 9)
        performance_layout.setSpacing(18)
        self.current_epoch_value = _performance_value("Current Epoch Time")
        self.average_epoch_value = _performance_value("Average Epoch Time")
        self.configuration_value = _performance_value("Effective Settings")
        performance_layout.addWidget(self.current_epoch_value, 1)
        performance_layout.addWidget(self.average_epoch_value, 1)
        performance_layout.addWidget(self.configuration_value, 2)
        layout.addWidget(performance)

        graph_header = QHBoxLayout()
        graph_header.setContentsMargins(0, 0, 0, 0)
        graph_title = QLabel("Recent Hardware Usage")
        graph_title.setObjectName("TrainingMonitorGraphTitle")
        self.graph_legend = QLabel("GPU  |  VRAM")
        self.graph_legend.setObjectName("TrainingMonitorLegend")
        graph_header.addWidget(graph_title)
        graph_header.addStretch(1)
        graph_header.addWidget(self.graph_legend)
        layout.addLayout(graph_header)
        self.graph = TrainingTelemetryGraph()
        layout.addWidget(self.graph)

        self.assessment_card = QFrame()
        self.assessment_card.setObjectName("TrainingAssessmentCard")
        assessment_layout = QHBoxLayout(self.assessment_card)
        assessment_layout.setContentsMargins(12, 10, 12, 10)
        assessment_layout.setSpacing(10)
        self.assessment_title = QLabel()
        self.assessment_title.setObjectName("TrainingAssessmentTitle")
        self.assessment_detail = QLabel()
        self.assessment_detail.setObjectName("TrainingAssessmentDetail")
        self.assessment_detail.setWordWrap(True)
        assessment_layout.addWidget(self.assessment_title)
        assessment_layout.addWidget(self.assessment_detail, 1)
        layout.addWidget(self.assessment_card)

    def configure(
        self,
        backend: RvcComputeBackend,
        *,
        adapter_name: str = "",
        batch_size: int = 0,
    ) -> None:
        self._backend = backend
        self._adapter_name = adapter_name.strip()
        self._batch_size = max(0, int(batch_size))
        self._sync_configuration()
        self._sync_assessment()

    def set_runtime_inspection(self, inspection: RvcTrainingRuntimeInspection) -> None:
        self._precision = "FP16" if inspection.training_accelerated else "FP32"
        parts = [self._adapter_name or inspection.backend.value.upper()]
        if inspection.torch_version:
            parts.append(f"Torch {inspection.torch_version}")
        runtime_version = inspection.hip_version or inspection.cuda_version
        if runtime_version:
            runtime_name = "ROCm" if inspection.hip_version else "CUDA"
            parts.append(f"{runtime_name} {runtime_version}")
        if inspection.device_capability:
            parts.append(f"sm_{inspection.device_capability[0]}{inspection.device_capability[1]}")
        parts.append(self._precision)
        self.runtime_label.setText("  |  ".join(part for part in parts if part))
        self._sync_configuration()

    def set_effective_workers(self, workers: int | None) -> None:
        self._workers = None if workers is None else max(0, int(workers))
        self._sync_configuration()

    def set_epoch_timing(self, current_seconds: float, average_seconds: float) -> None:
        self._current_epoch_seconds = max(0.0, float(current_seconds))
        self._average_epoch_seconds = max(0.0, float(average_seconds))
        self.current_epoch_value.setText(
            _format_seconds(self._current_epoch_seconds)
            if self._current_epoch_seconds > 0
            else "-"
        )
        self.average_epoch_value.setText(
            _format_seconds(self._average_epoch_seconds)
            if self._average_epoch_seconds > 0
            else "-"
        )

    def set_snapshot(self, snapshot: RvcTrainingTelemetrySnapshot) -> None:
        self._history.append(snapshot)
        self._set_metric("gpu", snapshot.gpu_utilization_percent, percent=True)
        self._set_metric(
            "vram",
            snapshot.gpu_memory_percent,
            detail=_memory_pair(
                snapshot.gpu_memory_used_bytes,
                snapshot.gpu_memory_total_bytes,
            ),
        )
        self._set_metric("cpu", snapshot.cpu_utilization_percent, percent=True)
        self._set_metric(
            "ram",
            snapshot.system_memory_percent,
            detail=_memory_pair(
                snapshot.system_memory_used_bytes,
                snapshot.system_memory_total_bytes,
            ),
        )
        self.graph.set_samples(self._history.samples)
        self._sync_assessment()

    def reset(self) -> None:
        self._history.clear()
        self.graph.set_samples(())
        for key in self._metric_widgets:
            self._set_metric(key, None)
        self.set_epoch_timing(0.0, 0.0)
        self._workers = None
        self._precision = "-"
        set_translated_text(self.runtime_label, "Waiting for runtime information")
        self._sync_configuration()
        self._sync_assessment()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._sync_configuration()
        self._sync_assessment()

    def _set_metric(
        self,
        key: str,
        value: float | None,
        *,
        percent: bool = False,
        detail: str = "",
    ) -> None:
        label, progress = self._metric_widgets[key]
        if value is None:
            label.setText(tr("Unavailable"))
            progress.setValue(0)
            progress.setProperty("available", False)
        else:
            label.setText(detail or (f"{value:.0f}%" if percent or not detail else detail))
            progress.setValue(round(max(0.0, min(100.0, value))))
            progress.setProperty("available", True)
        progress.style().unpolish(progress)
        progress.style().polish(progress)

    def _sync_configuration(self) -> None:
        workers = "-" if self._workers is None else str(self._workers)
        batch = "-" if self._batch_size <= 0 else str(self._batch_size)
        self.configuration_value.setText(
            tr(
                "Batch {batch}  |  Workers {workers}  |  {precision}",
                batch=batch,
                workers=workers,
                precision=self._precision,
            )
        )

    def _sync_assessment(self) -> None:
        assessment = assess_rvc_training_performance(
            self._history.samples,
            self._backend,
        )
        self.assessment_title.setText(tr(assessment.title))
        self.assessment_detail.setText(tr(assessment.detail))
        health = assessment.health.value
        if self.assessment_card.property("health") != health:
            self.assessment_card.setProperty("health", health)
            self.assessment_card.style().unpolish(self.assessment_card)
            self.assessment_card.style().polish(self.assessment_card)


def _metric_card(title: str) -> tuple[QFrame, QLabel, QProgressBar]:
    card = QFrame()
    card.setObjectName("TrainingMetricCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(6)
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    title_label = QLabel(title)
    title_label.setObjectName("TrainingMetricTitle")
    value_label = QLabel("-")
    value_label.setObjectName("TrainingMetricValue")
    value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
    header.addWidget(title_label)
    header.addStretch(1)
    header.addWidget(value_label)
    progress = QProgressBar()
    progress.setObjectName("TrainingMetricProgress")
    progress.setRange(0, 100)
    progress.setValue(0)
    progress.setTextVisible(False)
    layout.addLayout(header)
    layout.addWidget(progress)
    return card, value_label, progress


def _performance_value(title: str) -> QLabel:
    label = QLabel("-")
    label.setObjectName("TrainingPerformanceValue")
    label.setToolTip(title)
    return label


def _memory_pair(used: int | None, total: int | None) -> str:
    if used is None or total is None or total <= 0:
        return ""
    return f"{used / 1024**3:.1f} / {total / 1024**3:.1f} GB"


def _format_seconds(seconds: float) -> str:
    rounded = max(0, round(seconds))
    minutes, remaining = divmod(rounded, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:02d}:{remaining:02d}"
