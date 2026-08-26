from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.widgets import (
    FeedbackButton,
    SvgIconButton,
    attach_transparent_scroll_widget,
    render_app_icon,
)
from jang_app.services.i18n import tr
from jang_app.services.rvc_environment_status import RvcEnvironmentSnapshot
from jang_app.services.storage_management import StorageCleanupPlan, StorageInventory
from jang_app.services.system_environment import PcEnvironmentSnapshot


class EnvironmentNavigationButton(FeedbackButton):
    def __init__(self, label: str, icon_name: str) -> None:
        super().__init__()
        self.setObjectName("EnvironmentNavigationButton")
        self.setCheckable(True)
        self.setFixedHeight(62)
        self.setMinimumWidth(190)
        self._label_key = label
        self._summary = ""
        self._icon_name = icon_name
        self._theme_mode = "white"
        self._compact = False
        self.setAccessibleName(tr(label))

    def set_summary(self, summary: str) -> None:
        value = tr(summary)
        if value == self._summary:
            return
        self._summary = value
        self.setAccessibleDescription(value)
        self.update()

    def apply_language(self) -> None:
        self.setAccessibleName(tr(self._label_key))
        if self._compact:
            self.setToolTip(tr(self._label_key))
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_compact(self, compact: bool) -> None:
        if self._compact == compact:
            return
        self._compact = compact
        self.setFixedHeight(50 if compact else 62)
        if compact:
            self.setMinimumWidth(48)
            self.setMaximumWidth(48)
            self.setToolTip(tr(self._label_key))
        else:
            self.setMinimumWidth(190)
            self.setMaximumWidth(16777215)
            self.setToolTip("")
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dark = self._theme_mode == "dark"
        selected = self.isChecked()
        hovered = self._is_pointer_hovered()
        pressed = self._is_pointer_pressed() or self.isDown()
        background = QColor(0, 0, 0, 0)
        border = QColor(0, 0, 0, 0)
        if selected:
            background = QColor("#292927" if dark else "#eee8de")
            border = QColor("#4b4943" if dark else "#cfc5b5")
        elif pressed:
            background = QColor("#242422" if dark else "#e7e0d5")
        elif hovered:
            background = QColor("#222220" if dark else "#f3eee6")
        foreground = QColor("#efeee9" if dark else "#24231f")
        muted = QColor("#9c9a94" if dark else "#78736a")
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(background)
        painter.setPen(QPen(border, 1) if border.alpha() else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 11, 11)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#d6a13a" if dark else "#a56c16"))
            painter.drawRoundedRect(QRectF(0, 11, 3, rect.height() - 22), 1.5, 1.5)

        if self._compact:
            icon_rect = QRectF((rect.width() - 20) / 2, (rect.height() - 20) / 2, 20, 20)
            render_app_icon(painter, icon_rect, self._icon_name, foreground)
            return

        render_app_icon(painter, QRectF(14, 21, 19, 19), self._icon_name, foreground)
        label_font = QFont(self.font())
        label_font.setPixelSize(12)
        label_font.setWeight(QFont.Weight.Bold)
        painter.setFont(label_font)
        painter.setPen(foreground)
        painter.drawText(
            QRectF(43, 10, rect.width() - 52, 21),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            tr(self._label_key),
        )
        summary_font = QFont(self.font())
        summary_font.setPixelSize(9)
        summary_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(summary_font)
        painter.setPen(muted)
        summary = painter.fontMetrics().elidedText(
            self._summary,
            Qt.TextElideMode.ElideRight,
            max(20, int(rect.width() - 52)),
        )
        painter.drawText(
            QRectF(43, 31, rect.width() - 52, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            summary,
        )


class PcEnvironmentPanel(QFrame):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("EnvironmentContentPage")
        self._snapshot: PcEnvironmentSnapshot | None = None
        self._theme_mode = "white"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("EnvironmentScroll")
        self.scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        heading_frame = QFrame()
        heading_frame.setObjectName("EnvironmentPageHeader")
        heading = QHBoxLayout(heading_frame)
        heading.setContentsMargins(18, 12, 14, 12)
        heading.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = QLabel("PC Environment")
        self.title_label.setObjectName("EnvironmentPageTitle")
        self.description_label = QLabel(
            "Review the hardware available to JJZero Audio."
        )
        self.description_label.setObjectName("EnvironmentPageDescription")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.description_label)
        self.status_label = QLabel("Not checked")
        self.status_label.setObjectName("EnvironmentStatusPill")
        self.status_label.setProperty("status", "pending")
        self.refresh_button = SvgIconButton("refresh", size=34)
        self.refresh_button.setObjectName("DiagnosticsIconButton")
        set_translated_tooltip(self.refresh_button, "Refresh PC information")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addLayout(title_box, 1)
        heading.addWidget(self.status_label)
        heading.addWidget(self.refresh_button)

        self.hero = _InformationCard("Primary AI Device", hero=True)
        self.cpu_card = _InformationCard("CPU")
        self.memory_card = _InformationCard("Memory")
        self.memory_bar = QProgressBar()
        self.memory_bar.setObjectName("EnvironmentUsageBar")
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setTextVisible(False)
        self.memory_card.body_layout.addWidget(self.memory_bar)
        self.adapters_card = _InformationCard("Detected Graphics Devices")

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.addWidget(self.cpu_card, 0, 0)
        grid.addWidget(self.memory_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.checked_label = QLabel("")
        self.checked_label.setObjectName("EnvironmentPageDescription")
        layout.addWidget(self.hero)
        layout.addLayout(grid)
        layout.addWidget(self.adapters_card)
        layout.addWidget(self.checked_label)
        layout.addStretch(1)
        attach_transparent_scroll_widget(self.scroll_area, content)
        root.addWidget(heading_frame)
        root.addWidget(self.scroll_area)

    def reset_scroll(self) -> None:
        self.scroll_area.verticalScrollBar().setValue(0)

    def set_loading(self, loading: bool) -> None:
        self.refresh_button.setEnabled(not loading)
        if loading and self._snapshot is None:
            self.status_label.setText(tr("Checking..."))
            _set_status(self.status_label, "pending")

    def set_error(self, error: str) -> None:
        self.status_label.setText(tr("Unavailable"))
        _set_status(self.status_label, "failed")
        self.hero.set_rows((("Status", _last_line(error)),))

    def set_snapshot(self, snapshot: PcEnvironmentSnapshot) -> None:
        self._snapshot = snapshot
        processor = snapshot.processor
        memory = snapshot.memory
        selected = next(
            (
                adapter
                for adapter in snapshot.adapters
                if adapter.name == snapshot.selected_adapter_name
            ),
            None,
        )
        self.status_label.setText(tr("Ready" if not snapshot.warnings else "Attention"))
        _set_status(self.status_label, "completed" if not snapshot.warnings else "warning")
        self.hero.set_title(snapshot.selected_adapter_name or tr("CPU processing"))
        self.hero.set_rows(
            (
                ("AI profile", snapshot.selected_profile.upper() or "-"),
                (
                    "Dedicated VRAM",
                    _format_bytes(selected.adapter_ram) if selected is not None else "-",
                ),
                ("Operating system", snapshot.os_description),
            )
        )
        self.cpu_card.set_rows(
            (
                ("Processor", processor.name),
                ("Physical cores", str(processor.physical_cores or "-")),
                ("Logical processors", str(processor.logical_processors or "-")),
                ("Architecture", processor.architecture or "-"),
            )
        )
        self.memory_card.set_rows(
            (
                ("Used", _format_bytes(memory.used_bytes)),
                ("Available", _format_bytes(memory.available_bytes)),
                ("Total", _format_bytes(memory.total_bytes)),
            ),
            before_existing=True,
        )
        self.memory_bar.setValue(memory.used_percent)
        adapter_rows = tuple(
            (
                adapter.name,
                f"{adapter.vendor.upper()}  |  "
                f"{_adapter_memory_label(adapter.adapter_ram)}  |  "
                f"{adapter.driver_version or tr('Driver unavailable')}",
            )
            for adapter in snapshot.adapters
        ) or (
            (
                "Graphics devices",
                tr("No graphics adapter information is available."),
            ),
        )
        self.adapters_card.set_rows(adapter_rows)
        self.checked_label.setText(
            tr("Last checked: {time}", time=_format_time(snapshot.checked_at))
        )

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.refresh_button, "Refresh PC information")
        if self._snapshot is not None:
            self.set_snapshot(self._snapshot)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.refresh_button.set_theme_mode(theme_mode)


