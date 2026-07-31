from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from tkinterdnd2 import COPY, DND_FILES

from jang_app.config import SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.audio_player import AudioPlaybackError, AudioPlayer
from jang_app.services.audio_preview import AudioPreviewError, prepare_preview_audio
from jang_app.services.song_library import SongItem, SongLibrary
from jang_app.ui.controls import CanvasButton
from jang_app.ui.theme import AppTheme, DEFAULT_THEME


class SongRegistrationPage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        library: SongLibrary,
        on_use_song: Callable[[Path], None],
        theme: AppTheme = DEFAULT_THEME,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self._theme = theme
        self._library = library
        self._on_use_song = on_use_song
        self._player = AudioPlayer()
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._buttons: list[CanvasButton] = []
        self._row_buttons: dict[str, list[CanvasButton]] = {}
        self._playing_item_id: str | None = None
        self._status_text = tk.StringVar(value="Drop audio files to build a working set.")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()
        self._refresh_list()
        self.after(100, self._poll_events)
        self.after(250, self._poll_playback)

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self._drop_area.configure(bg=theme.panel_alt_bg, highlightbackground=theme.soft_border)
        self._list_canvas.configure(bg=theme.panel_bg)
        self._empty_canvas.configure(bg=theme.panel_bg)
        for button in self._buttons:
            button.set_theme(theme)
        for buttons in self._row_buttons.values():
            for button in buttons:
                button.set_theme(theme)
        self._draw_drop_art()

    def stop_playback(self) -> None:
        self._player.stop()
        self._playing_item_id = None
        self._refresh_row_buttons()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Song Intake", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Register local tracks, preview them, then send one into the studio workflow.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        add_button = CanvasButton(
            header,
            text="Add Songs",
            command=self._browse_files,
            theme=self._theme,
            variant="primary",
            width=112,
            height=34,
        )
        add_button.grid(row=0, column=1, sticky="ne", rowspan=2)
        self._buttons.append(add_button)

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0, minsize=360)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_drop_area(body)
        self._build_song_list(body)

    def _build_drop_area(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text="01", style="Badge.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="Register Songs", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(42, 0))
        ttk.Label(panel, text="Drop one or more audio files here.", style="Status.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(42, 0),
            pady=(28, 0),
        )

        self._drop_area = tk.Canvas(
            panel,
            height=360,
            bg=self._theme.panel_alt_bg,
            highlightthickness=1,
            highlightbackground=self._theme.soft_border,
            bd=0,
        )
        self._drop_area.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        self._drop_area.bind("<Configure>", lambda _event: self._draw_drop_art())
        self._drop_area.drop_target_register(DND_FILES)
        self._drop_area.dnd_bind("<<Drop>>", self._handle_drop)

        add_button = CanvasButton(
            panel,
            text="Browse Files",
            command=self._browse_files,
            theme=self._theme,
            variant="tool",
            width=132,
            height=34,
        )
        add_button.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self._buttons.append(add_button)

        ttk.Label(panel, textvariable=self._status_text, style="Status.TLabel", wraplength=310).grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(12, 0),
        )

    def _build_song_list(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        header = ttk.Frame(panel, style="PanelBody.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="02", style="Badge.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Registered Tracks", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(42, 0))
        ttk.Label(header, text="Preview or send a track to Studio.", style="Status.TLabel").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(42, 0),
            pady=(2, 0),
        )

        list_host = ttk.Frame(panel, style="PanelBody.TFrame")
        list_host.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        list_host.columnconfigure(0, weight=1)
        list_host.rowconfigure(0, weight=1)

        self._list_canvas = tk.Canvas(list_host, bg=self._theme.panel_bg, highlightthickness=0, bd=0)
        self._list_canvas.grid(row=0, column=0, sticky="nsew")
        self._list_container = ttk.Frame(self._list_canvas, style="PanelBody.TFrame")
        self._list_window = self._list_canvas.create_window((0, 0), window=self._list_container, anchor="nw")
        self._list_container.columnconfigure(0, weight=1)
        self._list_container.bind("<Configure>", self._sync_list_scroll_region)
        self._list_canvas.bind("<Configure>", self._sync_list_width)
        self._list_canvas.bind("<MouseWheel>", self._scroll_list)

        self._empty_canvas = tk.Canvas(self._list_container, height=260, bg=self._theme.panel_bg, highlightthickness=0, bd=0)

    def _handle_drop(self, event: tk.Event) -> str:
        paths = [Path(path) for path in self.tk.splitlist(event.data)]
        self._add_paths(paths)
        return COPY

    def _sync_list_scroll_region(self, _event: tk.Event) -> None:
        self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))

    def _sync_list_width(self, event: tk.Event) -> None:
        self._list_canvas.itemconfigure(self._list_window, width=event.width)

    def _scroll_list(self, event: tk.Event) -> str:
        self._list_canvas.yview_scroll(-1 * int(event.delta / 120), "units")
        return "break"

    def _browse_files(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_AUDIO_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Add songs",
            filetypes=[("Audio files", patterns), ("All files", "*.*")],
        )
        if paths:
            self._add_paths([Path(path) for path in paths])

    def _add_paths(self, paths: list[Path]) -> None:
        added = self._library.add_paths(paths)
        skipped = len(paths) - len(added)
        if added:
            self._status_text.set(f"Added {len(added)} song(s).")
            self._refresh_list()
            return
        if skipped:
            self._status_text.set("No supported new audio files were added.")

    def _refresh_list(self) -> None:
        for child in self._list_container.winfo_children():
            if child == self._empty_canvas:
                child.grid_forget()
            else:
                child.destroy()

        items = self._library.items()
        self._row_buttons = {}
        if not items:
            self._empty_canvas.grid(row=0, column=0, sticky="nsew")
            self._draw_empty_list()
            return

        self._empty_canvas.grid_forget()
        for row, item in enumerate(items):
            self._add_song_row(row * 2, item)

    def _add_song_row(self, row: int, item: SongItem) -> None:
        frame = ttk.Frame(self._list_container, style="PanelBody.TFrame", padding=(0, 0, 0, 12))
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        frame.columnconfigure(0, weight=1)

        info = ttk.Frame(frame, style="PanelBody.TFrame")
        info.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        info.columnconfigure(0, weight=1)
        ttk.Label(info, text=item.title, style="StatusStrong.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(info, text=f"{item.format_label}  |  {item.size_label}", style="Status.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(info, text=str(item.path), style="Status.TLabel", wraplength=560).grid(row=2, column=0, sticky="w", pady=(3, 0))

        actions = ttk.Frame(frame, style="PanelBody.TFrame")
        actions.grid(row=0, column=1, sticky="ne")
        play_button = CanvasButton(
            actions,
            text="Stop" if self._playing_item_id == item.id else "Play",
            command=lambda selected=item: self._toggle_playback(selected),
            theme=self._theme,
            variant="tool",
            width=62,
            height=32,
        )
        play_button.grid(row=0, column=0, padx=(0, 8))
        use_button = CanvasButton(
            actions,
            text="Use",
            command=lambda selected=item: self._use_song(selected),
            theme=self._theme,
            variant="primary",
            width=70,
            height=32,
        )
        use_button.grid(row=0, column=1)
        self._row_buttons[item.id] = [play_button, use_button]

        ttk.Frame(self._list_container, style="Divider.TFrame", height=1).grid(row=row + 1, column=0, sticky="ew")

    def _toggle_playback(self, item: SongItem) -> None:
        if self._playing_item_id == item.id and self._player.is_playing():
            self.stop_playback()
            self._status_text.set("Playback stopped.")
            return

        self.stop_playback()
        self._status_text.set(f"Preparing preview: {item.title}")
        threading.Thread(target=self._prepare_and_play, args=(item,), daemon=True).start()

    def _prepare_and_play(self, item: SongItem) -> None:
        try:
            preview_path = prepare_preview_audio(item.path)
        except AudioPreviewError as exc:
            self._events.put(("preview_error", str(exc)))
            return
        self._events.put(("preview_ready", (item, preview_path)))

    def _play_preview(self, item: SongItem, preview_path: Path) -> None:
        try:
            self._player.play([preview_path])
        except AudioPlaybackError as exc:
            self._status_text.set(f"Playback failed: {exc}")
            messagebox.showerror("Playback failed", str(exc), parent=self.winfo_toplevel())
            return
        self._playing_item_id = item.id
        self._status_text.set(f"Playing: {item.title}")
        self._refresh_row_buttons()

    def _use_song(self, item: SongItem) -> None:
        self.stop_playback()
        self._on_use_song(item.path)

    def _poll_events(self) -> None:
        try:
            event, payload = self._events.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_events)
            return

        if event == "preview_ready":
            item, preview_path = payload
            self._play_preview(item, preview_path)
        elif event == "preview_error":
            self._status_text.set(f"Preview failed: {payload}")
            messagebox.showerror("Preview failed", str(payload), parent=self.winfo_toplevel())

        self.after(100, self._poll_events)

    def _poll_playback(self) -> None:
        if self._playing_item_id is not None and not self._player.is_playing():
            self._playing_item_id = None
            self._status_text.set("Playback complete.")
            self._refresh_row_buttons()
        self.after(250, self._poll_playback)

    def _refresh_row_buttons(self) -> None:
        for item in self._library.items():
            buttons = self._row_buttons.get(item.id)
            if not buttons:
                continue
            buttons[0].configure(text="Stop" if self._playing_item_id == item.id and self._player.is_playing() else "Play")

    def _draw_drop_art(self) -> None:
        canvas = self._drop_area
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        theme = self._theme

        canvas.create_rectangle(28, 28, width - 28, height - 28, outline=theme.soft_border, dash=(4, 8))
        canvas.create_line(width // 2, height // 2 - 54, width // 2, height // 2 + 12, fill=theme.text, width=2)
        canvas.create_line(width // 2 - 20, height // 2 - 32, width // 2, height // 2 - 54, fill=theme.text, width=2)
        canvas.create_line(width // 2 + 20, height // 2 - 32, width // 2, height // 2 - 54, fill=theme.text, width=2)
        canvas.create_text(width // 2, height // 2 + 42, text="DROP AUDIO", fill=theme.text, font=("Segoe UI", 15, "bold"))
        canvas.create_text(
            width // 2,
            height // 2 + 70,
            text=", ".join(extension.removeprefix(".") for extension in sorted(SUPPORTED_AUDIO_EXTENSIONS)),
            fill=theme.muted_text,
            font=("Segoe UI", 9),
        )

    def _draw_empty_list(self) -> None:
        canvas = self._empty_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 240)
        canvas.create_text(width // 2, height // 2 - 12, text="No songs registered", fill=self._theme.text, font=("Segoe UI", 14, "bold"))
        canvas.create_text(width // 2, height // 2 + 18, text="Add or drop audio files to start.", fill=self._theme.muted_text, font=("Segoe UI", 10))
