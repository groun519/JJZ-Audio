from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Collection
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import COPY, DND_FILES

from jang_app.ui.controls import CanvasButton
from jang_app.ui.theme import AppTheme, DEFAULT_THEME


class DropZone(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        on_file_selected: Callable[[Path], None],
        selected_file: tk.StringVar,
        theme: AppTheme = DEFAULT_THEME,
        accepted_extensions: Collection[str] = (),
    ) -> None:
        super().__init__(parent, style="Drop.TFrame", padding=18)
        self._theme = theme
        self._accepted_extensions = {extension.lower() for extension in accepted_extensions}
        self._on_file_selected = on_file_selected
        self._selected_file = selected_file
        self._is_hovered = False

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_content()
        self._register_drop_targets(
            self,
            self._select_button,
            self._field_label,
            self._selected_label,
            self._icon,
            self._title,
            self._hint,
            self._format_label,
        )

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self._select_button.configure(
            bg=theme.panel_alt_bg,
        )
        self._select_button.set_theme(theme)
        self._select_button.configure(bg=theme.drop_hover_bg if self._is_hovered else theme.panel_alt_bg)
        self._icon.configure(bg=theme.drop_hover_bg if self._is_hovered else theme.panel_alt_bg)
        self._draw_icon()

    def _build_content(self) -> None:
        self._select_button = CanvasButton(
            self,
            text="File",
            command=self._select_file,
            theme=self._theme,
            variant="primary",
            width=58,
            height=38,
        )
        self._select_button.configure(bg=self._theme.panel_alt_bg)
        self._select_button.grid(row=0, column=0, sticky="nw")

        self._field_label = ttk.Label(self, text="SELECTED FILE", style="DropField.TLabel")
        self._field_label.grid(row=0, column=1, sticky="nw", padx=(12, 0))
        self._selected_label = ttk.Label(
            self,
            textvariable=self._selected_file,
            style="DropStrong.TLabel",
            anchor="w",
        )
        self._selected_label.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(18, 0))

        self._icon = tk.Canvas(self, width=86, height=78, highlightthickness=0, bg=self._theme.panel_alt_bg)
        self._icon.grid(row=1, column=0, columnspan=2, pady=(16, 8))

        self._title = ttk.Label(self, text="Drop audio file here", style="Drop.TLabel", anchor="center")
        self._title.grid(row=2, column=0, columnspan=2)

        self._hint = ttk.Label(self, text="Drag one file into this box", style="DropHint.TLabel", anchor="center")
        self._hint.grid(row=3, column=0, columnspan=2, pady=(4, 0))
        self._format_label = ttk.Label(
            self,
            text=f"SUPPORTED  {self._format_supported_extensions().upper()}",
            style="DropHint.TLabel",
            anchor="center",
        )
        self._format_label.grid(row=4, column=0, columnspan=2, pady=(10, 0))

        self._draw_icon()

    def _format_supported_extensions(self) -> str:
        return ", ".join(extension.removeprefix(".") for extension in sorted(self._accepted_extensions))

    def _register_drop_targets(self, *widgets: tk.Widget) -> None:
        for widget in widgets:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<DropEnter>>", self._handle_drop_hover)
            widget.dnd_bind("<<DropPosition>>", self._handle_drop_hover)
            widget.dnd_bind("<<DropLeave>>", self._handle_drop_leave)
            widget.dnd_bind("<<Drop>>", self._handle_drop)

    def _handle_drop_hover(self, _event: tk.Event) -> str:
        self._set_hovered(True)
        return COPY

    def _handle_drop_leave(self, _event: tk.Event) -> str:
        self._set_hovered(False)
        return COPY

    def _handle_drop(self, event: tk.Event) -> str:
        self._set_hovered(False)
        paths = self.tk.splitlist(event.data)
        if not paths:
            return COPY

        self._select_path(Path(paths[0]))
        return COPY

    def _select_file(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(self._accepted_extensions))
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio files", patterns), ("All files", "*.*")],
        )
        if path:
            self._select_path(Path(path))

    def _select_path(self, path: Path) -> None:
        if not self._is_supported(path):
            messagebox.showwarning("Unsupported file", f"Supported audio formats: {self._format_supported_extensions()}")
            return

        self._on_file_selected(path)

    def _is_supported(self, path: Path) -> bool:
        return not self._accepted_extensions or path.suffix.lower() in self._accepted_extensions

    def _set_hovered(self, is_hovered: bool) -> None:
        if self._is_hovered == is_hovered:
            return

        self._is_hovered = is_hovered
        frame_style = "DropHover.TFrame" if is_hovered else "Drop.TFrame"
        label_style = "DropHover.TLabel" if is_hovered else "Drop.TLabel"
        hint_style = "DropHoverHint.TLabel" if is_hovered else "DropHint.TLabel"
        field_style = "DropHoverField.TLabel" if is_hovered else "DropField.TLabel"
        strong_style = "DropHoverStrong.TLabel" if is_hovered else "DropStrong.TLabel"
        background = self._theme.drop_hover_bg if is_hovered else self._theme.panel_alt_bg

        self.configure(style=frame_style)
        self._title.configure(style=label_style)
        self._hint.configure(style=hint_style)
        self._format_label.configure(style=hint_style)
        self._field_label.configure(style=field_style)
        self._selected_label.configure(style=strong_style)
        self._select_button.configure(bg=background)
        self._icon.configure(bg=background)
        self._draw_icon()

    def _draw_icon(self) -> None:
        self._icon.delete("all")
        highlight = self._theme.accent if not self._is_hovered else self._theme.accent_light
        body = self._theme.text if not self._is_hovered else self._theme.accent_light

        self._icon.create_rectangle(22, 10, 58, 64, outline=highlight, width=2)
        self._icon.create_line(46, 10, 58, 22, fill=highlight, width=2)
        self._icon.create_line(46, 10, 46, 22, fill=highlight, width=2)
        self._icon.create_line(46, 22, 58, 22, fill=highlight, width=2)
        self._icon.create_oval(30, 42, 42, 54, outline=body, width=2)
        self._icon.create_line(42, 48, 50, 34, fill=body, width=2)
        self._icon.create_line(50, 34, 50, 50, fill=body, width=2)
        self._icon.create_line(18, 70, 68, 70, fill=highlight, width=2)
