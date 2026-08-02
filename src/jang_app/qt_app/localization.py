from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget

from jang_app.services.i18n import has_translation, tr

_TEXT_BINDING = "_jj_i18n_text"
_TOOLTIP_BINDING = "_jj_i18n_tooltip"
_PLACEHOLDER_BINDING = "_jj_i18n_placeholder"


def set_translated_text(widget: object, source: str, **values: object) -> None:
    setattr(widget, _TEXT_BINDING, (source, values))
    setter = getattr(widget, "setText", None)
    if callable(setter):
        setter(tr(source, **values))


def set_translated_tooltip(widget: QWidget, source: str, **values: object) -> None:
    setattr(widget, _TOOLTIP_BINDING, (source, values))
    widget.setToolTip(tr(source, **values))


def set_translated_placeholder(widget: QLineEdit, source: str, **values: object) -> None:
    setattr(widget, _PLACEHOLDER_BINDING, (source, values))
    widget.setPlaceholderText(tr(source, **values))


def apply_widget_language(root: QWidget) -> None:
    for widget in (root, *root.findChildren(QWidget)):
        _apply_binding(widget, _TEXT_BINDING, getattr(widget, "setText", None), _current_text(widget))
        _apply_binding(widget, _TOOLTIP_BINDING, widget.setToolTip, widget.toolTip())
        if isinstance(widget, QLineEdit):
            _apply_binding(
                widget,
                _PLACEHOLDER_BINDING,
                widget.setPlaceholderText,
                widget.placeholderText(),
            )


def _apply_binding(
    widget: QWidget,
    attribute: str,
    setter: Callable[[str], None] | None,
    current_text: str,
) -> None:
    if setter is None:
        return
    binding = getattr(widget, attribute, None)
    if binding is None:
        if not current_text or not has_translation(current_text):
            return
        binding = (current_text, {})
        setattr(widget, attribute, binding)
    source, values = binding
    setter(tr(source, **values))


def _current_text(widget: QWidget) -> str:
    if isinstance(widget, (QAbstractButton, QLabel)):
        return widget.text()
    return ""
