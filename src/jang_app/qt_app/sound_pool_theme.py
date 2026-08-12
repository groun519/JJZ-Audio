from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget


def apply_sound_pool_theme(widget: QWidget, theme_mode: str) -> None:
    widget.setStyleSheet(sound_pool_stylesheet(theme_mode))


def sound_pool_stylesheet(theme_mode: str) -> str:
    colors = _sound_pool_colors(theme_mode)
    return f"""
        QFrame#SeparationStemPoolPanel {{
            background: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 18px;
        }}

        QFrame#VocalVersionPool,
        QFrame#SoundPoolList,
        QFrame#ConversionVocalPool {{
            background: {colors['card']};
            border: 1px solid {colors['border']};
            border-radius: 13px;
        }}

        QScrollArea#SoundPoolListScroll,
        QScrollArea#SoundPoolListScroll > QWidget > QWidget,
        QWidget#SoundPoolListContent {{
            background: transparent;
            border: 0;
        }}

        QLabel#SoundPoolListTitle {{
            color: {colors['text']};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#ConversionPoolTitle {{
            color: {colors['text']};
            background: transparent;
            border: 0;
            font-size: 18px;
            font-weight: 800;
        }}

        QLabel#SoundPoolListCount,
        QLabel#SeparationPairStatus {{
            color: {colors['muted']};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 800;
        }}

        QLabel#SeparationPairStatus[paired="true"] {{
            color: {colors['pair_accent']};
        }}

        QLabel#SoundPoolListEmpty {{
            min-height: 60px;
            color: {colors['muted']};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QFrame#VocalVersionCard,
        QFrame#ConversionVocalCard,
        QFrame#SoundPoolItemCard {{
            background: {colors['raised']};
            border: 1px solid {colors['border']};
            border-radius: 13px;
        }}

        QFrame#VocalVersionCard:hover,
        QFrame#ConversionVocalCard:hover,
        QFrame#SoundPoolItemCard:hover {{
            background: {colors['hover']};
            border-color: {colors['button_border']};
        }}

        QFrame#VocalVersionCard[selected="true"],
        QFrame#ConversionVocalCard[selected="true"],
        QFrame#SoundPoolItemCard[selected="true"] {{
            background: {colors['selection']};
            border-color: {colors['focus']};
        }}

        QFrame#VocalVersionCard[selected="true"][linkedSelection="true"] {{
            background: {colors['pair_background']};
            border-color: {colors['pair_border']};
        }}

        QFrame#VocalVersionCard[selected="true"][linkedSelection="true"]
        QWidget#StudioSoundCardTitle {{
            color: {colors['pair_accent']};
        }}

        QFrame#VocalVersionCard[selected="true"][linkedSelection="true"]
        QFrame#StudioSoundRoleStrip {{
            background: {colors['pair_accent']};
        }}

        QFrame#StudioSoundRoleStrip {{
            background: {colors['muted']};
            border: 0;
            border-radius: 1px;
        }}

        QFrame#StudioSoundRoleStrip[role="original_vocal"] {{
            background: #d6a85f;
        }}

        QFrame#StudioSoundRoleStrip[role="instrumental"] {{
            background: #58a88f;
        }}

        QFrame#StudioSoundRoleStrip[role="converted_vocal"] {{
            background: #d2675a;
        }}

        QWidget#StudioSoundCardTitle {{
            color: {colors['text']};
            background: transparent;
            border: 0;
            font-size: 11px;
            font-weight: 900;
        }}

        QLabel#StudioSoundCardDetail,
        QLabel#StudioSoundDuration {{
            color: {colors['muted']};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QLabel#StudioSoundSourceBadge {{
            padding: 2px 6px;
            color: {colors['text']};
            background: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 7px;
            font-size: 8px;
            font-weight: 900;
        }}

        QLabel#StudioSoundSourceBadge[role="original_vocal"] {{
            color: #d6a85f;
            border-color: #80693f;
        }}

        QLabel#StudioSoundSourceBadge[role="instrumental"] {{
            color: #65b99f;
            border-color: #3f7565;
        }}

        QLabel#StudioSoundSourceBadge[role="converted_vocal"] {{
            color: #df7770;
            border-color: #864b47;
        }}
    """


def pair_button_palette(
    theme_mode: str,
    *,
    checked: bool,
    enabled: bool,
    hovered: bool,
    pressed: bool,
) -> dict[str, QColor]:
    colors = _sound_pool_colors(theme_mode)
    transparent = QColor(0, 0, 0, 0)
    if not enabled:
        return {
            "background": transparent,
            "border": QColor(colors["border"]),
            "icon": QColor(colors["faint"]),
        }
    if checked:
        if pressed:
            background = colors["pair_pressed"]
        elif hovered:
            background = colors["pair_hover"]
        else:
            background = colors["pair_background"]
        return {
            "background": QColor(background),
            "border": QColor(colors["pair_border"]),
            "icon": QColor(colors["pair_accent"]),
        }
    return {
        "background": QColor(colors["hover"]) if hovered or pressed else transparent,
        "border": QColor(colors["button_border"]),
        "icon": QColor(colors["muted"]),
    }


def _sound_pool_colors(theme_mode: str) -> dict[str, str]:
    if theme_mode == "dark":
        return {
            "surface": "#1b1b1a", "card": "#212120", "raised": "#272725",
            "text": "#ecebe7", "muted": "#aaa8a1", "faint": "#6c6b66",
            "border": "#383835", "button_border": "#484843", "hover": "#30302e",
            "selection": "#323230", "focus": "#898780", "pair_accent": "#f2c45c",
            "pair_background": "#302817", "pair_hover": "#40351d",
            "pair_pressed": "#4a3d21", "pair_border": "#8c6d27",
        }
    return {
        "surface": "#fffdf7", "card": "#fffdf7", "raised": "#ebe7dd",
        "text": "#10100e", "muted": "#6e6a61", "faint": "#aaa397",
        "border": "#d8d0c2", "button_border": "#10100e", "hover": "#e7e1d5",
        "selection": "#ded6ca", "focus": "#6e6a61", "pair_accent": "#8a6200",
        "pair_background": "#fff1bf", "pair_hover": "#f9e6a3",
        "pair_pressed": "#efd27b", "pair_border": "#c38d13",
    }
