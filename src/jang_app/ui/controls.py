from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from jang_app.ui.theme import AppTheme, DEFAULT_THEME


class CanvasButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], None] | None = None,
        *,
        theme: AppTheme = DEFAULT_THEME,
        variant: str = "tool",
        width: int = 96,
        height: int = 34,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=theme.panel_bg,
            cursor="hand2",
        )
        self._text = text
        self._command = command
        self._theme = theme
        self._variant = variant
        self._width = width
        self._height = height
        self._is_enabled = True
        self._is_hovered = False

        self.bind("<Enter>", self._handle_enter)
        self.bind("<Leave>", self._handle_leave)
        self.bind("<Button-1>", self._handle_click)
        self._draw()

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self.configure(bg=theme.panel_bg)
        self._draw()

    def configure(self, cnf: dict[str, object] | None = None, **kwargs: object) -> None:  # type: ignore[override]
        options = dict(cnf or {})
        options.update(kwargs)

        should_redraw = False
        if "text" in options:
            self._text = str(options.pop("text"))
            should_redraw = True
        if "state" in options:
            self._is_enabled = options.pop("state") != "disabled"
            super().configure(cursor="hand2" if self._is_enabled else "arrow")
            should_redraw = True
        if "command" in options:
            command = options.pop("command")
            self._command = command if callable(command) else None
        if "variant" in options:
            self._variant = str(options.pop("variant"))
            should_redraw = True
        if "width" in options:
            self._width = int(options["width"])
            should_redraw = True
        if "height" in options:
            self._height = int(options["height"])
            should_redraw = True

        if options:
            super().configure(**options)
        if should_redraw:
            self._draw()

    config = configure

    def cget(self, key: str) -> object:  # type: ignore[override]
        if key == "text":
            return self._text
        if key == "state":
            return "normal" if self._is_enabled else "disabled"
        return super().cget(key)

    def _handle_enter(self, _event: tk.Event) -> None:
        self._is_hovered = True
        self._draw()

    def _handle_leave(self, _event: tk.Event) -> None:
        self._is_hovered = False
        self._draw()

    def _handle_click(self, _event: tk.Event) -> None:
        if self._is_enabled and self._command is not None:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        fill, outline, foreground = self._colors()
        self.create_rectangle(1, 1, self._width - 1, self._height - 1, fill=fill, outline=outline, width=1)
        self.create_text(
            self._width // 2,
            self._height // 2,
            text=self._text,
            fill=foreground,
            font=("Segoe UI", 9, "bold" if self._variant == "primary" else "normal"),
        )

    def _colors(self) -> tuple[str, str, str]:
        theme = self._theme
        if not self._is_enabled:
            return theme.panel_alt_bg, theme.soft_border, theme.muted_text
        if self._variant == "primary":
            return (
                theme.accent_dark if self._is_hovered else theme.accent,
                theme.accent_dark if self._is_hovered else theme.accent,
                theme.on_accent,
            )
        fill = theme.panel_alt_bg if self._is_hovered else theme.panel_bg
        outline = theme.text if self._is_hovered else theme.border
        return fill, outline, theme.text


class VolumeSlider(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        command: Callable[[], None],
        *,
        theme: AppTheme = DEFAULT_THEME,
        width: int = 118,
        height: int = 20,
        value: int = 100,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=theme.panel_bg,
            cursor="hand2",
        )
        self._theme = theme
        self._command = command
        self._width = width
        self._height = height
        self._value = _clamp_percent(value)
        self._is_enabled = True
        self._is_dragging = False

        self.bind("<Button-1>", self._handle_pointer)
        self.bind("<B1-Motion>", self._handle_pointer)
        self.bind("<ButtonRelease-1>", self._handle_release)
        self._draw()

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self.configure(bg=theme.panel_bg)
        self._draw()

    def value(self) -> int:
        return self._value

    def set_value(self, value: int, notify: bool = False) -> None:
        next_value = _clamp_percent(value)
        if next_value == self._value:
            return
        self._value = next_value
        self._draw()
        if notify:
            self._command()

    def configure(self, cnf: dict[str, object] | None = None, **kwargs: object) -> None:  # type: ignore[override]
        options = dict(cnf or {})
        options.update(kwargs)
        if "state" in options:
            self._is_enabled = options.pop("state") != "disabled"
            super().configure(cursor="hand2" if self._is_enabled else "arrow")
            self._draw()
        if options:
            super().configure(**options)

    config = configure

    def _handle_pointer(self, event: tk.Event) -> None:
        if not self._is_enabled:
            return
        self._is_dragging = True
        usable_width = max(1, self._width - 18)
        next_value = round(max(0, min(usable_width, event.x - 9)) / usable_width * 100)
        self.set_value(next_value, notify=True)

    def _handle_release(self, _event: tk.Event) -> None:
        self._is_dragging = False
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        theme = self._theme
        y = self._height // 2
        x0 = 9
        x1 = self._width - 9
        handle_x = x0 + round((x1 - x0) * self._value / 100)
        track = theme.soft_border
        active = theme.text if self._is_enabled else theme.muted_text
        handle = theme.panel_bg if self._is_enabled else theme.panel_alt_bg
        outline = theme.text if self._is_enabled else theme.soft_border

        self.create_line(x0, y, x1, y, fill=track, width=2)
        self.create_line(x0, y, handle_x, y, fill=active, width=3)
        self.create_rectangle(handle_x - 5, y - 7, handle_x + 5, y + 7, fill=handle, outline=outline, width=1)


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))