class RvcEnvironmentPanel(QFrame):
    detailed_check_requested = Signal()
    repair_requested = Signal()
    open_location_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("EnvironmentContentPage")
        self._snapshot: RvcEnvironmentSnapshot | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("EnvironmentScroll")
        self.scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        heading_frame = QFrame()
        heading_frame.setObjectName("EnvironmentPageHeader")
        heading = QHBoxLayout(heading_frame)
        heading.setContentsMargins(18, 12, 14, 12)
        heading.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = QLabel("RVC Environment")
        self.title_label.setObjectName("EnvironmentPageTitle")
        self.description_label = QLabel(
            "Check the runtime used for conversion and model training."
        )
        self.description_label.setObjectName("EnvironmentPageDescription")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.description_label)
        self.status_label = QLabel("Not checked")
        self.status_label.setObjectName("EnvironmentStatusPill")
        self.status_label.setProperty("status", "pending")
        heading.addLayout(title_box, 1)
        heading.addWidget(self.status_label)

        self.summary_card = _InformationCard("RVC Runtime", hero=True)
        self.runtime_card = _InformationCard("Runtime Details")
        self.backend_card = _InformationCard("Execution Devices")
        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setSpacing(12)
        detail_grid.addWidget(self.runtime_card, 0, 0)
        detail_grid.addWidget(self.backend_card, 0, 1)
        detail_grid.setColumnStretch(0, 1)
        detail_grid.setColumnStretch(1, 1)
        self.checks_card = _InformationCard("Environment Checks")

        self.action_status = QLabel("")
        self.action_status.setObjectName("EnvironmentPageDescription")
        self.open_button = SvgIconButton("folder", size=34)
        self.open_button.setObjectName("DiagnosticsIconButton")
        set_translated_tooltip(self.open_button, "Open RVC runtime folder")
        self.open_button.clicked.connect(self._open_runtime)
        self.repair_button = FeedbackButton("Repair Environment")
        self.repair_button.setObjectName("DiagnosticsActionButton")
        self.repair_button.clicked.connect(self.repair_requested.emit)
        self.detailed_button = FeedbackButton("Run Detailed Check")
        self.detailed_button.setObjectName("DiagnosticsPrimaryButton")
        self.detailed_button.clicked.connect(self.detailed_check_requested.emit)
        action_bar = QFrame()
        action_bar.setObjectName("EnvironmentActionBar")
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(18, 8, 18, 14)
        actions.setSpacing(8)
        actions.addWidget(self.action_status, 1)
        actions.addWidget(self.open_button)
        actions.addWidget(self.repair_button)
        actions.addWidget(self.detailed_button)

        layout.addWidget(self.summary_card)
        layout.addLayout(detail_grid)
        layout.addWidget(self.checks_card)
        layout.addStretch(1)
        attach_transparent_scroll_widget(self.scroll_area, content)
        root.addWidget(heading_frame)
        root.addWidget(self.scroll_area, 1)
        root.addWidget(action_bar)

    def reset_scroll(self) -> None:
        self.scroll_area.verticalScrollBar().setValue(0)

    def set_loading(self, loading: bool, *, deep: bool = False) -> None:
        self.detailed_button.setEnabled(not loading)
        self.repair_button.setEnabled(not loading)
        if loading:
            self.action_status.setText(
                tr("Running the installed runtime check...")
                if deep
                else tr("Reading the installed RVC environment...")
            )

    def set_error(self, error: str) -> None:
        self.action_status.setText(_last_line(error))
        self.status_label.setText(tr("Unavailable"))
        _set_status(self.status_label, "failed")

    def set_snapshot(self, snapshot: RvcEnvironmentSnapshot) -> None:
        self._snapshot = snapshot
        self.action_status.clear()
        status_text = {
            "completed": "Ready",
            "warning": "Attention",
            "failed": "Repair required",
        }.get(snapshot.status, "Not checked")
        self.status_label.setText(tr(status_text))
        _set_status(self.status_label, snapshot.status)
        self.summary_card.set_title(tr(snapshot.summary))
        self.summary_card.set_rows(
            (
                ("Adapter", snapshot.adapter_name),
                ("Active profile", snapshot.active_profile.upper() or "-"),
                ("Installation", tr(snapshot.installation_kind)),
            )
        )
        capability = (
            f"sm_{snapshot.capability[0]}{snapshot.capability[1]}"
            if snapshot.capability
            else "-"
        )
        if snapshot.deep_checked:
            self.runtime_card.set_rows(
                (
                    ("Python", snapshot.python_version or "-"),
                    ("PyTorch", snapshot.torch_version or "-"),
                    ("CUDA", snapshot.cuda_version or "-"),
                    ("ROCm / HIP", snapshot.hip_version or "-"),
                    ("Compute capability", capability),
                    ("Runtime version", snapshot.runtime_version or "-"),
                )
            )
        else:
            self.runtime_card.set_rows(
                (("Status", tr("Run the detailed check to view runtime versions.")),)
            )
        self.backend_card.set_rows(
            (
                ("Conversion", snapshot.inference_backend.upper()),
                ("Model training", snapshot.training_backend.upper()),
                ("Preferred profile", snapshot.preferred_profile.upper() or "-"),
                ("Activation", snapshot.activation_status or "-"),
            )
        )
        self.checks_card.set_status_rows(
            tuple(
                (check.title, check.detail, check.status) for check in snapshot.checks
            )
        )
        self.detailed_button.setText(
            tr("Run Detailed Check Again" if snapshot.deep_checked else "Run Detailed Check")
        )

    def _open_runtime(self) -> None:
        if self._snapshot is not None:
            self.open_location_requested.emit(self._snapshot.root)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.open_button, "Open RVC runtime folder")
        if self._snapshot is not None:
            self.set_snapshot(self._snapshot)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_button.set_theme_mode(theme_mode)


