from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import SUPPORTED_AUDIO_EXTENSIONS
from jang_app.qt_app.model_clip_editor import ModelClipEditor
from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.qt_app.workers import TaskCallable, TaskWorker
from jang_app.services.audio_metadata import format_duration
from jang_app.services.clip_edit_history import TRAINING_MODE_CLIPS
from jang_app.services.model_dataset import ModelDataset, ModelDatasetItem, ModelDatasetStore
from jang_app.services.i18n import tr
from jang_app.services.segment_review import split_review_regions
from jang_app.services.silence_detection import detect_speech_regions


class ModelDatasetPanel(QWidget):
    preview_started = Signal()

    def __init__(self, store: ModelDatasetStore) -> None:
        super().__init__()
        self._store = store
        self._model_id = ""
        self._dataset = ModelDataset("")
        self._worker: TaskWorker | None = None
        self._worker_success: Callable[[object], None] | None = None
        self._externally_locked = False
        self._theme_mode = "white"
        self._build_ui()
        self.set_model(None)

    def _build_ui(self) -> None:
        self.source_list = DatasetAudioList(accept_files=True)
        self.training_list = DatasetAudioList()
        self.source_list.files_dropped.connect(self.add_files)
        self.source_list.itemDoubleClicked.connect(lambda _item: self._select_sources())
        self.training_list.itemDoubleClicked.connect(lambda _item: self._deselect_training())
        self.source_list.itemSelectionChanged.connect(self._sync_action_state)
        self.training_list.itemSelectionChanged.connect(self._on_training_selection_changed)

        self.add_button = _dataset_icon_button("file_plus", "Add source audio")
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = _dataset_icon_button("trash", "Remove source audio")
        self.remove_button.clicked.connect(self._remove_sources)
        self.move_right_button = _dataset_icon_button(
            "arrow_right",
            "Use in training set",
            38,
            "DatasetTransferButton",
        )
        self.move_right_button.clicked.connect(self._select_sources)
        self.move_left_button = _dataset_icon_button(
            "arrow_left",
            "Return to source audio",
            38,
            "DatasetTransferButton",
        )
        self.move_left_button.clicked.connect(self._deselect_training)
        self.move_up_button = _dataset_icon_button("chevron_up", "Move earlier")
        self.move_up_button.clicked.connect(lambda: self._move_training_item(-1))
        self.move_down_button = _dataset_icon_button("chevron_down", "Move later")
        self.move_down_button.clicked.connect(lambda: self._move_training_item(1))

        self.source_count_label = _count_badge()
        self.training_count_label = _count_badge()
        source_column = self._build_column(
            "Source Audio",
            self.source_count_label,
            self.source_list,
            "Drop audio files here",
            (self.add_button, self.remove_button),
        )
        training_column = self._build_column(
            "Training Set",
            self.training_count_label,
            self.training_list,
            "Move source audio here",
            (self.move_up_button, self.move_down_button),
        )

        transfer_rail = QFrame()
        transfer_rail.setObjectName("DatasetTransferRail")
        transfer_layout = QVBoxLayout(transfer_rail)
        transfer_layout.setContentsMargins(8, 8, 8, 8)
        transfer_layout.setSpacing(8)
        transfer_layout.addStretch(1)
        transfer_layout.addWidget(self.move_right_button)
        transfer_layout.addWidget(self.move_left_button)
        transfer_layout.addStretch(1)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        columns.addWidget(source_column, 1)
        columns.addWidget(transfer_rail, 0)
        columns.addWidget(training_column, 1)

        columns_widget = QWidget()
        columns_widget.setLayout(columns)

        self.clip_editor = ModelClipEditor()
        self.clip_editor.add_clip_requested.connect(self._add_clip)
        self.clip_editor.update_clip_requested.connect(self._update_clip)
        self.clip_editor.split_clip_requested.connect(self._split_clip)
        self.clip_editor.analyze_requested.connect(self._analyze_silence)
        self.clip_editor.use_candidate_requested.connect(self._use_candidate)
        self.clip_editor.candidate_status_requested.connect(self._set_candidate_status)
        self.clip_editor.remove_clip_requested.connect(self._remove_clip)
        self.clip_editor.undo_requested.connect(self._undo_clip)
        self.clip_editor.redo_requested.connect(self._redo_clip)
        self.clip_editor.reset_requested.connect(self._reset_item)
        self.clip_editor.ready_requested.connect(self._mark_ready)
        self.clip_editor.navigate_requested.connect(self._navigate_training_item)
        self.clip_editor.close_requested.connect(self._close_editor)
        self.clip_editor.denoise_requested.connect(self._apply_denoise)
        self.clip_editor.remove_denoise_requested.connect(self._remove_denoise)
        self.clip_editor.playback_started.connect(self.preview_started.emit)
        self.clip_editor.playback_failed.connect(
            lambda error: self._set_status(f"Preview failed: {_last_error_line(error)}")
        )
        self.clip_editor.hide()

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("DatasetSummary")
        self.status_label = QLabel("")
        self.status_label.setObjectName("DatasetStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.hide()

        footer = QFrame()
        footer.setObjectName("DatasetFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 8)
        footer_layout.addWidget(self.summary_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DatasetProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(columns_widget, 1)
        layout.addWidget(self.clip_editor, 0)
        layout.addWidget(footer)
        layout.addWidget(self.progress_bar)

    def _build_column(
        self,
        title: str,
        count_label: QLabel,
        list_widget: "DatasetAudioList",
        empty_text: str,
        actions: tuple[SvgIconButton, ...],
    ) -> QFrame:
        column = QFrame()
        column.setObjectName("DatasetColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        heading.setContentsMargins(2, 0, 2, 0)
        heading.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("DatasetColumnTitle")
        heading.addWidget(title_label)
        heading.addWidget(count_label)
        heading.addStretch(1)
        for button in actions:
            heading.addWidget(button)

        list_widget.set_empty_text(empty_text)

        layout.addLayout(heading)
        layout.addWidget(list_widget, 1)
        return column

    def set_model(self, model_id: str | None) -> None:
        self.clip_editor.stop_preview()
        self.clip_editor.hide()
        self._model_id = model_id or ""
        if not self._model_id:
            self._dataset = ModelDataset("")
            self._set_status("")
            self._render()
            self._set_enabled(False)
            return
        try:
            self._dataset = self._store.load(self._model_id)
            self._set_status("")
        except Exception as exc:
            self._dataset = ModelDataset(self._model_id)
            self._set_status(f"Load failed: {_last_error_line(exc)}")
        self._render()
        self._set_enabled(not self._externally_locked)

    def set_training_locked(self, is_locked: bool) -> None:
        self._externally_locked = is_locked
        self._set_enabled(bool(self._model_id) and self._worker is None and not is_locked)
        self.clip_editor.set_busy(self._worker is not None or is_locked)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for button in (
            self.add_button,
            self.remove_button,
            self.move_right_button,
            self.move_left_button,
            self.move_up_button,
            self.move_down_button,
        ):
            button.set_theme_mode(theme_mode)
        self.clip_editor.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.source_list.apply_language()
        self.training_list.apply_language()
        self.clip_editor.apply_language()
        for list_widget in (self.source_list, self.training_list):
            for index in range(list_widget.count()):
                row = list_widget.itemWidget(list_widget.item(index))
                if isinstance(row, DatasetAudioRow):
                    row.apply_language()
        self._refresh_summary()

    def add_files(self, paths: tuple[Path, ...]) -> None:
        if not self._model_id or self._worker is not None or not paths:
            return
        self._start_worker(
            lambda progress: self._store.add_sources(self._model_id, paths, progress),
            "Adding source audio",
            lambda result: self._apply_worker_dataset(result, status="Source audio added"),
        )

    def _start_worker(self, task: TaskCallable, status: str, on_success: Callable[[object], None]) -> None:
        if self._worker is not None:
            return
        self._set_busy(True)
        self.progress_bar.setValue(0)
        self._set_status(status)
        worker = TaskWorker(task)
        worker.setParent(self)
        worker.progress_changed.connect(self.progress_bar.setValue)
        worker.succeeded.connect(self._on_worker_succeeded)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker_success = on_success
        self._worker = worker
        worker.start()

    def _choose_files(self) -> None:
        extensions = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_AUDIO_EXTENSIONS))
        selected, _filter = QFileDialog.getOpenFileNames(
            self,
            tr("Add Source Audio"),
            str(Path.home()),
            f"{tr('Audio Files')} ({extensions})",
        )
        if selected:
            self.add_files(tuple(Path(path) for path in selected))

    def _on_worker_succeeded(self, result: object) -> None:
        if self._worker_success is not None:
            self._worker_success(result)

    def _on_worker_failed(self, traceback_text: str) -> None:
        self._set_status(f"Operation failed: {_last_error_line(traceback_text)}")

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self._worker_success = None
        self._set_busy(False)
        if worker is not None:
            worker.deleteLater()

    def _select_sources(self) -> None:
        self._apply_dataset_change(self._store.select_items, _selected_item_ids(self.source_list))

    def _deselect_training(self) -> None:
        self._apply_dataset_change(self._store.deselect_items, _selected_item_ids(self.training_list))

    def _remove_sources(self) -> None:
        self._apply_dataset_change(self._store.remove_items, _selected_item_ids(self.source_list))

    def _move_training_item(self, offset: int) -> None:
        item_ids = _selected_item_ids(self.training_list)
        if len(item_ids) != 1 or not self._model_id:
            return
        try:
            self._dataset = self._store.move_selected_item(self._model_id, item_ids[0], offset)
        except Exception as exc:
            self._set_status(f"Reorder failed: {_last_error_line(exc)}")
            return
        self._render(selected_training_id=item_ids[0])

    def _add_clip(self, start_ms: int, end_ms: int) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.add_clip(self._model_id, item.item_id, start_ms, end_ms, progress),
            "Rendering clip",
            lambda result: self._apply_worker_dataset(result, selected_training_id=item.item_id, status="Clip added"),
        )

    def _update_clip(self, clip_id: str, start_ms: int, end_ms: int) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.update_clip(
                self._model_id,
                item.item_id,
                clip_id,
                start_ms,
                end_ms,
                progress,
            ),
            "Updating clip",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Clip updated",
            ),
        )

    def _split_clip(self, clip_id: str, position_ms: int) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.split_clip(
                self._model_id,
                item.item_id,
                clip_id,
                position_ms,
                progress,
            ),
            "Splitting clip",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Clip split",
            ),
        )

    def _analyze_silence(
        self,
        threshold_db: int,
        min_silence_ms: int,
        padding_ms: int,
        max_clip_seconds: int,
    ) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: _build_review_queue(
                self._store,
                self._model_id,
                item.item_id,
                item.active_audio_path,
                threshold_db,
                min_silence_ms,
                padding_ms,
                max_clip_seconds * 1000,
                progress,
            ),
            "Analyzing voice regions",
            lambda result: self._show_review_queue(result, item.item_id),
        )

    def _apply_denoise(self, strength: int, sample_start_ms: int, sample_end_ms: int) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.apply_denoise(
                self._model_id,
                item.item_id,
                strength,
                sample_start_ms,
                sample_end_ms,
                progress,
            ),
            "Removing noise",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Denoised version ready",
            ),
        )

    def _remove_denoise(self) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None or not item.has_denoised_audio:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.remove_denoise(
                self._model_id,
                item.item_id,
                progress,
            ),
            "Restoring clean source",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Denoised version removed",
            ),
        )

    def _show_review_queue(self, result: object, item_id: str) -> None:
        if not isinstance(result, ModelDataset):
            return
        item = next((candidate for candidate in result.items if candidate.item_id == item_id), None)
        count = len(item.segment_candidates) if item is not None else 0
        status = "{count} review segments found" if count else "No voice regions found"
        self._apply_worker_dataset(result, selected_training_id=item_id, status=tr(status, count=count))

    def _use_candidate(self, candidate_id: str, start_ms: int, end_ms: int) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.accept_segment_candidate(
                self._model_id,
                item.item_id,
                candidate_id,
                start_ms,
                end_ms,
                progress,
            ),
            "Rendering region",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Region added",
            ),
        )

    def _set_candidate_status(self, candidate_id: str, status: str) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self._run_editor_change(
            lambda: self._store.set_segment_candidate_status(
                self._model_id,
                item.item_id,
                candidate_id,
                status,
            ),
            item.item_id,
        )

    def _remove_clip(self, clip_id: str) -> None:
        item = self._current_training_item()
        if item is None:
            return
        self.clip_editor.stop_preview()
        self._run_editor_change(lambda: self._store.remove_clip(self._model_id, item.item_id, clip_id), item.item_id)

    def _undo_clip(self) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.undo_edit(self._model_id, item.item_id, progress),
            "Undoing edit",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Edit undone",
            ),
        )

    def _redo_clip(self) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.redo_edit(self._model_id, item.item_id, progress),
            "Redoing edit",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Edit redone",
            ),
        )

    def _mark_ready(self) -> None:
        item = self._current_training_item()
        if item is None:
            return
        self._run_editor_change(lambda: self._store.mark_item_ready(self._model_id, item.item_id), item.item_id)

    def _navigate_training_item(self, offset: int) -> None:
        current_row = self.training_list.currentRow()
        target_row = current_row + offset
        if 0 <= target_row < self.training_list.count():
            self.training_list.setCurrentRow(target_row)

    def _reset_item(self) -> None:
        item = self._current_training_item()
        if item is None or self._worker is not None:
            return
        self.clip_editor.stop_preview()
        self._start_worker(
            lambda progress: self._store.reset_item(self._model_id, item.item_id, progress),
            "Restoring original",
            lambda result: self._apply_worker_dataset(
                result,
                selected_training_id=item.item_id,
                status="Original restored",
            ),
        )

    def _apply_worker_dataset(
        self,
        result: object,
        *,
        selected_training_id: str = "",
        status: str,
    ) -> None:
        if not isinstance(result, ModelDataset):
            return
        self._dataset = result
        self._render(selected_training_id=selected_training_id)
        self._set_status(status)

    def _run_editor_change(self, action: Callable[[], ModelDataset], selected_training_id: str) -> None:
        try:
            self._dataset = action()
        except Exception as exc:
            self._set_status(f"Edit failed: {_last_error_line(exc)}")
            return
        self._render(selected_training_id=selected_training_id)

    def _current_training_item(self) -> ModelDatasetItem | None:
        selected_ids = _selected_item_ids(self.training_list)
        if len(selected_ids) != 1:
            return None
        return next((item for item in self._dataset.training_items if item.item_id == selected_ids[0]), None)

    def _apply_dataset_change(self, action, item_ids: tuple[str, ...]) -> None:
        if not self._model_id or not item_ids or self._worker is not None:
            return
        try:
            self._dataset = action(self._model_id, item_ids)
        except Exception as exc:
            self._set_status(f"Dataset failed: {_last_error_line(exc)}")
            return
        self._render()

    def _render(self, *, selected_training_id: str = "") -> None:
        self._populate_list(self.source_list, self._dataset.source_items, "SOURCE")
        self._populate_list(self.training_list, self._dataset.training_items, "WORKING")
        self.source_count_label.setText(str(len(self._dataset.source_items)))
        self.training_count_label.setText(str(len(self._dataset.training_items)))
        self._refresh_summary()
        if selected_training_id:
            _select_item(self.training_list, selected_training_id)
        self._sync_action_state()
        self._on_training_selection_changed()

    def _populate_list(self, list_widget: QListWidget, items: tuple[ModelDatasetItem, ...], badge_text: str) -> None:
        list_widget.clear()
        for dataset_item in items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, dataset_item.item_id)
            row = DatasetAudioRow(dataset_item, badge_text)
            row.apply_language()
            item.setSizeHint(row.sizeHint())
            list_widget.addItem(item)
            list_widget.setItemWidget(item, row)

    def _set_busy(self, is_busy: bool) -> None:
        self.progress_bar.setVisible(is_busy)
        self.clip_editor.set_busy(is_busy or self._externally_locked)
        self._set_enabled(not is_busy and not self._externally_locked and bool(self._model_id))

    def _set_enabled(self, is_enabled: bool) -> None:
        self.source_list.setEnabled(is_enabled)
        self.training_list.setEnabled(is_enabled)
        self.add_button.setEnabled(is_enabled)
        if not is_enabled:
            buttons = (
                self.remove_button,
                self.move_right_button,
                self.move_left_button,
                self.move_up_button,
                self.move_down_button,
            )
            for button in buttons:
                button.setEnabled(False)
        else:
            self._sync_action_state()

    def _sync_action_state(self) -> None:
        available = bool(self._model_id) and self._worker is None and not self._externally_locked
        source_selected = bool(self.source_list.selectedItems())
        training_selected = self.training_list.selectedItems()
        self.remove_button.setEnabled(available and source_selected)
        self.move_right_button.setEnabled(available and source_selected)
        self.move_left_button.setEnabled(available and bool(training_selected))
        single_training = len(training_selected) == 1
        selected_row = self.training_list.row(training_selected[0]) if single_training else -1
        self.move_up_button.setEnabled(available and single_training and selected_row > 0)
        self.move_down_button.setEnabled(
            available and single_training and 0 <= selected_row < self.training_list.count() - 1
        )
        _refresh_selected_rows(self.source_list)
        _refresh_selected_rows(self.training_list)

    def _on_training_selection_changed(self) -> None:
        self._sync_action_state()
        item = self._current_training_item()
        if item is None:
            self.clip_editor.stop_preview()
            self.clip_editor.hide()
            return
        self.clip_editor.set_item(item)
        current_row = self.training_list.currentRow()
        self.clip_editor.set_navigation_state(
            current_row > 0,
            0 <= current_row < self.training_list.count() - 1,
        )
        self.clip_editor.show()

    def stop_preview(self) -> None:
        self.clip_editor.stop_preview()

    def _close_editor(self) -> None:
        self.clip_editor.stop_preview()
        self.training_list.clearSelection()
        self.training_list.setCurrentRow(-1)
        self.clip_editor.hide()
        self._sync_action_state()

    def _set_status(self, text: str) -> None:
        set_translated_text(self.status_label, text)
        self.status_label.setVisible(bool(text))

    def _refresh_summary(self) -> None:
        total_duration = sum(item.training_duration_ms for item in self._dataset.training_items)
        set_translated_text(
            self.summary_label,
            "{files} files  /  {selected} selected  /  {duration}",
            files=len(self._dataset.items),
            selected=len(self._dataset.training_items),
            duration=format_duration(total_duration),
        )


