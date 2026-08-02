from __future__ import annotations

from PySide6.QtWidgets import QLabel

from jang_app.qt_app.localization import set_translated_text


def set_model_badge(label: QLabel, text: str, property_name: str, value: object) -> None:
    set_translated_text(label, text)
    label.setProperty(property_name, value)
    label.style().unpolish(label)
    label.style().polish(label)
