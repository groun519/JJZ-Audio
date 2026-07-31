from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from jang_app.services.waveform import build_waveform_peaks
from jang_app.ui.controls import CanvasButton, VolumeSlider
from jang_app.ui.theme import AppTheme, DEFAULT_THEME


EXPORT_ICON = "\u21e9"


class WaveformTrack(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        on_seek: Callable[[int], None],
        on_mute_changed: Callable[[], None],
        on_volume_changed: Callable[[], None],
        on_export_requested: Callable[[], None],
        header_extra_builder: Callable[[ttk.Frame], tk.Widget] | None = None,
        theme: AppTheme = DEFAULT_THEME,
    ) -> None:
        super().__init__(parent, style="PanelBody.TFrame")
        self._label_text = tk.StringVar(value=label)
        self._time_text = tk.StringVar(value="00:00 / 00:00")
        self._volume_text = tk.StringVar(value="100%")
        self._on_seek = on_seek
        self._on_mute_changed = on_mute_changed
        self._on_volume_changed = on_volume_changed
        self._on_export_requested = on_export_requested
        self._header_extra_builder = header_extra_builder
        self._theme = theme
        self._path: Path | None = None
        self._duration_ms = 0
        self._position_ms = 0
        self._is_muted = False
        self._is_syncing_volume = False
        self._peaks: list[float] = []
        self._empty_message = "Waiting for audio"

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._canvas = self._build_canvas()
        self.show_empty()

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self._volume_scale.configure(
            bg=theme.panel_bg,
        )
        self._volume_scale.set_theme(theme)
        self._export_button.set_theme(theme)
        self._mute_button.set_theme(theme)
        self._canvas.configure(bg=theme.panel_alt_bg, highlightbackground=theme.soft_border)
        self._redraw()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="PanelBody.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, textvariable=self._label_text, style="PanelHeading.TLabel").grid(row=0, column=0, sticky="w")
        if self._header_extra_builder is not None:
            self._header_extra_builder(header).grid(row=0, column=1, sticky="ew", padx=(10, 16))

        ttk.Label(header, textvariable=self._time_text, style="StatusStrong.TLabel").grid(row=0, column=2, sticky="e")
        ttk.Label(header, text="Click waveform to seek", style="Status.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        actions = ttk.Frame(header, style="PanelBody.TFrame")
        actions.grid(row=1, column=2, sticky="e", pady=(6, 0))
        ttk.Label(actions, text="VOL", style="Field.TLabel").grid(row=0, column=0, padx=(0, 6))
        self._volume_scale = VolumeSlider(
            actions,
            self._change_volume,
            theme=self._theme,
            width=118,
            height=22,
        )
        self._volume_scale.grid(row=0, column=1, padx=(0, 6))
        ttk.Label(actions, textvariable=self._volume_text, style="Status.TLabel", width=4).grid(row=0, column=2, padx=(0, 8))
        self._export_button = CanvasButton(
            actions,
            text=EXPORT_ICON,
            command=self._request_export,
            theme=self._theme,
            variant="tool",
            width=38,
            height=30,
        )
        self._export_button.grid(row=0, column=3, padx=(0, 8))
        self._mute_button = CanvasButton(
            actions,
            text="Mute",
            command=self._toggle_mute,
            theme=self._theme,
            variant="tool",
            width=76,
            height=30,
        )
        self._mute_button.grid(row=0, column=4)

    def _build_canvas(self) -> tk.Canvas:
        canvas = tk.Canvas(
            self,
            height=112,
            bg=self._theme.panel_alt_bg,
            highlightthickness=1,
            highlightbackground=self._theme.soft_border,
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        canvas.bind("<Button-1>", self._seek_from_event)
        canvas.bind("<B1-Motion>", self._seek_from_event)
        canvas.bind("<Configure>", self._redraw)
        return canvas

    def show_empty(self, message: str = "Waiting for audio") -> None:
        self._empty_message = message
        self._path = None
        self._duration_ms = 0
        self._position_ms = 0
        self._is_muted = False
        self._peaks = []
        self._reset_volume()
        self._set_mute_enabled(False)
        self._set_volume_enabled(False)
        self._set_export_enabled(False)
        self._update_mute_text()
        self._update_time_label()
        self._draw_placeholder(message)

    def show_file(self, path: Path, duration_ms: int) -> None:
        self._path = path
        self._duration_ms = duration_ms
        self._position_ms = 0
        self._is_muted = False
        self._reset_volume()
        self._set_mute_enabled(True)
        self._set_volume_enabled(True)
        self._set_export_enabled(True)
        self._update_mute_text()
        self._update_time_label()
        self._draw_file(path)

    def set_label(self, label: str) -> None:
        self._label_text.set(label)

    def set_position(self, position_ms: int) -> None:
        self._position_ms = max(0, min(self._duration_ms, position_ms))
        self._update_time_label()
        self._redraw()

    def path(self) -> Path | None:
        return self._path

    def duration_ms(self) -> int:
        return self._duration_ms

    def is_muted(self) -> bool:
        return self._is_muted

    def volume(self) -> float:
        return max(0.0, min(1.0, self._volume_scale.value() / 100))

    def _toggle_mute(self) -> None:
        if self._path is None:
            return
        self._is_muted = not self._is_muted
        self._update_mute_text()
        self._redraw()
        self._on_mute_changed()

    def _change_volume(self) -> None:
        self._update_volume_text()
        if self._is_syncing_volume or self._path is None:
            return
        self._on_volume_changed()

    def _set_mute_enabled(self, is_enabled: bool) -> None:
        self._mute_button.configure(state="normal" if is_enabled else "disabled")

    def _set_volume_enabled(self, is_enabled: bool) -> None:
        self._volume_scale.configure(state="normal" if is_enabled else "disabled")

    def _set_export_enabled(self, is_enabled: bool) -> None:
        self._export_button.configure(state="normal" if is_enabled else "disabled")

    def _update_mute_text(self) -> None:
        self._mute_button.configure(text="Muted" if self._is_muted else "Mute")

    def _update_volume_text(self) -> None:
        self._volume_text.set(f"{self._volume_scale.value()}%")

    def _reset_volume(self) -> None:
        self._is_syncing_volume = True
        try:
            self._volume_scale.set_value(100)
            self._update_volume_text()
        finally:
            self._is_syncing_volume = False

    def _request_export(self) -> None:
        if self._path is None:
            return
        self._on_export_requested()

    def _draw_file(self, path: Path) -> None:
        self._empty_message = "No waveform data"
        self._canvas.update_idletasks()
        width = max(self._canvas.winfo_width(), 320)
        self._peaks = build_waveform_peaks(path, width)
        self._draw_waveform()

    def _draw_placeholder(self, text: str) -> None:
        self._canvas.delete("all")
        self._canvas.create_text(18, 18, text=text, fill=self._theme.muted_text, anchor="nw", font=("Segoe UI", 10))

    def _draw_waveform(self) -> None:
        self._canvas.delete("all")
        width = max(self._canvas.winfo_width(), 320)
        height = max(self._canvas.winfo_height(), 100)
        mid_y = height // 2
        max_amp = max(8, (height - 24) // 2)

        if not self._peaks:
            self._draw_placeholder("No waveform data")
            return

        wave_color = self._theme.muted_text if self._is_muted else self._theme.accent
        self._draw_grid(width, height, mid_y)
        step = width / max(len(self._peaks), 1)
        for index, peak in enumerate(self._peaks):
            x = int(index * step)
            y = max(1, int(peak * max_amp))
            self._canvas.create_line(x, mid_y - y, x, mid_y + y, fill=wave_color, width=1)
        self._canvas.create_line(0, mid_y, width, mid_y, fill=self._theme.soft_border)
        self._draw_playhead(width, height)

    def _draw_grid(self, width: int, height: int, mid_y: int) -> None:
        for ratio in (0.25, 0.5, 0.75):
            x = int(width * ratio)
            self._canvas.create_line(x, 12, x, height - 12, fill=self._theme.soft_border, dash=(2, 6))
        self._canvas.create_text(12, mid_y - 18, text="0", fill=self._theme.muted_text, anchor="w", font=("Segoe UI", 8))

    def _draw_playhead(self, width: int, height: int) -> None:
        if self._duration_ms <= 0:
            return
        ratio = max(0.0, min(1.0, self._position_ms / self._duration_ms))
        x = int(width * ratio)
        self._canvas.create_line(x, 0, x, height, fill=self._theme.accent_light, width=2)
        self._canvas.create_oval(x - 4, 6, x + 4, 14, fill=self._theme.accent_light, outline="")

    def _seek_from_event(self, event: tk.Event) -> None:
        if self._path is None or self._duration_ms <= 0:
            return
        width = max(self._canvas.winfo_width(), 1)
        ratio = max(0.0, min(1.0, event.x / width))
        self._on_seek(int(self._duration_ms * ratio))

    def _update_time_label(self) -> None:
        self._time_text.set(f"{_format_time(self._position_ms)} / {_format_time(self._duration_ms)}")

    def _redraw(self, _event: tk.Event | None = None) -> None:
        if self._peaks:
            self._draw_waveform()
            return
        self._draw_placeholder(self._empty_message)


def _format_time(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"