class StorageManagementPanel(QFrame):
    scan_requested = Signal()
    cleanup_requested = Signal()
    locations_requested = Signal()
    open_location_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("EnvironmentContentPage")
        self._inventory: StorageInventory | None = None
        self._cleanup_plan = StorageCleanupPlan(())
        self._locations: tuple[tuple[str, Path], ...] = ()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("EnvironmentScroll")
        self.scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        heading_frame = QFrame()
        heading_frame.setObjectName("EnvironmentPageHeader")
        heading = QHBoxLayout(heading_frame)
        heading.setContentsMargins(18, 12, 14, 12)
        heading.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = QLabel("Storage Management")
        self.title_label.setObjectName("EnvironmentPageTitle")
        self.description_label = QLabel(
            "Review app storage and safely remove rebuildable files."
        )
        self.description_label.setObjectName("EnvironmentPageDescription")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.description_label)
        self.scan_button = SvgIconButton("refresh", size=34)
        self.scan_button.setObjectName("DiagnosticsIconButton")
        set_translated_tooltip(self.scan_button, "Scan storage again")
        self.scan_button.clicked.connect(self.scan_requested.emit)
        heading.addLayout(title_box, 1)
        heading.addWidget(self.scan_button)

        self.storage_card = _InformationCard("Available Storage", hero=True)
        self.storage_bar = QProgressBar()
        self.storage_bar.setObjectName("EnvironmentStorageBar")
        self.storage_bar.setRange(0, 100)
        self.storage_bar.setTextVisible(False)
        self.storage_card.body_layout.addWidget(self.storage_bar)
        self.scan_progress = QProgressBar()
        self.scan_progress.setObjectName("EnvironmentScanProgress")
        self.scan_progress.setRange(0, 100)
        self.scan_progress.hide()

        self.categories_card = _InformationCard("Storage Breakdown")
        self.cleanup_card = _InformationCard("Safe Cleanup")
        self.cleanup_summary = QLabel("")
        self.cleanup_summary.setObjectName("EnvironmentPageDescription")
        self.cleanup_summary.setWordWrap(True)
        self.cleanup_button = FeedbackButton("Review Safe Cleanup")
        self.cleanup_button.setObjectName("DiagnosticsPrimaryButton")
        self.cleanup_button.clicked.connect(self.cleanup_requested.emit)
        cleanup_actions = QHBoxLayout()
        cleanup_actions.addWidget(self.cleanup_summary, 1)
        cleanup_actions.addWidget(self.cleanup_button)
        self.cleanup_card.body_layout.addLayout(cleanup_actions)

        self.locations_card = _InformationCard("Storage Locations")
        self.change_locations_button = FeedbackButton("Change Storage Locations")
        self.change_locations_button.setObjectName("DiagnosticsActionButton")
        self.change_locations_button.clicked.connect(self.locations_requested.emit)
        self.locations_card.body_layout.addWidget(
            self.change_locations_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        self.action_status = QLabel("")
        self.action_status.setObjectName("EnvironmentPageDescription")
        layout.addWidget(self.storage_card)
        layout.addWidget(self.scan_progress)
        layout.addWidget(self.categories_card)
        layout.addWidget(self.cleanup_card)
        layout.addWidget(self.locations_card)
        layout.addWidget(self.action_status)
        layout.addStretch(1)
        attach_transparent_scroll_widget(self.scroll_area, content)
        root.addWidget(heading_frame)
        root.addWidget(self.scroll_area)

    def reset_scroll(self) -> None:
        self.scroll_area.verticalScrollBar().setValue(0)

    def set_locations(self, locations: tuple[tuple[str, Path], ...]) -> None:
        self._locations = locations
        rows = tuple((label, str(path)) for label, path in locations)
        self.locations_card.set_action_rows(rows, self._open_location)

    def set_loading(self, loading: bool) -> None:
        self.scan_button.setEnabled(not loading)
        self.cleanup_button.setEnabled(not loading and bool(self._cleanup_plan.candidates))
        self.scan_progress.setVisible(loading)
        if loading:
            self.scan_progress.setValue(0)
            self.action_status.setText(tr("Scanning managed storage..."))

    def set_progress(self, value: int) -> None:
        self.scan_progress.setValue(max(0, min(100, value)))

    def set_error(self, error: str) -> None:
        self.scan_progress.hide()
        self.action_status.setText(_last_line(error))

    def set_inventory(self, inventory: StorageInventory) -> None:
        self._inventory = inventory
        self.scan_progress.hide()
        self.action_status.clear()
        used_percent = (
            round(inventory.disk_used_bytes * 100 / inventory.disk_total_bytes)
            if inventory.disk_total_bytes
            else 0
        )
        if inventory.disk_free_bytes < 8 * 1024**3:
            state = "danger"
        elif inventory.disk_free_bytes < 20 * 1024**3:
            state = "warning"
        else:
            state = "completed"
        self.storage_bar.setValue(max(0, min(100, used_percent)))
        self.storage_bar.setProperty("storageState", state)
        self.storage_bar.style().unpolish(self.storage_bar)
        self.storage_bar.style().polish(self.storage_bar)
        self.storage_card.set_title(
            tr("{free} available", free=_format_bytes(inventory.disk_free_bytes))
        )
        self.storage_card.set_rows(
            (
                ("Location", str(inventory.storage_root)),
                ("Used on drive", _format_bytes(inventory.disk_used_bytes)),
                ("Drive capacity", _format_bytes(inventory.disk_total_bytes)),
                ("Managed by JJZero", _format_bytes(inventory.managed_bytes)),
            )
        )
        category_rows = tuple(
            (
                category.title,
                f"{_format_bytes(category.size_bytes)}  |  "
                f"{category.file_count:,} {tr('files')}  |  {tr(_safety_label(category.safety))}",
                category.safety,
            )
            for category in inventory.categories
        )
        self.categories_card.set_status_rows(category_rows)

    def set_cleanup_plan(self, plan: StorageCleanupPlan) -> None:
        self._cleanup_plan = plan
        self.cleanup_button.setEnabled(bool(plan.candidates))
        if not plan.candidates:
            text = "No safe cleanup items were found."
        else:
            text = "{size} can be safely reclaimed from {count} files."
        self.cleanup_summary.setText(
            tr(text, size=_format_bytes(plan.reclaimable_bytes), count=plan.file_count)
        )
        if plan.skipped_for_active_jobs:
            self.cleanup_summary.setText(
                self.cleanup_summary.text()
                + "\n"
                + tr("Temporary work files are excluded while a job is running.")
            )

    def set_cleanup_running(self, running: bool) -> None:
        self.cleanup_button.setEnabled(not running and bool(self._cleanup_plan.candidates))
        self.scan_button.setEnabled(not running)
        self.scan_progress.setVisible(running)
        if running:
            self.scan_progress.setValue(0)
            self.action_status.setText(tr("Cleaning safe temporary files..."))

    def set_cleanup_result(
        self,
        reclaimed_bytes: int,
        failed_count: int,
        skipped_count: int = 0,
    ) -> None:
        if skipped_count:
            self.action_status.setText(
                tr(
                    "Reclaimed {size}; {count} temporary items were kept because a job started.",
                    size=_format_bytes(reclaimed_bytes),
                    count=skipped_count,
                )
            )
            return
        if failed_count:
            self.action_status.setText(
                tr(
                    "Reclaimed {size}; {count} items could not be removed.",
                    size=_format_bytes(reclaimed_bytes),
                    count=failed_count,
                )
            )
        else:
            self.action_status.setText(
                tr("Reclaimed {size}.", size=_format_bytes(reclaimed_bytes))
            )

    def _open_location(self, index: int) -> None:
        if 0 <= index < len(self._locations):
            self.open_location_requested.emit(self._locations[index][1])

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.scan_button, "Scan storage again")
        if self._inventory is not None:
            self.set_inventory(self._inventory)
        self.set_cleanup_plan(self._cleanup_plan)
        self.set_locations(self._locations)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.scan_button.set_theme_mode(theme_mode)
        self.locations_card.set_theme_mode(theme_mode)


