from __future__ import annotations

from PySide6.QtWidgets import QLabel


def set_model_badge(label: QLabel, text: str, property_name: str, value: object) -> None:
    label.setText(text)
    label.setProperty(property_name, value)
    label.style().unpolish(label)
    label.style().polish(label)
