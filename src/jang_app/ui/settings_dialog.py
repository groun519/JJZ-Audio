from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from jang_app.pipeline.rvc_convert import list_index_files, list_voice_models
from jang_app.services.settings import AppSettings, RVC_DEVICE_OPTIONS, RvcSettings, save_app_settings


class OutputSettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, settings: AppSettings, on_save: Callable[[AppSettings], None]) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.configure(bg=parent.cget("bg"))

        self._on_save = on_save
        self._output_root = tk.StringVar(value=str(settings.output_root))
        self._theme_mode = tk.StringVar(value=settings.theme_mode)
        self._rvc_root = tk.StringVar(value=str(settings.rvc.root))
        self._voice_model = tk.StringVar(value=settings.rvc.voice_model)
        self._index_file = tk.StringVar(value=settings.rvc.index_file)
        self._pitch = tk.StringVar(value=str(settings.rvc.pitch))
        self._device = tk.StringVar(value=settings.rvc.device)

        self._build_ui()
        self._refresh_rvc_choices()
        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def _build_ui(self) -> None:
        panel = ttk.Frame(self, style="Panel.TFrame", padding=18)
        panel.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        panel.columnconfigure(1, weight=1)

        self._add_output_section(panel)
        self._add_theme_section(panel)
        self._add_rvc_section(panel)

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=9, column=1, sticky="e", pady=(18, 0), columnspan=2)
        ttk.Button(actions, text="Cancel", style="Tool.TButton", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Save", style="Accent.TButton", command=self._save).grid(row=0, column=1)

    def _add_output_section(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="Output folder", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Entry(panel, textvariable=self._output_root, width=64).grid(row=0, column=1, sticky="ew")
        ttk.Button(panel, text="Browse", style="Tool.TButton", command=self._browse_output).grid(
            row=0,
            column=2,
            padx=(10, 0),
        )

    def _add_theme_section(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="Theme", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        ttk.Combobox(panel, textvariable=self._theme_mode, values=["white", "dark"], state="readonly", width=12).grid(
            row=1,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

    def _add_rvc_section(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="RVC", style="PanelHeading.TLabel").grid(row=2, column=0, sticky="w", pady=(18, 8))

        ttk.Label(panel, text="RVC root", style="Panel.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 12))
        ttk.Entry(panel, textvariable=self._rvc_root, width=64).grid(row=3, column=1, sticky="ew")
        ttk.Button(panel, text="Browse", style="Tool.TButton", command=self._browse_rvc_root).grid(
            row=3,
            column=2,
            padx=(10, 0),
        )

        ttk.Label(panel, text="Voice model", style="Panel.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        self._voice_model_combo = ttk.Combobox(panel, textvariable=self._voice_model, width=61)
        self._voice_model_combo.grid(row=4, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(panel, text="Index file", style="Panel.TLabel").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        self._index_file_combo = ttk.Combobox(panel, textvariable=self._index_file, width=61)
        self._index_file_combo.grid(row=5, column=1, sticky="ew", pady=(8, 0))

        ttk.Button(panel, text="Refresh", style="Tool.TButton", command=self._refresh_rvc_choices).grid(
            row=5,
            column=2,
            padx=(10, 0),
            pady=(8, 0),
        )

        ttk.Label(panel, text="Pitch", style="Panel.TLabel").grid(row=6, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        ttk.Entry(panel, textvariable=self._pitch, width=12).grid(row=6, column=1, sticky="w", pady=(8, 0))

        ttk.Label(panel, text="Device", style="Panel.TLabel").grid(row=7, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        ttk.Combobox(panel, textvariable=self._device, values=RVC_DEVICE_OPTIONS, width=12).grid(
            row=7,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

        ttk.Label(panel, text="F0 method: rmvpe", style="Status.TLabel").grid(
            row=8,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder", initialdir=self._output_root.get())
        if path:
            self._output_root.set(path)

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

    def _save(self) -> None:
        output_root = self._output_root.get().strip()
        rvc_root = self._rvc_root.get().strip()
        if not output_root:
            messagebox.showwarning("Missing output folder", "Select an output folder first.", parent=self)
            return
        if not rvc_root:
            messagebox.showwarning("Missing RVC root", "Select the RVC root folder first.", parent=self)
            return

        try:
            pitch = int(self._pitch.get().strip())
        except ValueError:
            messagebox.showwarning("Invalid pitch", "Pitch must be an integer.", parent=self)
            return

        settings = AppSettings(
            output_root=Path(output_root).expanduser(),
            theme_mode=self._theme_mode.get().strip() if self._theme_mode.get().strip() in {"white", "dark"} else "white",
            rvc=RvcSettings(
                root=Path(rvc_root).expanduser(),
                voice_model=self._voice_model.get().strip(),
                index_file=self._index_file.get().strip(),
                pitch=pitch,
                device=self._device.get().strip() or "auto",
                f0_method="rmvpe",
            ),
        )
        save_app_settings(settings)
        self._on_save(settings)
        self.destroy()