class _InformationCard(QFrame):
    def __init__(self, title: str, *, hero: bool = False) -> None:
        super().__init__()
        self.setObjectName("EnvironmentHeroCard" if hero else "EnvironmentInfoCard")
        self._title_key = title
        self._theme_mode = "white"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        self.title_label = QLabel(title)
        self.title_label.setObjectName(
            "EnvironmentHeroTitle" if hero else "EnvironmentCardTitle"
        )
        self.body = QWidget()
        self.body.setObjectName("EnvironmentCardBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_rows(
        self,
        rows: tuple[tuple[str, str], ...],
        *,
        before_existing: bool = False,
    ) -> None:
        _clear_layout(self.body_layout, preserve_last=1 if before_existing else 0)
        insert_at = 0
        for label, value in rows:
            row = _information_row(label, value)
            if before_existing:
                self.body_layout.insertWidget(insert_at, row)
                insert_at += 1
            else:
                self.body_layout.addWidget(row)

    def set_status_rows(self, rows: tuple[tuple[str, str, str], ...]) -> None:
        _clear_layout(self.body_layout)
        for title, detail, status in rows:
            row = QFrame()
            row.setObjectName("EnvironmentStatusRow")
            row.setProperty("status", status)
            row.setMinimumHeight(48)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)
            indicator = QLabel(_status_symbol(status))
            indicator.setObjectName("EnvironmentCheckIndicator")
            indicator.setProperty("status", status)
            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)
            heading = QLabel(tr(title))
            heading.setObjectName("EnvironmentInformationLabel")
            description = QLabel(tr(detail))
            description.setObjectName("EnvironmentInformationValue")
            description.setWordWrap(True)
            text_layout.addWidget(heading)
            text_layout.addWidget(description)
            row_layout.addWidget(indicator, 0, Qt.AlignmentFlag.AlignTop)
            row_layout.addLayout(text_layout, 1)
            self.body_layout.addWidget(row)

    def set_action_rows(self, rows: tuple[tuple[str, str], ...], action) -> None:
        _clear_layout(self.body_layout, preserve_last=1)
        for index, (label, value) in enumerate(rows):
            row = _information_row(label, value)
            button = SvgIconButton("folder", size=30)
            button.setObjectName("DiagnosticsIconButton")
            button.set_theme_mode(self._theme_mode)
            set_translated_tooltip(button, "Open file location")
            button.clicked.connect(lambda _checked=False, value=index: action(value))
            row.layout().addWidget(button)
            self.body_layout.insertWidget(index, row)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for button in self.findChildren(SvgIconButton):
            button.set_theme_mode(theme_mode)


