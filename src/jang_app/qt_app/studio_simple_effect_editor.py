from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.widgets import (
    DangerIconButton,
    InfoPopoverButton,
    ScrollSafeComboBox,
    ScrollSafeSpinBox,
    ToggleSwitchButton,
)
from jang_app.services.i18n import tr
from jang_app.services.studio_session import StudioEffect


@dataclass(frozen=True)
class SimpleEffectField:
    name: str
    label: str
    minimum: int
    maximum: int
    step: int
    suffix: str
    detail: str
    recommendation: str
    choices: tuple[tuple[object, str], ...] = ()


@dataclass(frozen=True)
class SimpleEffectPreset:
    key: str
    name: str
    settings: object


@dataclass(frozen=True)
class SimpleEffectEditorSpec:
    effect_kind: str
    settings_field: str
    settings_factory: Callable[..., object]
    custom_preset: str
    presets: tuple[SimpleEffectPreset, ...]
    groups: tuple[tuple[str, tuple[str, ...]], ...]
    fields: tuple[SimpleEffectField, ...]
    preset_detail: str
    preset_recommendation: str


class StudioSimpleEffectEditor(QWidget):
    effect_changed = Signal(object)
    remove_requested = Signal(str)

    def __init__(
        self,
        spec: SimpleEffectEditorSpec,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StudioSimpleEffectEditor")
        self._spec = spec
        self._fields = {field.name: field for field in spec.fields}
        self._effect: StudioEffect | None = None
        self._loading = False
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(24)
        self._change_timer.timeout.connect(self._emit_changed)
        self.controls: dict[str, ScrollSafeSpinBox | ScrollSafeComboBox] = {}
        self.group_title_labels: dict[str, QLabel] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.field_info_buttons: dict[str, InfoPopoverButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_action_bar())
        layout.addWidget(self._build_preset_section())
        for title, fields in spec.groups:
            layout.addWidget(self._build_section(title, fields))
        layout.addStretch(1)
        self.apply_language()

    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("StudioReverbActionBar")
        self.enabled_button = ToggleSwitchButton()
        self.enabled_button.setChecked(True)
        self.enabled_button.toggled.connect(self._set_effect_enabled)
        self.remove_button = DangerIconButton(size=30)
        self.remove_button.clicked.connect(self._request_remove)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addStretch(1)
        layout.addWidget(self.enabled_button)
        layout.addWidget(self.remove_button)
        return bar

    def _build_preset_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("StudioReverbPresetSection")
        self.preset_label = QLabel()
        self.preset_label.setObjectName("StudioInspectorSectionTitle")
        self.preset_info = InfoPopoverButton()
        self.preset_combo = ScrollSafeComboBox()
        self.preset_combo.setObjectName("StudioReverbPresetCombo")
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.preset_combo.currentIndexChanged.connect(self._apply_selected_preset)
        layout = QHBoxLayout(section)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        layout.addWidget(self.preset_label)
        layout.addWidget(self.preset_info)
        layout.addWidget(self.preset_combo, 1)
        return section

    def _build_section(self, title: str, field_names: tuple[str, ...]) -> QFrame:
        section = QFrame()
        section.setObjectName("StudioReverbSection")
        title_label = QLabel()
        title_label.setObjectName("StudioInspectorSectionTitle")
        self.group_title_labels[title] = title_label
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, field_name in enumerate(field_names):
            field_spec = self._fields[field_name]
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            label = QLabel()
            label.setObjectName("MutedText")
            label.setWordWrap(False)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            info = InfoPopoverButton()
            info.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(4)
            label_row.addWidget(label, 1)
            label_row.addWidget(info, 0, Qt.AlignmentFlag.AlignRight)
            control = ScrollSafeComboBox() if field_spec.choices else ScrollSafeSpinBox()
            control.setObjectName("StudioReverbControl")
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            if isinstance(control, ScrollSafeComboBox):
                for value, choice_label in field_spec.choices:
                    control.addItem(tr(choice_label), value)
                control.currentIndexChanged.connect(self._queue_changed)
            else:
                control.setRange(field_spec.minimum, field_spec.maximum)
                control.setSingleStep(field_spec.step)
                control.setSuffix(field_spec.suffix)
                control.valueChanged.connect(self._queue_changed)
                control.editingFinished.connect(self._flush_changed)
            self.controls[field_name] = control
            self.field_labels[field_name] = label
            self.field_info_buttons[field_name] = info
            field_layout.addLayout(label_row)
            field_layout.addWidget(control)
            grid.addWidget(field, index // 2, index % 2)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 12, 12, 12)
        section_layout.setSpacing(8)
        section_layout.addWidget(title_label)
        section_layout.addLayout(grid)
        return section

    def apply_language(self) -> None:
        selected = self.preset_combo.currentData()
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_label.setText(tr("Preset"))
        self.preset_info.set_content(
            tr("Preset"),
            tr(self._spec.preset_detail),
            tr(self._spec.preset_recommendation),
        )
        self.preset_combo.clear()
        for preset in self._spec.presets:
            self.preset_combo.addItem(tr(preset.name), preset.key)
        self.preset_combo.addItem(tr("Custom"), self._spec.custom_preset)
        self._select_preset(str(selected or self._spec.custom_preset))
        del blocker
        for title, label in self.group_title_labels.items():
            label.setText(tr(title))
        for name, field_spec in self._fields.items():
            title = tr(field_spec.label)
            detail = tr(field_spec.detail)
            recommendation = tr(field_spec.recommendation)
            control = self.controls[name]
            if isinstance(control, ScrollSafeComboBox):
                selected_value = control.currentData()
                choice_blocker = QSignalBlocker(control)
                control.clear()
                for value, choice_label in field_spec.choices:
                    control.addItem(tr(choice_label), value)
                selected_index = control.findData(selected_value)
                control.setCurrentIndex(max(0, selected_index))
                del choice_blocker
            self.field_labels[name].setText(title)
            self.field_info_buttons[name].set_content(title, detail, recommendation)
            control.setToolTip(f"{detail}\n\n{recommendation}")
        self.remove_button.setToolTip(tr("Remove Effect"))
        self.remove_button.setAccessibleName(tr("Remove Effect"))
        self._sync_enabled_button(self.enabled_button.isChecked())

    def set_theme_mode(self, theme_mode: str) -> None:
        self.enabled_button.set_theme_mode(theme_mode)
        self.remove_button.set_theme_mode(theme_mode)

    def set_effect(self, effect: StudioEffect) -> None:
        if effect.kind != self._spec.effect_kind:
            raise ValueError("Effect kind does not match this editor.")
        self._change_timer.stop()
        self._loading = True
        self._effect = effect
        settings = getattr(effect, self._spec.settings_field)
        for name, control in self.controls.items():
            self._set_control_value(control, getattr(settings, name))
        self._select_preset(self._matching_preset(settings))
        blocker = QSignalBlocker(self.enabled_button)
        self.enabled_button.setChecked(effect.enabled)
        del blocker
        self._sync_enabled_button(effect.enabled)
        self._loading = False

    def _matching_preset(self, settings: object) -> str:
        return next(
            (
                preset.key
                for preset in self._spec.presets
                if preset.settings == settings
            ),
            self._spec.custom_preset,
        )

    def _select_preset(self, key: str) -> None:
        index = self.preset_combo.findData(key)
        if index < 0:
            index = self.preset_combo.findData(self._spec.custom_preset)
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_combo.setCurrentIndex(index)
        del blocker

    def _apply_selected_preset(self, _index: int) -> None:
        if self._loading:
            return
        key = str(self.preset_combo.currentData())
        settings = next(
            (preset.settings for preset in self._spec.presets if preset.key == key),
            None,
        )
        if settings is None:
            return
        self._change_timer.stop()
        self._loading = True
        for name, control in self.controls.items():
            self._set_control_value(control, getattr(settings, name))
        self._loading = False
        self._emit_changed()

    def _current_settings(self) -> object:
        return self._spec.settings_factory(
            **{
                name: self._control_value(control)
                for name, control in self.controls.items()
            }
        )

    @staticmethod
    def _control_value(control: ScrollSafeSpinBox | ScrollSafeComboBox) -> object:
        if isinstance(control, ScrollSafeComboBox):
            return control.currentData()
        return control.value()

    @staticmethod
    def _set_control_value(
        control: ScrollSafeSpinBox | ScrollSafeComboBox,
        value: object,
    ) -> None:
        if isinstance(control, ScrollSafeComboBox):
            index = control.findData(value)
            control.setCurrentIndex(max(0, index))
            return
        control.setValue(int(value))

    def _emit_changed(self) -> None:
        if self._loading or self._effect is None:
            return
        self._emit_effect(
            replace(
                self._effect,
                **{self._spec.settings_field: self._current_settings()},
            )
        )

    def _emit_effect(self, effect: StudioEffect) -> None:
        self._effect = effect
        self.effect_changed.emit(effect)

    def _set_effect_enabled(self, enabled: bool) -> None:
        self._sync_enabled_button(enabled)
        if self._loading or self._effect is None:
            return
        self._change_timer.stop()
        self._emit_effect(
            replace(
                self._effect,
                enabled=enabled,
                **{self._spec.settings_field: self._current_settings()},
            )
        )

    def _sync_enabled_button(self, enabled: bool) -> None:
        self.enabled_button.setToolTip(tr("Enable or bypass this effect"))
        self.enabled_button.setAccessibleName(
            tr("Effect enabled") if enabled else tr("Effect bypassed")
        )

    def _queue_changed(self, _value: int) -> None:
        if not self._loading:
            self._select_preset(self._spec.custom_preset)
            self._change_timer.start()

    def _flush_changed(self) -> None:
        if self._loading:
            return
        self._change_timer.stop()
        self._emit_changed()

    def _request_remove(self) -> None:
        if self._effect is not None:
            self.remove_requested.emit(self._effect.effect_id)