class DatasetAudioList(QListWidget):
    files_dropped = Signal(tuple)

    def __init__(self, *, accept_files: bool = False) -> None:
        super().__init__()
        self.setObjectName("DatasetList")
        self.empty_text = ""
        self._empty_source = ""
        self._accept_files = accept_files
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSpacing(3)
        self.setAcceptDrops(accept_files)

    def set_empty_text(self, source: str) -> None:
        self._empty_source = source
        self.empty_text = tr(source)

    def apply_language(self) -> None:
        self.empty_text = tr(self._empty_source)
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() or not self.empty_text:
            return
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._accept_files and _event_audio_paths(event):
            self._set_dragging(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._accept_files and _event_audio_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_dragging(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = _event_audio_paths(event) if self._accept_files else ()
        self._set_dragging(False)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _set_dragging(self, is_dragging: bool) -> None:
        self.setProperty("dragging", is_dragging)
        self.style().unpolish(self)
        self.style().polish(self)


class DatasetAudioRow(QWidget):
    def __init__(self, item: ModelDatasetItem, badge_text: str) -> None:
        super().__init__()
        self.setObjectName("DatasetAudioRow")
        self.setProperty("selected", False)
        self.setFixedHeight(62)
        self._item = item
        self._badge_source = item.review_state.upper() if badge_text == "WORKING" else badge_text

        self.title_label = QLabel(item.source_name)
        self.title_label.setObjectName("DatasetItemTitle")
        self.title_label.setToolTip(str(item.working_path))
        self.metadata_label = QLabel(_item_metadata(item))
        self.metadata_label.setObjectName("DatasetItemMeta")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.metadata_label)

        self.badge_label = QLabel(tr(self._badge_source))
        self.badge_label.setObjectName("DatasetItemBadge")
        self.badge_label.setProperty("kind", self._badge_source.casefold())
        self.badge_label.setFixedSize(78, 24)
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.badge_label)

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def apply_language(self) -> None:
        self.metadata_label.setText(_item_metadata(self._item))
        set_translated_text(self.badge_label, self._badge_source)


