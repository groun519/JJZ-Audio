from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QWidget

_DWM_WINDOW_CORNER_PREFERENCE = 33
_DWM_DONOTROUND = 1
_DWM_ROUND = 2
_WINDOW_CORNER_RADIUS = 12.0

CornerPreferenceSetter = Callable[[int, int], int]


def apply_window_corner_style(
    window: QWidget,
    *,
    rounded: bool,
    setter: CornerPreferenceSetter | None = None,
) -> bool:
    preference = _DWM_ROUND if rounded else _DWM_DONOTROUND
    if sys.platform == "win32" or setter is not None:
        set_preference = setter or _set_dwm_corner_preference
        try:
            if set_preference(int(window.winId()), preference) == 0:
                window.clearMask()
                return True
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    if not rounded:
        window.clearMask()
        return True

    path = QPainterPath()
    path.addRoundedRect(QRectF(window.rect()), _WINDOW_CORNER_RADIUS, _WINDOW_CORNER_RADIUS)
    window.setMask(QRegion(path.toFillPolygon().toPolygon()))
    return True


def _set_dwm_corner_preference(window_id: int, preference: int) -> int:
    value = ctypes.c_int(preference)
    return int(
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(window_id),
            ctypes.c_uint(_DWM_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    )
