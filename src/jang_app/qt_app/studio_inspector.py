from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.qt_app.studio_reverb_editor import StudioReverbEditor
from jang_app.qt_app.widgets import (
    COMPACT_ICON_BUTTON_SIZE,
    FeedbackButton,
    ScrollSafeDoubleSpinBox,
    ScrollSafeSlider,
    SvgIconButton,
    TimecodeSpinBox,
)
from jang_app.services.i18n import tr
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    TRACK_AUDIO,
    TRACK_CONVERTED_VOCAL,
    TRACK_INSTRUMENTAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioClip,
    StudioTrack,
)


_ROLE_COLORS = {
    TRACK_ORIGINAL_VOCAL: "#d6a85f",
    TRACK_INSTRUMENTAL: "#58a88f",
    TRACK_CONVERTED_VOCAL: "#d2675a",
    TRACK_AUDIO: "#7788bb",
    TRACK_VIDEO: "#668cc4",
}


class ElidingLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self._full_text = ""

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_elision()

    def _refresh_elision(self) -> None:
        width = max(1, self.contentsRect().width())
        QLabel.setText(
            self,
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                width,
            ),
        )


class InspectorSection(QFrame):
    def __init__(
        self,
        title_key: str,
        *,
        collapsible: bool = False,
        expanded: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName("StudioInspectorSection")
        self._title_key = title_key
        self.title_label = QLabel()
        self.title_label.setObjectName("StudioInspectorSectionTitle")
        self.toggle_button: FeedbackButton | None = None

        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.addWidget(self.title_label, 1)
        if collapsible:
            self.toggle_button = FeedbackButton()
            self.toggle_button.setObjectName("StudioInspectorSectionToggle")
            self.toggle_button.setCheckable(True)
            self.toggle_button.setChecked(expanded)
            self.toggle_button.setFixedHeight(26)
            self.toggle_button.toggled.connect(self._set_expanded)
            self.header_layout.addWidget(self.toggle_button, 0)

        self.content = QWidget()
        self.content.setObjectName("StudioInspectorSectionContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(self.header_layout)
        layout.addWidget(self.content)
        self._set_expanded(expanded)
        self.apply_language()

    def add_header_action(self, widget: QWidget) -> None:
        self.header_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def apply_language(self) -> None:
        self.title_label.setText(tr(self._title_key))
        if self.toggle_button is not None:
            self.toggle_button.setText(tr("Hide") if self.toggle_button.isChecked() else tr("Show"))

    def _set_expanded(self, expanded: bool) -> None:
        self.content.setVisible(expanded)
        if self.toggle_button is not None:
            self.toggle_button.setText(tr("Hide") if expanded else tr("Show"))


class InspectorHeader(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StudioInspectorHeader")
        self.role_marker = QFrame()
        self.role_marker.setObjectName("StudioInspectorRoleMarker")
        self.role_marker.setFixedSize(8, 34)
        self.kind_label = QLabel()
        self.kind_label.setObjectName("StudioInspectorKind")
        self.name_label = ElidingLabel()
        self.name_label.setObjectName("StudioInspectorName")
        self.name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.meta_label = QLabel()
        self.meta_label.setObjectName("MutedText")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.meta_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.role_marker, 0)
        layout.addWidget(self.kind_label, 0)
        layout.addLayout(text_layout, 1)

    def set_content(self, kind: str, name: str, meta: str, role: str) -> None:
        self.kind_label.setText(kind.upper())
        self.name_label.setText(name)
        self.meta_label.setText(meta)
        color = _ROLE_COLORS.get(role, _ROLE_COLORS[TRACK_AUDIO])
        self.role_marker.setStyleSheet(f"background: {color}; border-radius: 4px;")


class StudioInspector(QFrame):
    clip_values_changed = Signal(str, int, int, int, float, bool, int, int)
    track_mix_changed = Signal(str, bool, bool, int, int)
    track_name_changed = Signal(str, str)
    open_location_requested = Signal(object)
    effect_changed = Signal(str, object)
    effect_remove_requested = Signal(str, str)

    EMPTY_PAGE = 0
    CLIP_PAGE = 1
    TRACK_PAGE = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StudioInspector")
        self.setMinimumWidth(280)
        self.setMaximumWidth(460)
        self._track: StudioTrack | None = None
        self._clip: StudioClip | None = None
        self._asset: StudioSoundAsset | None = None
        self._loading = False
        self._active_effect_id = ""
        self.effect_tab_buttons: dict[str, FeedbackButton] = {}
        self.effect_editors: dict[str, StudioReverbEditor] = {}

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.stack = QStackedWidget()
        self.stack.setObjectName("StudioInspectorStack")
        self.stack.addWidget(self._build_empty_page())
        self.stack.addWidget(self._build_clip_page())
        self.stack.addWidget(self._build_track_page())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(self.title_label)
        layout.addWidget(self.stack, 1)
        self.apply_language()
        self.clear_selection()

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("StudioInspectorEmptyPage")
        self.empty_title = QLabel()
        self.empty_title.setObjectName("CardTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_detail = QLabel()
        self.empty_detail.setObjectName("MutedText")
        self.empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_detail.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 28, 14, 28)
        layout.addStretch(1)
        layout.addWidget(self.empty_title)
        layout.addWidget(self.empty_detail)
        layout.addStretch(2)
        return page

    def _build_clip_page(self) -> QWidget:
        page = QWidget()
        self.clip_header = InspectorHeader()

        self.clip_section = InspectorSection("Clip")
        self.clip_mute_button = SvgIconButton(
            "speaker",
            size=COMPACT_ICON_BUTTON_SIZE,
        )
        self.clip_mute_button.setObjectName("TrackMuteButton")
        self.clip_mute_button.setCheckable(True)
        self.clip_mute_button.clicked.connect(self._toggle_clip_mute)
        self.clip_section.add_header_action(self.clip_mute_button)
        self.gain_slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-600, 120)
        self.gain_slider.valueChanged.connect(self._sync_gain_from_slider)
        self.gain_slider.sliderReleased.connect(self._emit_clip_values)
        self.gain_spin = ScrollSafeDoubleSpinBox()
        self.gain_spin.setObjectName("StudioInspectorGainSpin")
        self.gain_spin.setFixedWidth(112)
        self.gain_spin.setRange(-60.0, 12.0)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.editingFinished.connect(self._sync_gain_from_spin)
        self.gain_reset = FeedbackButton()
        self.gain_reset.setObjectName("StudioInspectorResetButton")
        self.gain_reset.clicked.connect(self._reset_gain)
        self.gain_label = QLabel()
        self.gain_label.setObjectName("MutedText")
        gain_header = QHBoxLayout()
        gain_header.setContentsMargins(0, 0, 0, 0)
        gain_header.addWidget(self.gain_label)
        gain_header.addStretch(1)
        gain_header.addWidget(self.gain_reset, 0)
        gain_row = QHBoxLayout()
        gain_row.setContentsMargins(0, 0, 0, 0)
        gain_row.addWidget(self.gain_slider, 1)
        gain_row.addWidget(self.gain_spin, 0)
        self.clip_section.content_layout.addLayout(gain_header)
        self.clip_section.content_layout.addLayout(gain_row)

        self.time_section = InspectorSection("Time")
        self.position_label, position_field = _field_widget("Timeline Position", TimecodeSpinBox())
        self.position_spin = position_field.control
        self.position_spin.editingFinished.connect(self._emit_clip_values)
        self.duration_label, duration_field = _value_field("Clip Duration")
        self.duration_value = duration_field.control
        time_grid = QGridLayout()
        time_grid.setContentsMargins(0, 0, 0, 0)
        time_grid.setHorizontalSpacing(8)
        time_grid.setVerticalSpacing(8)
        time_grid.addWidget(position_field, 0, 0)
        time_grid.addWidget(duration_field, 0, 1)
        self.time_section.content_layout.addLayout(time_grid)

        self.source_section = InspectorSection("Source Range", collapsible=True, expanded=False)
        self.in_label, in_field = _field_widget("Source In", TimecodeSpinBox())
        self.out_label, out_field = _field_widget("Source Out", TimecodeSpinBox())
        self.in_spin = in_field.control
        self.out_spin = out_field.control
        self.in_spin.editingFinished.connect(self._emit_clip_values)
        self.out_spin.editingFinished.connect(self._emit_clip_values)
        source_grid = QGridLayout()
        source_grid.setContentsMargins(0, 0, 0, 0)
        source_grid.setHorizontalSpacing(8)
        source_grid.addWidget(in_field, 0, 0)
        source_grid.addWidget(out_field, 1, 0)
        self.source_section.content_layout.addLayout(source_grid)

        self.fade_section = InspectorSection("Fade")
        self.fade_in_label, fade_in_field = _field_widget("Fade In", TimecodeSpinBox())
        self.fade_out_label, fade_out_field = _field_widget("Fade Out", TimecodeSpinBox())
        self.fade_in_spin = fade_in_field.control
        self.fade_out_spin = fade_out_field.control
        self.fade_in_spin.editingFinished.connect(self._emit_clip_values)
        self.fade_out_spin.editingFinished.connect(self._emit_clip_values)
        fade_grid = QGridLayout()
        fade_grid.setContentsMargins(0, 0, 0, 0)
        fade_grid.setHorizontalSpacing(8)
        fade_grid.addWidget(fade_in_field, 0, 0)
        fade_grid.addWidget(fade_out_field, 1, 0)
        self.fade_section.content_layout.addLayout(fade_grid)

        self.open_button = SvgIconButton("folder", size=32)
        self.open_button.setObjectName("ControlIconButton")
        self.open_button.clicked.connect(self._open_asset_location)
        actions = QHBoxLayout()
        actions.addWidget(self.open_button, 0)
        actions.addStretch(1)

        self.clip_properties_page = QWidget()
        properties_layout = QVBoxLayout(self.clip_properties_page)
        properties_layout.setContentsMargins(0, 0, 0, 0)
        properties_layout.setSpacing(10)
        properties_layout.addWidget(self.clip_section)
        properties_layout.addWidget(self.time_section)
        properties_layout.addWidget(self.source_section)
        properties_layout.addWidget(self.fade_section)
        properties_layout.addLayout(actions)
        properties_layout.addStretch(1)

        self.clip_tabs = QFrame()
        self.clip_tabs.setObjectName("StudioInspectorTabs")
        self.clip_tabs_layout = QHBoxLayout(self.clip_tabs)
        self.clip_tabs_layout.setContentsMargins(3, 3, 3, 3)
        self.clip_tabs_layout.setSpacing(2)
        self.clip_tab_button = FeedbackButton()
        self.clip_tab_button.setObjectName("StudioInspectorTab")
        self.clip_tab_button.setCheckable(True)
        self.clip_tab_button.clicked.connect(lambda: self.open_effect_tab(""))
        self.clip_tabs_layout.addWidget(self.clip_tab_button)
        self.clip_tabs_layout.addStretch(1)

        self.clip_detail_stack = QStackedWidget()
        self.clip_detail_stack.setObjectName("StudioInspectorDetailStack")
        self.clip_detail_stack.addWidget(self.clip_properties_page)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.clip_header)
        layout.addWidget(self.clip_tabs)
        layout.addWidget(self.clip_detail_stack, 1)
        return page

    def _build_track_page(self) -> QWidget:
        page = QWidget()
        self.track_header = InspectorHeader()
        self.mix_section = InspectorSection("Mix")
        self.mute_button = FeedbackButton()
        self.mute_button.setCheckable(True)
        self.solo_button = FeedbackButton()
        self.solo_button.setCheckable(True)
        self.mute_button.clicked.connect(self._emit_track_mix)
        self.solo_button.clicked.connect(self._emit_track_mix)
        buttons = QHBoxLayout()
        buttons.addWidget(self.mute_button, 1)
        buttons.addWidget(self.solo_button, 1)
        self.volume_label, self.volume_slider, self.volume_value = _slider_field(0, 200, 100)
        self.pan_label, self.pan_slider, self.pan_value = _slider_field(-100, 100, 0)
        self.volume_slider.valueChanged.connect(self._update_track_value_labels)
        self.pan_slider.valueChanged.connect(self._update_track_value_labels)
        self.volume_slider.sliderReleased.connect(self._emit_track_mix)
        self.pan_slider.sliderReleased.connect(self._emit_track_mix)
        self.mix_section.content_layout.addLayout(buttons)
        volume_header = QHBoxLayout()
        volume_header.addWidget(self.volume_label)
        volume_header.addStretch(1)
        volume_header.addWidget(self.volume_value)
        pan_header = QHBoxLayout()
        pan_header.addWidget(self.pan_label)
        pan_header.addStretch(1)
        pan_header.addWidget(self.pan_value)
        self.mix_section.content_layout.addLayout(volume_header)
        self.mix_section.content_layout.addWidget(self.volume_slider)
        self.mix_section.content_layout.addLayout(pan_header)
        self.mix_section.content_layout.addWidget(self.pan_slider)

        self.track_section = InspectorSection("Track")
        self.track_name_label = QLabel()
        self.track_name_label.setObjectName("MutedText")
        self.track_name_edit = QLineEdit()
        self.track_name_edit.editingFinished.connect(self._emit_track_name)
        self.track_meta = QLabel()
        self.track_meta.setObjectName("MutedText")
        self.track_meta.setWordWrap(True)
        self.track_section.content_layout.addWidget(self.track_name_label)
        self.track_section.content_layout.addWidget(self.track_name_edit)
        self.track_section.content_layout.addWidget(self.track_meta)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.track_header)
        layout.addWidget(self.mix_section)
        layout.addWidget(self.track_section)
        layout.addStretch(1)
        return page

    def set_selection(
        self,
        track: StudioTrack | None,
        clip: StudioClip | None,
        asset: StudioSoundAsset | None,
    ) -> None:
        self._loading = True
        previous_clip_id = self._clip.clip_id if self._clip is not None else ""
        self._track = track
        self._clip = clip
        self._asset = asset
        if clip is not None and track is not None:
            if previous_clip_id != clip.clip_id:
                self._active_effect_id = ""
            self._load_clip(track, clip, asset)
            self._sync_effect_tabs(clip)
            self.stack.setCurrentIndex(self.CLIP_PAGE)
        elif track is not None:
            self._active_effect_id = ""
            self._load_track(track)
            self.stack.setCurrentIndex(self.TRACK_PAGE)
        else:
            self.stack.setCurrentIndex(self.EMPTY_PAGE)
        self._loading = False

    def clear_selection(self) -> None:
        self.set_selection(None, None, None)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_button.set_theme_mode(theme_mode)
        self.clip_mute_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Inspector"))
        self.clip_tab_button.setText(tr("Clip"))
        self.empty_title.setText(tr("Nothing selected"))
        self.empty_detail.setText(tr("Select a clip or track on the timeline to edit its properties."))
        for section in (
            self.clip_section,
            self.time_section,
            self.source_section,
            self.fade_section,
            self.mix_section,
            self.track_section,
        ):
            section.apply_language()
        self._refresh_clip_mute_control()
        self.gain_label.setText(tr("Clip Gain"))
        self.gain_reset.setText(tr("Reset"))
        self.position_label.setText(tr("Timeline Position"))
        self.duration_label.setText(tr("Clip Duration"))
        self.in_label.setText(tr("Source In"))
        self.out_label.setText(tr("Source Out"))
        self.fade_in_label.setText(tr("Fade In"))
        self.fade_out_label.setText(tr("Fade Out"))
        self.mute_button.setText(tr("Mute"))
        self.solo_button.setText(tr("Solo"))
        self.volume_label.setText(tr("Track Volume"))
        self.pan_label.setText(tr("Pan"))
        self.track_name_label.setText(tr("Track Name"))
        set_translated_tooltip(self.open_button, "Open file location")
        for editor in self.effect_editors.values():
            editor.apply_language()
        self._refresh_selection_text()

    def effect_tab_ids(self) -> tuple[str, ...]:
        return tuple(self.effect_tab_buttons)

    def open_effect_tab(self, effect_id: str) -> None:
        if effect_id and effect_id not in self.effect_editors:
            return
        self._active_effect_id = effect_id
        self.clip_detail_stack.setCurrentIndex(
            0 if not effect_id else list(self.effect_editors).index(effect_id) + 1
        )
        self.clip_tab_button.setChecked(not effect_id)
        for current_id, button in self.effect_tab_buttons.items():
            button.setChecked(current_id == effect_id)

    def _sync_effect_tabs(self, clip: StudioClip) -> None:
        effects = {
            effect.effect_id: effect
            for effect in clip.effects
            if effect.kind == "reverb"
        }
        for effect_id in tuple(self.effect_tab_buttons):
            if effect_id in effects:
                continue
            button = self.effect_tab_buttons.pop(effect_id)
            editor = self.effect_editors.pop(effect_id)
            self.clip_tabs_layout.removeWidget(button)
            self.clip_detail_stack.removeWidget(editor)
            button.hide()
            editor.hide()
            button.deleteLater()
            editor.deleteLater()

        for effect_id, effect in effects.items():
            editor = self.effect_editors.get(effect_id)
            if editor is not None:
                editor.set_effect(effect)
                continue
            button = FeedbackButton(tr("Reverb"))
            button.setObjectName("StudioInspectorTab")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, effect_id=effect_id: self.open_effect_tab(effect_id)
            )
            self.clip_tabs_layout.insertWidget(
                max(1, self.clip_tabs_layout.count() - 1),
                button,
            )
            editor = StudioReverbEditor()
            editor.set_effect(effect)
            editor.effect_changed.connect(self._forward_effect_changed)
            editor.remove_requested.connect(self._forward_effect_remove)
            self.clip_detail_stack.addWidget(editor)
            self.effect_tab_buttons[effect_id] = button
            self.effect_editors[effect_id] = editor
        if self._active_effect_id not in self.effect_editors:
            self._active_effect_id = ""
        self.open_effect_tab(self._active_effect_id)

    def _forward_effect_changed(self, effect) -> None:
        if self._clip is None:
            return
        self._active_effect_id = effect.effect_id
        self.effect_changed.emit(self._clip.clip_id, effect)

    def _forward_effect_remove(self, effect_id: str) -> None:
        if self._clip is None:
            return
        self.effect_remove_requested.emit(self._clip.clip_id, effect_id)

    def _load_clip(
        self,
        track: StudioTrack,
        clip: StudioClip,
        asset: StudioSoundAsset | None,
    ) -> None:
        limit = max(clip.source_end_ms, asset.duration_ms if asset is not None else 0)
        self.in_spin.setMaximum(limit)
        self.out_spin.setMaximum(limit)
        self.fade_in_spin.setMaximum(clip.duration_ms)
        self.fade_out_spin.setMaximum(clip.duration_ms)
        self.position_spin.setValue(clip.timeline_start_ms)
        self.in_spin.setValue(clip.source_start_ms)
        self.out_spin.setValue(clip.source_end_ms)
        self.fade_in_spin.setValue(clip.fade_in_ms)
        self.fade_out_spin.setValue(clip.fade_out_ms)
        self.gain_spin.setValue(clip.gain_db)
        self.gain_slider.setValue(round(clip.gain_db * 10))
        self.clip_mute_button.setChecked(clip.muted)
        self._refresh_clip_mute_control()
        self.duration_value.setText(_format_timecode(clip.duration_ms))
        self.open_button.setEnabled(bool(asset and asset.path.is_file()))
        self._refresh_selection_text()

    def _load_track(self, track: StudioTrack) -> None:
        self.mute_button.setChecked(track.muted)
        self.solo_button.setChecked(track.solo)
        self.volume_slider.setValue(track.volume_percent)
        self.pan_slider.setValue(track.pan_percent)
        self.track_name_edit.setText(track.name)
        self.track_name_edit.setCursorPosition(0)
        self.track_name_edit.setReadOnly(track.role != TRACK_AUDIO)
        self._update_track_value_labels()
        self._refresh_selection_text()

    def _refresh_selection_text(self) -> None:
        if self._clip is not None and self._track is not None:
            name = self._asset.label if self._asset is not None else tr("Missing sound")
            meta = f"{tr(_role_name(self._clip.asset.role))}  /  {_format_timecode(self._clip.duration_ms)}"
            self.clip_header.set_content(tr("Clip"), name, meta, self._clip.asset.role)
        if self._track is not None:
            meta = tr("{count} clips").format(count=len(self._track.clips))
            self.track_header.set_content(
                tr("Track"),
                self._track.name,
                f"{tr(_role_name(self._track.role))}  /  {meta}",
                self._track.role,
            )
            self.track_meta.setText(f"{tr(_role_name(self._track.role))}  /  {meta}")

    def _sync_gain_from_slider(self, value: int) -> None:
        self.gain_spin.setValue(value / 10.0)
        if not self.gain_slider.isSliderDown():
            self._emit_clip_values()

    def _sync_gain_from_spin(self) -> None:
        self._loading = True
        self.gain_slider.setValue(round(self.gain_spin.value() * 10))
        self._loading = False
        self._emit_clip_values()

    def _reset_gain(self) -> None:
        self._loading = True
        self.gain_spin.setValue(0.0)
        self.gain_slider.setValue(0)
        self._loading = False
        self._emit_clip_values()

    def _toggle_clip_mute(self) -> None:
        self._refresh_clip_mute_control()
        self._emit_clip_values()

    def _refresh_clip_mute_control(self) -> None:
        tooltip = "Unmute Clip" if self.clip_mute_button.isChecked() else "Mute Clip"
        set_translated_tooltip(self.clip_mute_button, tooltip)
        self.clip_mute_button.setAccessibleName(tr(tooltip))

    def _emit_clip_values(self) -> None:
        if self._loading or self._clip is None:
            return
        self.clip_values_changed.emit(
            self._clip.clip_id,
            self.position_spin.value(),
            self.in_spin.value(),
            self.out_spin.value(),
            self.gain_spin.value(),
            self.clip_mute_button.isChecked(),
            self.fade_in_spin.value(),
            self.fade_out_spin.value(),
        )

    def _open_asset_location(self) -> None:
        if self._asset is not None:
            self.open_location_requested.emit(Path(self._asset.path))

    def _update_track_value_labels(self) -> None:
        self.volume_value.setText(f"{self.volume_slider.value()}%")
        pan = self.pan_slider.value()
        self.pan_value.setText(tr("Center") if pan == 0 else f"{'L' if pan < 0 else 'R'} {abs(pan)}")
        if not self._loading:
            if not self.volume_slider.isSliderDown() and not self.pan_slider.isSliderDown():
                self._emit_track_mix()

    def _emit_track_mix(self) -> None:
        if self._loading or self._track is None:
            return
        self.track_mix_changed.emit(
            self._track.track_id,
            self.mute_button.isChecked(),
            self.solo_button.isChecked(),
            self.volume_slider.value(),
            self.pan_slider.value(),
        )

    def _emit_track_name(self) -> None:
        if self._loading or self._track is None or self._track.role != TRACK_AUDIO:
            return
        name = self.track_name_edit.text().strip()
        if name and name != self._track.name:
            self.track_name_changed.emit(self._track.track_id, name)


