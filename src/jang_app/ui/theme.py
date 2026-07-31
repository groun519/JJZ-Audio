from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class AppTheme:
    window_bg: str = "#f4f4f1"
    panel_bg: str = "#ffffff"
    panel_alt_bg: str = "#f7f7f4"
    border: str = "#111111"
    soft_border: str = "#d8d8d2"
    text: str = "#111111"
    muted_text: str = "#5f5f5a"
    accent: str = "#111111"
    accent_light: str = "#333333"
    accent_dark: str = "#000000"
    on_accent: str = "#ffffff"
    entry_bg: str = "#ffffff"
    drop_hover_bg: str = "#eeeeea"


WHITE_THEME = AppTheme()
DARK_THEME = AppTheme(
    window_bg="#0d0d0d",
    panel_bg="#151515",
    panel_alt_bg="#0f0f0f",
    border="#f2f2f2",
    soft_border="#303030",
    text="#f7f7f4",
    muted_text="#b8b8b2",
    accent="#f7f7f4",
    accent_light="#ffffff",
    accent_dark="#dddddd",
    on_accent="#111111",
    entry_bg="#0a0a0a",
    drop_hover_bg="#242424",
)
DEFAULT_THEME = WHITE_THEME


def theme_for_mode(mode: str) -> AppTheme:
    return DARK_THEME if mode == "dark" else WHITE_THEME


