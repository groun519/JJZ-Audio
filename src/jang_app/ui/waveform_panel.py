from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from jang_app.config import SEPARATION_OUTPUT_DIR
from jang_app.services.audio_export import AudioExportError, AudioMixSource, export_audio_file, export_mix
from jang_app.services.audio_player import AudioPlaybackError, AudioPlayer
from jang_app.services.output_catalog import OutputSoundSet, load_output_sound_set, scan_output_sound_sets
from jang_app.ui.controls import CanvasButton
from jang_app.ui.theme import AppTheme, DEFAULT_THEME
from jang_app.ui.waveform_track import WaveformTrack, _format_time


PLAY_ICON = "\u25b6"
STOP_ICON = "\u25a0"
EXPORT_DIR_NAME = "exports"
MIX_OUTPUT_NAME = "mix_unmuted.wav"


class WaveformPanel(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        theme: AppTheme = DEFAULT_THEME,
        output_root: Path = SEPARATION_OUTPUT_DIR,
        on_sound_set_selected: Callable[[OutputSoundSet], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=16)
        self._theme = theme
        self._output_root = output_root
        self._on_sound_set_selected = on_sound_set_selected
        self._player = AudioPlayer()
        self._position_ms = 0
        self._duration_ms = 0
        self._export_base_dir: Path | None = None
        self._sound_sets: list[OutputSoundSet] = []
        self._sound_set_by_label: dict[str, OutputSoundSet] = {}
        self._converted_path_by_label: dict[str, Path] = {}
        self._current_sound_set: OutputSoundSet | None = None
        self._selected_sound_set = tk.StringVar()
        self._selected_converted = tk.StringVar()
        self._is_syncing_sound_set = False
        self._is_syncing_converted = False
        self._poll_after_id: str | None = None
        self._volume_after_id: str | None = None

        self.columnconfigure(0, weight=1)
        for row in (1, 2, 3):
            self.rowconfigure(row, weight=1)

        self._build_header()
        self._vocals = self._add_track(1, "Original Vocal")
        self._instrumental = self._add_track(2, "Instrumental")
        self._converted = self._add_track(3, "Converted Vocal")
        self.show_empty()
        self.refresh_output_sets(select_latest=True, notify=True)

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self._play_button.configure(
            bg=theme.panel_bg,
        )
        self._play_button.set_theme(theme)
        self._export_mix_button.set_theme(theme)
        self._vocals.set_theme(theme)
        self._instrumental.set_theme(theme)
        self._converted.set_theme(theme)

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="PanelBody.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        browser = ttk.Frame(header, style="PanelBody.TFrame")
        browser.grid(row=0, column=0, sticky="ew")
        browser.columnconfigure(0, weight=1)
        ttk.Label(browser, text="OUTPUT SESSION", style="Eyebrow.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(browser, text="Output Sounds", style="PanelTitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._sound_set_selector = ttk.Combobox(
            browser,
            textvariable=self._selected_sound_set,
            width=34,
            state="readonly",
        )
        self._sound_set_selector.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._sound_set_selector.bind("<<ComboboxSelected>>", self._handle_sound_set_selected)

        self._export_status_text = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._export_status_text, style="Status.TLabel", wraplength=420).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(8, 0),
        )
        controls = ttk.Frame(header, style="PanelBody.TFrame")
        controls.grid(row=0, column=1, sticky="ne", padx=(22, 0))

        self._time_text = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(controls, textvariable=self._time_text, style="StatusStrong.TLabel").grid(row=0, column=0, padx=(0, 10))
        self._play_button = CanvasButton(
            controls,
            text=PLAY_ICON,
            command=self._toggle_playback,
            theme=self._theme,
            variant="primary",
            width=38,
            height=32,
        )
        self._play_button.grid(row=0, column=1)
        self._export_mix_button = CanvasButton(
            controls,
            text="Export Mix",
            command=self._export_mix,
            theme=self._theme,
            variant="primary",
            width=104,
            height=32,
        )
        self._export_mix_button.grid(row=0, column=2, padx=(8, 0))

    def _add_track(self, row: int, label: str) -> WaveformTrack:
        header_extra_builder = self._build_converted_selector if label == "Converted Vocal" else None
        track = WaveformTrack(
            self,
            label,
            self._seek,
            self._handle_mute_changed,
            self._handle_volume_changed,
            lambda: self._export_track(label, track),
            header_extra_builder,
            self._theme,
        )
        track.grid(row=row, column=0, sticky="nsew", pady=(14, 0))
        return track

    def _build_converted_selector(self, parent: ttk.Frame) -> tk.Widget:
        self._converted_selector = ttk.Combobox(
            parent,
            textvariable=self._selected_converted,
            width=30,
            state="disabled",
        )
        self._converted_selector.bind("<<ComboboxSelected>>", self._handle_converted_selected)
        return self._converted_selector

    def show_empty(self) -> None:
        self.stop_playback()
        self._export_base_dir = None
        self._current_sound_set = None
        self._selected_sound_set.set("")
        self._set_converted_options(())
        self._export_status_text.set("")
        self._vocals.set_label("Original Vocal")
        self._instrumental.set_label("Instrumental")
        self._converted.set_label("Converted Vocal")
        self._vocals.show_empty("Waiting for vocals")
        self._instrumental.show_empty("Waiting for instrumental")
        self._converted.show_empty("Convert vocal to preview here")
        self._sync_duration()
        self._sync_export_buttons()

    def show_files(self, vocals_path: Path, accompaniment_path: Path) -> None:
        sound_set = load_output_sound_set(vocals_path.parent, self._output_root)
        if sound_set is None:
            self._current_sound_set = None
            self._selected_sound_set.set("")
            self._load_paths(vocals_path, accompaniment_path, ())
            return
        self.refresh_output_sets(select_job_dir=sound_set.job_dir, notify=False)

    def show_converted_vocal(self, converted_vocals_path: Path, _accompaniment_path: Path) -> None:
        self.refresh_output_sets(
            select_job_dir=converted_vocals_path.parent,
            selected_converted_path=converted_vocals_path,
            notify=False,
        )

    def set_output_root(self, output_root: Path) -> None:
        self._output_root = output_root
        self.refresh_output_sets(select_latest=True, notify=True)

    def refresh_output_sets(
        self,
        select_job_dir: Path | None = None,
        selected_converted_path: Path | None = None,
        select_latest: bool = False,
        notify: bool = False,
    ) -> None:
        self._sound_sets = scan_output_sound_sets(self._output_root)
        self._sound_set_by_label = {sound_set.label: sound_set for sound_set in self._sound_sets}
        labels = list(self._sound_set_by_label)
        self._sound_set_selector.configure(values=labels, state="readonly" if labels else "disabled")

        selected = self._resolve_selected_sound_set(select_job_dir, select_latest)
        if selected is None:
            if not labels:
                self.show_empty()
            return

        self._load_sound_set(selected, selected_converted_path)
        if notify and self._on_sound_set_selected is not None:
            self._on_sound_set_selected(selected)

    def _resolve_selected_sound_set(self, select_job_dir: Path | None, select_latest: bool) -> OutputSoundSet | None:
        if select_job_dir is not None:
            selected_job_dir = select_job_dir.expanduser().resolve()
            for sound_set in self._sound_sets:
                if sound_set.job_dir == selected_job_dir:
                    return sound_set

        if self._current_sound_set is not None:
            for sound_set in self._sound_sets:
                if sound_set.job_dir == self._current_sound_set.job_dir:
                    return sound_set

        if select_latest and self._sound_sets:
            return self._sound_sets[0]
        return None

    def _load_sound_set(self, sound_set: OutputSoundSet, selected_converted_path: Path | None = None) -> None:
        self._current_sound_set = sound_set
        self._load_paths(sound_set.vocals_path, sound_set.instrumental_path, sound_set.converted_vocal_paths, selected_converted_path)
        self._is_syncing_sound_set = True
        try:
            self._selected_sound_set.set(sound_set.label)
        finally:
            self._is_syncing_sound_set = False

    def _load_paths(
        self,
        vocals_path: Path,
        instrumental_path: Path,
        converted_paths: tuple[Path, ...],
        selected_converted_path: Path | None = None,
    ) -> None:
        self.stop_playback()
        self._export_base_dir = vocals_path.parent
        self._export_status_text.set("")
        self._vocals.set_label("Original Vocal")
        self._instrumental.set_label("Instrumental")
        self._converted.set_label("Converted Vocal")
        self._vocals.show_file(vocals_path, self._player.duration_ms(vocals_path))
        self._instrumental.show_file(instrumental_path, self._player.duration_ms(instrumental_path))
        self._set_converted_options(converted_paths, selected_converted_path)
        self._sync_duration()
        self._sync_export_buttons()

    def _set_converted_options(
        self,
        converted_paths: tuple[Path, ...],
        selected_converted_path: Path | None = None,
    ) -> None:
        self._converted_path_by_label = {}
        labels: list[str] = []
        for path in converted_paths:
            label = _converted_label(path)
            unique_label = _unique_label(label, self._converted_path_by_label)
            self._converted_path_by_label[unique_label] = path
            labels.append(unique_label)

        self._converted_selector.configure(values=labels, state="readonly" if labels else "disabled")
        selected_label = self._resolve_selected_converted_label(selected_converted_path, labels)
        self._is_syncing_converted = True
        try:
            self._selected_converted.set(selected_label)
        finally:
            self._is_syncing_converted = False

        selected_path = self._converted_path_by_label.get(selected_label)
        if selected_path is None:
            self._converted.show_empty("Convert vocal to preview here")
            return
        self._converted.show_file(selected_path, self._player.duration_ms(selected_path))

    def _resolve_selected_converted_label(self, selected_path: Path | None, labels: list[str]) -> str:
        if selected_path is not None:
            resolved = selected_path.expanduser().resolve()
            for label, path in self._converted_path_by_label.items():
                if path.expanduser().resolve() == resolved:
                    return label
        if self._selected_converted.get() in labels:
            return self._selected_converted.get()
        return labels[0] if labels else ""

    def _handle_sound_set_selected(self, _event: tk.Event) -> None:
        if self._is_syncing_sound_set:
            return
        sound_set = self._sound_set_by_label.get(self._selected_sound_set.get())
        if sound_set is None:
            return
        self._load_sound_set(sound_set)
        if self._on_sound_set_selected is not None:
            self._on_sound_set_selected(sound_set)

    def _handle_converted_selected(self, _event: tk.Event) -> None:
        if self._is_syncing_converted:
            return
        path = self._converted_path_by_label.get(self._selected_converted.get())
        if path is None:
            return
        self.stop_playback()
        self._converted.show_file(path, self._player.duration_ms(path))
        self._sync_duration()
        self._sync_export_buttons()

    def stop_playback(self) -> None:
        self._cancel_poll()
        self._cancel_volume_change()
        self._player.stop()
        self._set_playing(False)
        self._position_ms = 0
        self._update_positions()

    def _toggle_playback(self) -> None:
        try:
            if self._player.is_playing():
                self._position_ms = self._player.position_ms()
                self._player.pause()
                self._set_playing(False)
                self._update_positions()
                return
            self._play_from_current_position()
        except AudioPlaybackError as exc:
            self._handle_playback_error(exc)

    def _play_from_current_position(self) -> None:
        sources = self._active_playback_sources()
        if not sources:
            return
        if self._duration_ms and self._position_ms >= self._duration_ms:
            self._position_ms = 0
        paths = [path for path, _volume in sources]
        volumes = [volume for _path, volume in sources]
        self._player.play(paths, self._position_ms, volumes)
        self._set_playing(True)
        self._schedule_poll()

    def _seek(self, position_ms: int) -> None:
        self._position_ms = max(0, min(self._duration_ms, position_ms))
        self._update_positions()
        if self._player.is_playing():
            try:
                self._play_from_current_position()
            except AudioPlaybackError as exc:
                self._handle_playback_error(exc)

    def _handle_mute_changed(self) -> None:
        self._cancel_volume_change()
        self._sync_export_buttons()
        if not self._player.is_playing():
            return
        self._position_ms = self._player.position_ms()
        self._player.pause()
        try:
            self._play_from_current_position()
        except AudioPlaybackError as exc:
            self._handle_playback_error(exc)

    def _handle_volume_changed(self) -> None:
        if not self._player.is_playing():
            return
        self._cancel_volume_change()
        self._volume_after_id = self.after(180, self._apply_playback_volume_change)

    def _apply_playback_volume_change(self) -> None:
        self._volume_after_id = None
        if not self._player.is_playing():
            return
        self._position_ms = self._player.position_ms()
        self._player.pause()
        try:
            self._play_from_current_position()
        except AudioPlaybackError as exc:
            self._handle_playback_error(exc)

    def _export_mix(self) -> None:
        try:
            output_path = export_mix(self._active_mix_sources(), self._export_dir() / MIX_OUTPUT_NAME)
        except AudioExportError as exc:
            self._export_status_text.set(f"Export failed: {exc}")
            messagebox.showerror("Export failed", str(exc))
            return

        self._export_status_text.set(f"Exported mix: {output_path}")

    def _export_track(self, label: str, track: WaveformTrack) -> None:
        path = track.path()
        if path is None:
            return

        try:
            exported_path = export_audio_file(label, path, self._export_dir())
        except AudioExportError as exc:
            self._export_status_text.set(f"Export failed: {exc}")
            messagebox.showerror("Export failed", str(exc))
            return

        self._export_status_text.set(f"Exported track: {exported_path}")

    def _active_playback_sources(self) -> list[tuple[Path, float]]:
        sources: list[tuple[Path, float]] = []
        for _label, track in self._tracks():
            path = track.path()
            if path is not None and not track.is_muted():
                sources.append((path, track.volume()))
        return sources

    def _active_mix_sources(self) -> list[AudioMixSource]:
        sources: list[AudioMixSource] = []
        for label, track in self._tracks():
            path = track.path()
            if path is not None and not track.is_muted():
                sources.append(AudioMixSource(label, path, track.volume()))
        return sources

    def _loaded_named_paths(self) -> list[tuple[str, Path]]:
        paths: list[tuple[str, Path]] = []
        for label, track in self._tracks():
            path = track.path()
            if path is not None:
                paths.append((label, path))
        return paths

    def _tracks(self) -> tuple[tuple[str, WaveformTrack], ...]:
        return (
            ("Original Vocal", self._vocals),
            ("Instrumental", self._instrumental),
            ("Converted Vocal", self._converted),
        )

    def _export_dir(self) -> Path:
        if self._export_base_dir is not None:
            return self._export_base_dir / EXPORT_DIR_NAME

        loaded_paths = self._loaded_named_paths()
        if loaded_paths:
            return loaded_paths[0][1].parent / EXPORT_DIR_NAME
        raise AudioExportError("No output folder is available yet.")

    def _sync_export_buttons(self) -> None:
        active_count = len(self._active_mix_sources())
        self._export_mix_button.configure(state="normal" if active_count else "disabled")

    def _sync_duration(self) -> None:
        self._duration_ms = max(
            self._vocals.duration_ms(),
            self._instrumental.duration_ms(),
            self._converted.duration_ms(),
        )
        self._position_ms = 0
        self._update_positions()

    def _update_positions(self) -> None:
        for track in (self._vocals, self._instrumental, self._converted):
            track.set_position(self._position_ms)
        self._time_text.set(f"{_format_time(self._position_ms)} / {_format_time(self._duration_ms)}")

    def _schedule_poll(self) -> None:
        if self._poll_after_id is None:
            self._poll_after_id = self.after(100, self._poll_playback)

    def _poll_playback(self) -> None:
        self._poll_after_id = None
        if not self._player.is_playing():
            self._set_playing(False)
            return
        self._position_ms = self._player.position_ms()
        self._update_positions()
        self._schedule_poll()

    def _cancel_poll(self) -> None:
        if self._poll_after_id is None:
            return
        self.after_cancel(self._poll_after_id)
        self._poll_after_id = None

    def _cancel_volume_change(self) -> None:
        if self._volume_after_id is None:
            return
        self.after_cancel(self._volume_after_id)
        self._volume_after_id = None

    def _set_playing(self, is_playing: bool) -> None:
        self._play_button.configure(text=STOP_ICON if is_playing else PLAY_ICON)

    def _handle_playback_error(self, exc: AudioPlaybackError) -> None:
        self._player.stop()
        self._set_playing(False)
        self._export_status_text.set(f"Playback failed: {exc}")


