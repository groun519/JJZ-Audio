from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def add_section_header(parent: tk.Widget, row: int, eyebrow: str, title: str, description: str = "") -> ttk.Frame:
    header = ttk.Frame(parent, style="PanelBody.TFrame")
    header.grid(row=row, column=0, sticky="ew")
    header.columnconfigure(1, weight=1)

    ttk.Label(header, text=eyebrow, style="Badge.TLabel").grid(row=0, column=0, sticky="nw", padx=(0, 10), rowspan=2)
    ttk.Label(header, text=title, style="PanelTitle.TLabel").grid(row=0, column=1, sticky="w")
    if description:
        ttk.Label(header, text=description, style="Status.TLabel").grid(row=1, column=1, sticky="w", pady=(2, 0))
    return header