def apply_theme(root: tk.Tk, theme: AppTheme = DEFAULT_THEME) -> None:
    root.configure(bg=theme.window_bg)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", font=("Segoe UI", 10), background=theme.window_bg, foreground=theme.text)
    style.configure("App.TFrame", background=theme.window_bg)
    style.configure("Panel.TFrame", background=theme.panel_bg, borderwidth=1, relief="solid")
    style.configure("PanelBody.TFrame", background=theme.panel_bg)
    style.configure("Title.TLabel", background=theme.window_bg, foreground=theme.text, font=("Segoe UI", 20, "bold"))
    style.configure("Muted.TLabel", background=theme.window_bg, foreground=theme.muted_text)
    style.configure("Panel.TLabel", background=theme.panel_bg, foreground=theme.text)
    style.configure("PanelHeading.TLabel", background=theme.panel_bg, foreground=theme.text, font=("Segoe UI", 11, "bold"))
    style.configure("PanelTitle.TLabel", background=theme.panel_bg, foreground=theme.text, font=("Segoe UI", 13, "bold"))
    style.configure("Eyebrow.TLabel", background=theme.panel_bg, foreground=theme.muted_text, font=("Segoe UI", 8, "bold"))
    style.configure("Field.TLabel", background=theme.panel_bg, foreground=theme.muted_text, font=("Segoe UI", 9, "bold"))
    style.configure("Status.TLabel", background=theme.panel_bg, foreground=theme.muted_text)
    style.configure("StatusStrong.TLabel", background=theme.panel_bg, foreground=theme.text, font=("Segoe UI", 9, "bold"))
    style.configure("Badge.TLabel", background=theme.accent, foreground=theme.on_accent, font=("Segoe UI", 8, "bold"), padding=(7, 2))
    style.configure("Divider.TFrame", background=theme.soft_border)
    style.configure("Drop.TFrame", background=theme.panel_alt_bg, borderwidth=1, relief="solid")
    style.configure("Drop.TLabel", background=theme.panel_alt_bg, foreground=theme.text, font=("Segoe UI", 11, "bold"))
    style.configure("DropField.TLabel", background=theme.panel_alt_bg, foreground=theme.muted_text, font=("Segoe UI", 8, "bold"))
    style.configure("DropStrong.TLabel", background=theme.panel_alt_bg, foreground=theme.text, font=("Segoe UI", 10, "bold"))
    style.configure("DropHint.TLabel", background=theme.panel_alt_bg, foreground=theme.muted_text)
    style.configure("DropHover.TFrame", background=theme.drop_hover_bg, borderwidth=1, relief="solid")
    style.configure(
        "DropHover.TLabel",
        background=theme.drop_hover_bg,
        foreground=theme.text,
        font=("Segoe UI", 11, "bold"),
    )
    style.configure("DropHoverField.TLabel", background=theme.drop_hover_bg, foreground=theme.muted_text, font=("Segoe UI", 8, "bold"))
    style.configure("DropHoverStrong.TLabel", background=theme.drop_hover_bg, foreground=theme.text, font=("Segoe UI", 10, "bold"))
    style.configure("DropHoverHint.TLabel", background=theme.drop_hover_bg, foreground=theme.text)
    style.configure("Progress.TFrame", background=theme.window_bg)
    style.configure("Progress.Horizontal.TProgressbar", troughcolor=theme.panel_alt_bg, background=theme.accent)
    style.configure(
        "TEntry",
        fieldbackground=theme.entry_bg,
        foreground=theme.text,
        bordercolor=theme.soft_border,
        lightcolor=theme.soft_border,
        darkcolor=theme.soft_border,
        insertcolor=theme.text,
    )
    style.configure(
        "TCombobox",
        background=theme.panel_alt_bg,
        bordercolor=theme.soft_border,
        darkcolor=theme.soft_border,
        fieldbackground=theme.entry_bg,
        foreground=theme.text,
        insertcolor=theme.text,
        lightcolor=theme.soft_border,
        selectbackground=theme.entry_bg,
        selectforeground=theme.text,
    )
    style.map(
        "TCombobox",
        arrowcolor=[("disabled", theme.muted_text), ("active", theme.text), ("!disabled", theme.text)],
        background=[("active", theme.soft_border), ("disabled", theme.panel_alt_bg), ("!disabled", theme.panel_alt_bg)],
        fieldbackground=[("readonly", theme.entry_bg), ("disabled", theme.panel_alt_bg), ("!disabled", theme.entry_bg)],
        foreground=[("disabled", theme.muted_text), ("!disabled", theme.text)],
        selectbackground=[("readonly", theme.entry_bg), ("!disabled", theme.entry_bg)],
        selectforeground=[("readonly", theme.text), ("!disabled", theme.text)],
    )
    root.option_add("*TCombobox*Listbox.background", theme.panel_alt_bg)
    root.option_add("*TCombobox*Listbox.foreground", theme.text)
    root.option_add("*TCombobox*Listbox.selectBackground", theme.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", theme.on_accent)
    root.option_add("*TCombobox*Listbox.highlightColor", theme.text)
    root.option_add("*TCombobox*Listbox.highlightBackground", theme.panel_alt_bg)
    style.configure(
        "Accent.TButton",
        background=theme.accent,
        foreground=theme.on_accent,
        borderwidth=0,
        focusthickness=0,
        padding=(10, 5),
    )
    style.map(
        "Accent.TButton",
        background=[("active", theme.accent_dark), ("disabled", theme.soft_border)],
        foreground=[("disabled", theme.muted_text)],
    )
    style.configure(
        "Tool.TButton",
        background=theme.panel_bg,
        foreground=theme.text,
        bordercolor=theme.border,
        lightcolor=theme.border,
        darkcolor=theme.border,
        padding=(8, 4),
    )
    style.map(
        "Tool.TButton",
        background=[("active", theme.panel_alt_bg), ("disabled", theme.panel_alt_bg)],
        foreground=[("disabled", theme.muted_text)],
    )
    style.configure(
        "Icon.TButton",
        background=theme.panel_bg,
        foreground=theme.text,
        bordercolor=theme.border,
        lightcolor=theme.border,
        darkcolor=theme.border,
        padding=(6, 4),
    )
    style.map(
        "Icon.TButton",
        background=[("active", theme.panel_alt_bg), ("disabled", theme.panel_alt_bg)],
        foreground=[("disabled", theme.muted_text)],
    )
