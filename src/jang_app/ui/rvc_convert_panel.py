from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from jang_app.pipeline.rvc_convert import list_index_files, list_voice_models
from jang_app.services.settings import AppSettings, RvcSettings
from jang_app.ui.controls import CanvasButton
from jang_app.ui.progress_status import ProgressStatus
from jang_app.ui.theme import AppTheme, DEFAULT_THEME


AUTO_SAVE_DELAY_MS = 250
GEAR_ICON = "\u2699"
REFRESH_ICON = "\u21bb"


class RvcConvertPanel(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        settings: AppSettings,
        on_convert: Callable[[], None],
        on_save_settings: Callable[[RvcSettings], None],
        on_open_settings: Callable[[], None],
        theme: AppTheme = DEFAULT_THEME,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=18)
        self._theme = theme
        self._on_save_settings = on_save_settings
        self._on_open_settings = on_open_settings
        self._buttons: list[CanvasButton] = []
        self._auto_save_after_id: str | None = None
        self._is_syncing_settings = False
        self._rvc_root = tk.StringVar()
        self._voice_model = tk.StringVar()
        self._index_file = tk.StringVar()
        self._pitch = tk.StringVar()
        self._device = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_settings_editor()
        self._build_actions(on_convert)
        self.update_settings(settings)
        self._bind_auto_save()

    def apply_settings(self) -> bool:
        settings = self._collect_settings(show_warning=True)
        if settings is None:
            return False
        self._on_save_settings(settings)
        return True

    def set_convert_enabled(self, is_enabled: bool) -> None:
        self._convert_button.configure(state="normal" if is_enabled else "disabled")

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        for button in self._buttons:
            button.set_theme(theme)

    def set_progress(self, percent: int, text: str | None = None) -> None:
        self.progress_status.set_progress(percent, text)

    def set_status(self, text: str) -> None:
        self.progress_status.set_text(text)

    def reset_status(self, text: str = "") -> None:
        self.progress_status.reset(text)

    def update_settings(self, settings: AppSettings) -> None:
        self._cancel_auto_save()
        self._is_syncing_settings = True
        try:
            rvc = settings.rvc
            self._rvc_root.set(str(rvc.root))
            self._voice_model.set(rvc.voice_model)
            self._index_file.set(rvc.index_file)
            self._pitch.set(str(rvc.pitch))
            self._device.set(rvc.device)
            self._refresh_rvc_choices()
        finally:
            self._is_syncing_settings = False

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="PanelBody.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="03", style="Badge.TLabel").grid(row=0, column=0, sticky="nw", padx=(0, 10), rowspan=2)
        ttk.Label(header, text="Convert Vocal", style="PanelTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Apply the selected RVC voice model.", style="Status.TLabel").grid(
            row=1,
            column=1,
            sticky="w",
            pady=(2, 0),
        )
        button = CanvasButton(
            header,
            text=GEAR_ICON,
            command=self._on_open_settings,
            theme=self._theme,
            variant="tool",
            width=38,
            height=32,
        )
        button.grid(row=0, column=2, sticky="ne", rowspan=2)
        self._buttons.append(button)

    def _build_settings_editor(self) -> None:
        editor = ttk.Frame(self, style="PanelBody.TFrame")
        editor.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        editor.columnconfigure(1, weight=1)

        self._add_root_row(editor, 0)
        self._add_combo_row(editor, 1, "Model", self._voice_model, "_voice_model_combo")
        self._add_combo_row(editor, 2, "Index", self._index_file, "_index_file_combo")
        self._add_runtime_row(editor, 3)
        ttk.Label(editor, text="F0 method: rmvpe", style="Status.TLabel").grid(
            row=4,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

    def _build_actions(self, on_convert: Callable[[], None]) -> None:
        actions = ttk.Frame(self, style="PanelBody.TFrame")
        ttk.Frame(self, style="Divider.TFrame", height=1).grid(row=2, column=0, sticky="ew", pady=(16, 0))
        actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)

        self._convert_button = CanvasButton(
            actions,
            text="Convert Vocal",
            command=on_convert,
            theme=self._theme,
            variant="primary",
            width=344,
            height=34,
        )
        self._convert_button.grid(row=0, column=0, sticky="ew")
        self._buttons.append(self._convert_button)
        self.set_convert_enabled(False)

        self.progress_status = ProgressStatus(actions)
        self.progress_status.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.progress_status.reset("Separate audio before converting.")

    def _add_root_row(self, parent: ttk.Frame, row: int) -> None:
        ttk.Label(parent, text="ROOT", style="Field.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(parent, textvariable=self._rvc_root).grid(row=row, column=1, sticky="ew")
        button = CanvasButton(
            parent,
            text="...",
            command=self._browse_rvc_root,
            theme=self._theme,
            variant="tool",
            width=38,
            height=30,
        )
        button.grid(
            row=row,
            column=2,
            padx=(8, 0),
        )
        self._buttons.append(button)

    def _add_combo_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, attribute: str) -> None:
        ttk.Label(parent, text=label.upper(), style="Field.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=(6, 0),
        )
        combo = ttk.Combobox(parent, textvariable=variable, width=22)
        combo.grid(row=row, column=1, sticky="ew", pady=(6, 0))
        setattr(self, attribute, combo)
        if label == "Index":
            button = CanvasButton(
                parent,
                text=REFRESH_ICON,
                command=self._refresh_rvc_choices,
                theme=self._theme,
                variant="tool",
                width=38,
                height=30,
            )
            button.grid(
                row=row,
                column=2,
                padx=(8, 0),
                pady=(6, 0),
            )
            self._buttons.append(button)

    def _add_runtime_row(self, parent: ttk.Frame, row: int) -> None:
        ttk.Label(parent, text="PITCH", style="Field.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=(6, 0),
        )
        runtime = ttk.Frame(parent, style="PanelBody.TFrame")
        runtime.grid(row=row, column=1, sticky="ew", pady=(6, 0), columnspan=2)
        runtime.columnconfigure(1, weight=1)

        ttk.Entry(runtime, textvariable=self._pitch, width=8).grid(row=0, column=0, sticky="w")
        ttk.Label(runtime, text="DEVICE", style="Field.TLabel").grid(row=0, column=1, sticky="e", padx=(12, 8))
        ttk.Combobox(runtime, textvariable=self._device, values=["cuda:0", "cpu"], width=9).grid(
            row=0,
            column=2,
            sticky="e",
        )

    def _browse_rvc_root(self) -> None:
        path = filedialog.askdirectory(title="Select RVC root folder", initialdir=self._rvc_root.get())
        if path:
            self._rvc_root.set(path)
            self._refresh_rvc_choices()

    def _refresh_rvc_choices(self) -> None:
        root = Path(self._rvc_root.get().strip()).expanduser()
        models = list_voice_models(root)
        indexes = [""] + list_index_files(root)
        self._voice_model_combo.configure(values=models)
        self._index_file_combo.configure(values=indexes)
        if not self._voice_model.get() and models:
            self._voice_model.set(models[0])
        if self._index_file.get() not in indexes:
            self._index_file.set("")

    def _bind_auto_save(self) -> None:
        for variable in (self._rvc_root, self._voice_model, self._index_file, self._pitch, self._device):
            variable.trace_add("write", self._schedule_auto_save)

    def _schedule_auto_save(self, *_args: object) -> None:
        if self._is_syncing_settings:
            return
        self._cancel_auto_save()
        self._auto_save_after_id = self.after(AUTO_SAVE_DELAY_MS, self._auto_save_settings)

    def _cancel_auto_save(self) -> None:
        if self._auto_save_after_id is None:
            return
        self.after_cancel(self._auto_save_after_id)
        self._auto_save_after_id = None

    def _auto_save_settings(self) -> None:
        self._auto_save_after_id = None
        settings = self._collect_settings(show_warning=False)
        if settings is not None:
            self._on_save_settings(settings)

    def _collect_settings(self, show_warning: bool) -> RvcSettings | None:
        root = self._rvc_root.get().strip()
        if not root:
            if show_warning:
                self._show_warning("Missing RVC root", "Select the RVC root folder first.")
            return None

        try:
            pitch = int(self._pitch.get().strip())
        except ValueError:
            if show_warning:
                self._show_warning("Invalid pitch", "Pitch must be an integer.")
            return None

        return RvcSettings(
            root=Path(root).expanduser(),
            voice_model=self._voice_model.get().strip(),
            index_file=self._index_file.get().strip(),
            pitch=pitch,
            device=self._device.get().strip() or "cuda:0",
            f0_method="rmvpe",
        )

    def _show_warning(self, title: str, message: str) -> None:
        messagebox.showwarning(title, message, parent=self.winfo_toplevel())