def _dataset_icon_button(
    icon: str,
    tooltip: str,
    size: int = 30,
    object_name: str = "DatasetIconButton",
) -> SvgIconButton:
    button = SvgIconButton(icon, size=size)
    button.setObjectName(object_name)
    set_translated_tooltip(button, tooltip)
    return button


def _count_badge() -> QLabel:
    label = QLabel("0")
    label.setObjectName("DatasetCountBadge")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _selected_item_ids(list_widget: QListWidget) -> tuple[str, ...]:
    return tuple(
        str(list_widget.item(index).data(Qt.ItemDataRole.UserRole))
        for index in range(list_widget.count())
        if list_widget.item(index).isSelected()
    )


def _select_item(list_widget: QListWidget, item_id: str) -> None:
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == item_id:
            list_widget.setCurrentItem(item)
            return


def _refresh_selected_rows(list_widget: QListWidget) -> None:
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        row = list_widget.itemWidget(item)
        if isinstance(row, DatasetAudioRow):
            row.set_selected(item.isSelected())


def _event_audio_paths(event) -> tuple[Path, ...]:
    if not event.mimeData().hasUrls():
        return ()
    return tuple(
        Path(url.toLocalFile())
        for url in event.mimeData().urls()
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS
    )


def _item_metadata(item: ModelDatasetItem) -> str:
    displayed_duration = item.training_duration_ms
    duration = format_duration(displayed_duration) if displayed_duration > 0 else "--:--"
    extension = item.working_path.suffix.removeprefix(".").upper() or "AUDIO"
    mode_text = (
        tr("{count} CLIPS", count=len(item.clips))
        if item.training_mode == TRAINING_MODE_CLIPS
        else tr("FULL AUDIO")
    )
    parts = [mode_text]
    if item.has_denoised_audio:
        parts.append(tr("DENOISED"))
    if item.open_segment_count:
        parts.append(tr("{count} TO REVIEW", count=item.open_segment_count))
    parts.extend((duration, extension, _format_size(item.size_bytes)))
    return "  /  ".join(parts)


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def _last_error_line(error: object) -> str:
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"


def _build_review_queue(
    store: ModelDatasetStore,
    model_id: str,
    item_id: str,
    path: Path,
    threshold_db: int,
    min_silence_ms: int,
    padding_ms: int,
    max_clip_ms: int,
    progress: Callable[[int], None],
) -> ModelDataset:
    regions = detect_speech_regions(
        path,
        threshold_db=threshold_db,
        min_silence_ms=min_silence_ms,
        padding_ms=padding_ms,
        progress=lambda value: progress(round(value * 0.9)),
    )
    ranges = split_review_regions(
        ((region.start_ms, region.end_ms) for region in regions),
        max_duration_ms=max_clip_ms,
    )
    progress(95)
    dataset = store.replace_segment_candidates(model_id, item_id, ranges)
    progress(100)
    return dataset