class _FieldWidget(QWidget):
    def __init__(self, label: QLabel, control: QWidget) -> None:
        super().__init__()
        self.control = control
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(label)
        layout.addWidget(control)


def _field_widget(label_key: str, control: QWidget) -> tuple[QLabel, _FieldWidget]:
    label = QLabel(tr(label_key))
    label.setObjectName("MutedText")
    return label, _FieldWidget(label, control)


def _value_field(label_key: str) -> tuple[QLabel, _FieldWidget]:
    label = QLabel(tr(label_key))
    label.setObjectName("MutedText")
    value = QLabel("00:00.000")
    value.setObjectName("StudioInspectorReadOnlyValue")
    return label, _FieldWidget(label, value)


def _slider_field(
    minimum: int,
    maximum: int,
    value: int,
) -> tuple[QLabel, ScrollSafeSlider, QLabel]:
    label = QLabel()
    label.setObjectName("MutedText")
    slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    value_label = QLabel()
    value_label.setObjectName("StudioInspectorSliderValue")
    return label, slider, value_label


def _format_timecode(duration_ms: int) -> str:
    total_ms = max(0, int(duration_ms))
    milliseconds = total_ms % 1_000
    total_seconds = total_ms // 1_000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{total_minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _role_name(role: str) -> str:
    return {
        TRACK_ORIGINAL_VOCAL: "Original Vocal",
        TRACK_INSTRUMENTAL: "Instrumental",
        TRACK_CONVERTED_VOCAL: "Converted Vocal",
        TRACK_AUDIO: "Audio",
        TRACK_VIDEO: "Video",
    }.get(role, "Audio")