def _converted_label(path: Path) -> str:
    stem = path.stem
    if stem.startswith("vocals_rvc_"):
        stem = stem.removeprefix("vocals_rvc_")
    match = re.match(r"(?P<model>.+?)_pitch_(?P<sign>[mp])(?P<pitch>\d+)_(?P<index>.+)_(?P<f0>[a-z0-9]+)$", stem)
    if not match:
        return _ellipsize(stem)

    sign = "-" if match.group("sign") == "m" else "+"
    index = _compact_index_label(match.group("index"))
    parts = [
        _pretty_slug(match.group("model")),
        f"pitch {sign}{match.group('pitch')}",
    ]
    if index != "no index":
        parts.append(index)
    parts.append(match.group("f0"))
    return _ellipsize(" | ".join(parts))


def _compact_index_label(index_slug: str) -> str:
    if index_slug == "noindex":
        return "no index"
    match = re.search(r"_nprobe_\d+_(?P<name>.+)$", index_slug)
    if match:
        return _pretty_slug(match.group("name"))
    return _pretty_slug(index_slug)


def _pretty_slug(value: str) -> str:
    return value.replace("_", "-")


def _ellipsize(value: str, max_chars: int = 52) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars - 3]}..."


def _unique_label(label: str, existing: dict[str, Path]) -> str:
    if label not in existing:
        return label

    index = 2
    while True:
        candidate = f"{label} ({index})"
        if candidate not in existing:
            return candidate
        index += 1
