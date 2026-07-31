from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ProgressStatus(ttk.Frame):
    def __init__(self, parent: tk.Widget, wraplength: int = 280) -> None:
        super().__init__(parent, style="PanelBody.TFrame")
        self._text = tk.StringVar(value="")
        self._value = tk.DoubleVar(value=0)
        self._percent_text = tk.StringVar(value="0%")

        self.columnconfigure(0, weight=1)
        meta = ttk.Frame(self, style="PanelBody.TFrame")
        meta.grid(row=0, column=0, sticky="ew")
        meta.columnconfigure(0, weight=1)
        ttk.Label(meta, text="Progress", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, textvariable=self._percent_text, style="StatusStrong.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Progressbar(
            self,
            mode="determinate",
            maximum=100,
            variable=self._value,
            style="Progress.Horizontal.TProgressbar",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(self, textvariable=self._text, style="Status.TLabel", wraplength=wraplength).grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

    def set_progress(self, percent: int, text: str | None = None) -> None:
        value = max(0, min(100, percent))
        self._value.set(value)
        self._percent_text.set(f"{value}%")
        if text is not None:
            self._text.set(text)

    def set_text(self, text: str) -> None:
        self._text.set(text)

    def reset(self, text: str = "") -> None:
        self._value.set(0)
        self._percent_text.set("0%")
        self._text.set(text)