def _information_row(label: str, value: str) -> QFrame:
    row = QFrame()
    row.setObjectName("EnvironmentInformationRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(12)
    label_widget = QLabel(tr(label))
    label_widget.setObjectName("EnvironmentInformationLabel")
    value_widget = QLabel(value)
    value_widget.setObjectName("EnvironmentInformationValue")
    value_widget.setWordWrap(True)
    value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(label_widget, 0)
    layout.addWidget(value_widget, 1)
    return row


def _clear_layout(layout: QVBoxLayout, *, preserve_last: int = 0) -> None:
    while layout.count() > preserve_last:
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _set_status(label: QLabel, status: str) -> None:
    label.setProperty("status", status)
    label.style().unpolish(label)
    label.style().polish(label)


def _status_symbol(status: str) -> str:
    return {
        "completed": "OK",
        "warning": "!",
        "info": "i",
        "failed": "X",
        "pending": "...",
    }.get(status, "-")


def _safety_label(safety: str) -> str:
    return {
        "protected": "Protected",
        "managed": "Manage directly",
        "downloadable": "Can be downloaded again",
        "safe": "Safe cleanup available",
    }.get(safety, safety)


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _adapter_memory_label(value: int) -> str:
    return _format_bytes(value) if value else tr("VRAM unavailable")


def _format_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _last_line(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1] if lines else tr("Unavailable")
