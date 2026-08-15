from __future__ import annotations

def next_theme_mode(theme_mode: str) -> str:
    return "dark" if theme_mode == "white" else "white"


def build_stylesheet(theme_mode: str) -> str:
    from jang_app.config import ASSETS_DIR

    icon_tone = "light" if theme_mode == "dark" else "dark"
    check_tone = "dark" if theme_mode == "dark" else "light"
    chevron_down = (ASSETS_DIR / f"control_chevron_down_{icon_tone}.svg").as_posix()
    chevron_up = (ASSETS_DIR / f"control_chevron_up_{icon_tone}.svg").as_posix()
    check_icon = (ASSETS_DIR / f"control_check_{check_tone}.svg").as_posix()
    return _stylesheet(
        **theme_tokens(theme_mode),
        chevron_down=chevron_down,
        chevron_up=chevron_up,
        check_icon=check_icon,
    )


def theme_tokens(theme_mode: str) -> dict[str, str]:
    if theme_mode == "dark":
        return {
            "background": "#151515",
            "chrome": "#111111",
            "surface": "#1b1b1a",
            "card": "#212120",
            "raised": "#272725",
            "text": "#ecebe7",
            "muted": "#aaa8a1",
            "faint": "#6c6b66",
            "border": "#383835",
            "button_border": "#484843",
            "accent": "#efeee9",
            "accent_text": "#171717",
            "hover": "#30302e",
            "pressed": "#3a3a37",
            "selection": "#323230",
            "active_hover": "#e0dfd9",
            "active_pressed": "#c9c8c2",
            "focus": "#898780",
            "tab_active": "#30302e",
            "tab_active_text": "#ecebe7",
            "tab_active_hover": "#393936",
            "tab_active_pressed": "#444440",
            "tab_active_border": "#4b4b46",
            "source_local_text": "#c7d6e8",
            "source_local_background": "#202a34",
            "source_local_border": "#40566c",
            "source_youtube_text": "#ffd4d4",
            "source_youtube_background": "#3a2022",
            "source_youtube_border": "#7a3a3f",
            "source_output_text": "#c9f0dc",
            "source_output_background": "#1f3128",
            "source_output_border": "#3f6b53",
            "success_text": "#b9dfc9",
            "success_background": "#1f3128",
            "success_border": "#3f6b53",
            "warning_text": "#e7d3a0",
            "warning_background": "#332d20",
            "warning_border": "#685b34",
            "danger_text": "#f0b4b4",
            "danger_background": "#3a2022",
            "danger_border": "#7a3a3f",
            "pair_accent": "#f2c45c",
            "pair_background": "#302817",
            "pair_border": "#8c6d27",
        }

    return {
        "background": "#f6f3ec",
        "chrome": "#fffdf7",
        "surface": "#fffdf7",
        "card": "#fffdf7",
        "raised": "#ebe7dd",
        "text": "#10100e",
        "muted": "#6e6a61",
        "faint": "#aaa397",
        "border": "#d8d0c2",
        "button_border": "#10100e",
        "accent": "#10100e",
        "accent_text": "#fffdf7",
        "hover": "#e7e1d5",
        "pressed": "#d1c8b8",
        "selection": "#ded6ca",
        "active_hover": "#2b2a26",
        "active_pressed": "#46443e",
        "focus": "#6e6a61",
        "tab_active": "#10100e",
        "tab_active_text": "#fffdf7",
        "tab_active_hover": "#2b2a26",
        "tab_active_pressed": "#46443e",
        "tab_active_border": "#10100e",
        "source_local_text": "#244664",
        "source_local_background": "#e5eef5",
        "source_local_border": "#9bb3c6",
        "source_youtube_text": "#8a2930",
        "source_youtube_background": "#f6e4e4",
        "source_youtube_border": "#d7a2a5",
        "source_output_text": "#24543c",
        "source_output_background": "#e2f0e8",
        "source_output_border": "#9abda8",
        "success_text": "#24543c",
        "success_background": "#e2f0e8",
        "success_border": "#9abda8",
        "warning_text": "#765814",
        "warning_background": "#f5ecd5",
        "warning_border": "#d3bd83",
        "danger_text": "#8a2930",
        "danger_background": "#f6e4e4",
        "danger_border": "#d7a2a5",
        "pair_accent": "#8a6200",
        "pair_background": "#fff1bf",
        "pair_border": "#c38d13",
    }


def _stylesheet(
    *,
    background: str,
    chrome: str,
    surface: str,
    card: str,
    raised: str,
    text: str,
    muted: str,
    faint: str,
    border: str,
    button_border: str,
    accent: str,
    accent_text: str,
    hover: str,
    pressed: str,
    selection: str,
    active_hover: str,
    active_pressed: str,
    focus: str,
    tab_active: str,
    tab_active_text: str,
    tab_active_hover: str,
    tab_active_pressed: str,
    tab_active_border: str,
    source_local_text: str,
    source_local_background: str,
    source_local_border: str,
    source_youtube_text: str,
    source_youtube_background: str,
    source_youtube_border: str,
    source_output_text: str,
    source_output_background: str,
    source_output_border: str,
    success_text: str,
    success_background: str,
    success_border: str,
    warning_text: str,
    warning_background: str,
    warning_border: str,
    danger_text: str,
    danger_background: str,
    danger_border: str,
    pair_accent: str,
    pair_background: str,
    pair_border: str,
    chevron_down: str,
    chevron_up: str,
    check_icon: str,
) -> str:
    return f"""
        QWidget {{
            color: {text};
            font-family: "Malgun Gothic", "Segoe UI", "Arial";
            font-size: 13px;
        }}

        QMainWindow, QDialog,
        QWidget[surfaceRole="background"] {{
            background: {background};
        }}

        QWidget[surfaceRole="transparent"] {{
            background: transparent;
            border: 0;
        }}

        QFrame[surfaceRole="surface"] {{
            background: {surface};
        }}

        QFrame[surfaceRole="card"] {{
            background: {card};
        }}

        QFrame[surfaceRole="raised"] {{
            background: {raised};
        }}

        QLabel {{
            background: transparent;
        }}

        QLabel#AppTitle {{
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -1px;
        }}

        QLabel#SectionTitle {{
            font-size: 18px;
            font-weight: 800;
        }}

        QLabel#CardTitle {{
            font-size: 15px;
            font-weight: 800;
        }}

        QLabel#MutedText {{
            color: {muted};
        }}

        QFrame#WindowTitleBar {{
            background: {chrome};
            border: 0;
            border-bottom: 1px solid {border};
            border-radius: 0;
        }}

        QFrame#WindowTitleBar QLabel#AppTitle {{
            font-size: 16px;
            font-weight: 900;
            letter-spacing: 0;
        }}

        QFrame#WindowTitleBar QLabel#AppVersion {{
            color: {muted};
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0;
        }}

        QFrame#NavigationDock {{
            background: {chrome};
            border: 0;
            border-radius: 0;
        }}

        QPushButton#NavigationItemButton {{
            padding: 0;
            border: 0;
            border-radius: 12px;
            background: transparent;
        }}

        QLabel#NavigationWorkSongPopupTitle {{
            color: {text};
            font-size: 14px;
            font-weight: 900;
        }}

        QLabel#NavigationWorkSongPopupCount {{
            min-width: 28px;
            max-width: 28px;
            min-height: 22px;
            max-height: 22px;
            color: {muted};
            background: {raised};
            border: 1px solid {border};
            border-radius: 8px;
            qproperty-alignment: AlignCenter;
            font-size: 10px;
            font-weight: 800;
        }}

        QLineEdit#NavigationWorkSongSearch {{
            min-height: 34px;
            max-height: 34px;
            padding: 0 11px;
            background: {raised};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QLineEdit#NavigationWorkSongSearch:focus {{
            border-color: {button_border};
        }}

        QFrame#NavigationGroupDivider {{
            background: {border};
            border: 0;
        }}

        QWidget#AppContent {{
            background: {background};
            border: 0;
        }}

        QFrame#ResultTransportBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QLabel#VocalResultSongTitle {{
            color: {muted};
            font-size: 12px;
            font-weight: 750;
        }}

        QFrame#StudioTransportBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QWidget#StudioPreviewArea {{
            background: transparent;
            border: 0;
        }}

        QLabel#StudioTransportToolLabel {{
            color: {muted};
            font-size: 11px;
            font-weight: 800;
        }}

        QFrame#StudioTransportDivider {{
            background: {border};
            border: 0;
        }}

        QComboBox#WorkSongCombo {{
            min-height: 24px;
            max-height: 24px;
            font-size: 13px;
            font-weight: 850;
            background: {raised};
        }}

        QLabel#PlaybackScopeLabel {{
            min-height: 24px;
            max-height: 24px;
            padding: 0 10px;
            color: {muted};
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 850;
        }}

        QComboBox#ExportSongCombo {{
            min-height: 32px;
            max-height: 32px;
            font-size: 13px;
            font-weight: 850;
            background: {raised};
        }}

        QWidget#TitleBarCenter, QWidget#TitleBarActions {{
            background: transparent;
            border: 0;
        }}

        QFrame#WindowControlGroup {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#WindowControlGroup[compactControls="true"] {{
            background: transparent;
            border: 0;
            border-radius: 0;
        }}

        QFrame#TitleBarControlDivider {{
            background: {border};
            border: 0;
        }}

        QLabel#AppLogo {{
            background: transparent;
            border: 0;
            border-radius: 10px;
        }}

        QFrame#Panel {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#StudioInspector {{
            background: {surface};
            border: 0;
        }}

        QStackedWidget#StudioInspectorStack,
        QWidget#StudioInspectorEmptyPage,
        QWidget#StudioInspectorSectionContent {{
            background: transparent;
            border: 0;
        }}

        QFrame#StudioInspectorHeader {{
            background: transparent;
            border: 0;
            min-height: 42px;
        }}

        QLabel#StudioInspectorKind {{
            min-height: 22px;
            max-height: 22px;
            padding: 0 7px;
            color: {muted};
            background: {raised};
            border: 1px solid {border};
            border-radius: 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#StudioInspectorName {{
            color: {text};
            font-size: 13px;
            font-weight: 850;
        }}

        QFrame#StudioInspectorSection {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QLabel#StudioInspectorSectionTitle {{
            color: {text};
            font-size: 12px;
            font-weight: 850;
        }}

        QPushButton#StudioInspectorSectionToggle {{
            min-height: 26px;
            max-height: 26px;
            padding: 0 9px;
            color: {muted};
            background: transparent;
            border: 1px solid {border};
            border-radius: 8px;
            font-size: 10px;
            font-weight: 800;
        }}

        QPushButton#StudioInspectorSectionToggle:hover {{
            color: {text};
            background: {hover};
            border-color: {focus};
        }}

        QLabel#StudioInspectorReadOnlyValue {{
            min-height: 30px;
            padding: 0 8px;
            color: {text};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            font-weight: 750;
        }}

        QLabel#StudioInspectorSliderValue {{
            color: {muted};
            font-size: 11px;
            font-weight: 800;
        }}

        QDoubleSpinBox#StudioInspectorGainSpin {{
            min-height: 32px;
            max-height: 32px;
            padding-left: 8px;
            padding-right: 26px;
        }}

        QFrame#StudioInspectorTabs {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 11px;
        }}

        QPushButton#StudioInspectorTab {{
            min-height: 28px;
            max-height: 28px;
            padding: 0 11px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            font-size: 10px;
            font-weight: 850;
        }}

        QPushButton#StudioInspectorTab:hover,
        QPushButton#StudioInspectorTab[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#StudioInspectorTab:checked {{
            color: {text};
            background: {surface};
            border-color: {button_border};
        }}

        QStackedWidget#StudioInspectorDetailStack,
        QWidget#StudioReverbEditor,
        QWidget#StudioCharacterEffectEditor {{
            background: transparent;
            border: 0;
        }}

        QFrame#StudioReverbSection,
        QFrame#StudioCharacterFxSection {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#StudioReverbPresetSection,
        QFrame#StudioCharacterFxPresetSection {{
            background: {surface};
            border: 1px solid {button_border};
            border-radius: 12px;
        }}

        QFrame#StudioReverbActionBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
            min-height: 38px;
            max-height: 38px;
        }}

        QComboBox#StudioReverbPresetCombo,
        QComboBox#StudioCharacterFxPresetCombo {{
            min-height: 32px;
            max-height: 32px;
            padding-left: 10px;
            padding-right: 28px;
        }}

        QPushButton#StudioEffectToggle {{
            min-width: 52px;
            max-width: 52px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            color: {faint};
            background: {raised};
            border: 1px solid {button_border};
            border-radius: 15px;
            font-size: 9px;
            font-weight: 900;
        }}

        QPushButton#StudioEffectToggle:hover,
        QPushButton#StudioEffectToggle[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#StudioEffectToggle:checked {{
            color: {success_text};
            background: {success_background};
            border-color: {success_border};
        }}

        QPushButton#StudioEffectToggle:checked:hover,
        QPushButton#StudioEffectToggle:checked[pointerState="hover"] {{
            color: {text};
            border-color: {success_text};
        }}

        QPushButton#ToggleSwitchButton {{
            min-width: 42px;
            max-width: 42px;
            min-height: 24px;
            max-height: 24px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QSpinBox#StudioReverbControl,
        QDoubleSpinBox#StudioReverbControl,
        QSpinBox#StudioCharacterFxControl {{
            min-height: 30px;
            max-height: 30px;
            padding-left: 8px;
            padding-right: 26px;
            font-size: 10px;
        }}

        QFrame#VideoPreviewPanel {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QSplitter[workspaceSplitter="true"] {{
            background: transparent;
        }}

        QSplitter[workspaceSplitter="true"]::handle:horizontal {{
            width: 6px;
            border: 0;
            background: transparent;
        }}

        QSplitter[workspaceSplitter="true"]::handle:horizontal:hover {{
            border: 0;
            background: transparent;
        }}

        QSplitter[workspaceSplitter="true"]::handle:vertical {{
            height: 6px;
            border: 0;
            background: transparent;
        }}

        QSplitter[workspaceSplitter="true"]::handle:vertical:hover {{
            border: 0;
            background: transparent;
        }}

        QWidget#VideoCanvas, QFrame#VideoCanvas {{
            background: #080808;
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#VideoSourceCanvas {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#VideoSourceCard {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 13px;
        }}

        QFrame#VideoUrlField {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 11px;
        }}

        QFrame#VideoUrlField:focus-within {{
            border-color: {focus};
        }}

        QLineEdit#VideoUrlEdit {{
            background: transparent;
            border: 0;
            border-radius: 0;
            padding: 0;
            min-height: 28px;
        }}

        QComboBox#VideoSourceCombo {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 30px 0 11px;
            border-radius: 10px;
        }}

        QWidget#VideoOriginalUrlSlot {{
            background: transparent;
            border: 0;
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
        }}

        QScrollArea#StudioStepScroll {{
            background: transparent;
            border: 0;
        }}

        QScrollArea#StudioStepScroll > QWidget > QWidget {{
            background: transparent;
        }}

        QScrollArea#RvcSettingsScroll,
        QScrollArea#RvcSettingsScroll > QWidget > QWidget,
        QWidget#RvcSettingsScrollContent {{
            background: transparent;
            border: 0;
        }}

        QFrame#Card, QFrame#TrackCard {{
            background: {card};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#StudioSoundPool {{
            background: {card};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#StudioFxPool {{
            background: {card};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QScrollArea#StudioSoundPoolScroll,
        QScrollArea#StudioSoundPoolScroll > QWidget > QWidget,
        QWidget#StudioSoundPoolContent,
        QScrollArea#StudioFxPoolScroll,
        QScrollArea#StudioFxPoolScroll > QWidget > QWidget,
        QWidget#StudioFxPoolContent {{
            background: transparent;
            border: 0;
        }}

        QFrame#StudioFxCard {{
            min-height: 48px;
            max-height: 48px;
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#StudioFxCard:hover {{
            background: {hover};
            border-color: {focus};
        }}

        QLabel#StudioFxCardIcon {{
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
            color: {text};
            background: {surface};
            border: 1px solid {button_border};
            border-radius: 8px;
            qproperty-alignment: AlignCenter;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#StudioFxCardName {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 11px;
            font-weight: 900;
        }}

        QLabel#StudioFxCardDetail {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QLabel#StudioFxGroupLabel {{
            color: {muted};
            background: transparent;
            border: 0;
            padding: 4px 2px 2px 2px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#StudioEffectReferenceStatus {{
            color: {warning_text};
            background: {warning_background};
            border: 1px solid {warning_border};
            border-radius: 9px;
            padding: 8px 10px;
            font-size: 9px;
            font-weight: 800;
        }}

        QLabel#StudioEffectReferenceStatus[available="true"] {{
            color: {success_text};
            background: {success_background};
            border-color: {success_border};
        }}

        QLineEdit#StudioSoundSearch {{
            min-height: 32px;
            max-height: 32px;
            border-radius: 9px;
            font-size: 10px;
        }}

        QFrame#StudioSoundRoleFilter {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
        }}

        QPushButton#StudioSoundRoleButton {{
            min-width: 0;
            min-height: 25px;
            max-height: 25px;
            padding: 0 6px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QPushButton#StudioSoundRoleButton:hover,
        QPushButton#StudioSoundRoleButton[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#StudioSoundRoleButton:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#StudioSoundCount {{
            min-width: 20px;
            padding: 2px 6px;
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#StudioSoundEmpty {{
            min-height: 100px;
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 700;
        }}

        QFrame#StudioSoundCard,
        QFrame#VocalVersionCard {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 13px;
        }}

        QFrame#StudioSoundCard:hover,
        QFrame#VocalVersionCard:hover {{
            background: {hover};
            border-color: {button_border};
        }}

        QFrame#StudioSoundCard[selected="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QFrame#VocalVersionCard[selected="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QFrame#VocalVersionCard[selected="true"][linkedSelection="true"] {{
            background: {pair_background};
            border-color: {pair_border};
        }}

        QFrame#VocalVersionCard[selected="true"][linkedSelection="true"] QWidget#StudioSoundCardTitle {{
            color: {pair_accent};
        }}

        QFrame#VocalVersionCard[selected="true"][linkedSelection="true"] QFrame#StudioSoundRoleStrip {{
            background: {pair_accent};
        }}

        QFrame#SeparationStemPoolPanel {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#VocalVersionPool,
        QFrame#SoundPoolList {{
            background: {card};
            border: 1px solid {border};
            border-radius: 13px;
        }}

        QLabel#SoundPoolListTitle {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#SoundPoolListCount,
        QLabel#SeparationPairStatus {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 800;
        }}

        QLabel#SeparationPairStatus[paired="true"] {{
            color: {pair_accent};
        }}

        QLabel#SoundPoolListEmpty {{
            min-height: 60px;
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QFrame#StudioSoundRoleStrip {{
            background: {muted};
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

        QFrame#StudioSoundRoleStrip[role="video"] {{
            background: #668cc4;
        }}

        QLabel#StudioVideoThumbnail {{
            color: #a9c8f2;
            background: #151c26;
            border: 1px solid #3d5575;
            border-radius: 8px;
            font-size: 10px;
            font-weight: 900;
            letter-spacing: 2px;
        }}

        QWidget#StudioSoundCardTitle {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 11px;
            font-weight: 900;
        }}

        QLabel#StudioSoundCardDetail,
        QLabel#StudioSoundDuration {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QLabel#StudioSoundSourceBadge {{
            padding: 2px 6px;
            color: {text};
            background: {surface};
            border: 1px solid {border};
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

        QLabel#StudioSoundSourceBadge[role="video"] {{
            color: #8bb5ec;
            border-color: #4d6e98;
        }}

        QFrame#ModelWorkspaceHeader {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 16px;
        }}

        QLabel#ModelWorkspaceTitle {{
            color: {text};
            font-size: 16px;
            font-weight: 900;
        }}

        QLabel#ModelWorkspaceSection {{
            color: {muted};
            font-size: 11px;
            font-weight: 800;
        }}

        QFrame#TrainingStatusCard, QFrame#TrainingSettingsCard,
        QFrame#TrainingReadinessCard, QFrame#TrainingMonitorCard {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QLabel#TrainingMonitorRuntime, QLabel#TrainingMonitorLegend {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 800;
        }}

        QFrame#TrainingMetricCard, QFrame#TrainingPerformanceStrip {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QLabel#TrainingMetricTitle, QLabel#TrainingMonitorGraphTitle {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 800;
        }}

        QLabel#TrainingMetricValue, QLabel#TrainingPerformanceValue {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 900;
        }}

        QProgressBar#TrainingMetricProgress {{
            min-height: 5px;
            max-height: 5px;
            background: {border};
            border: 0;
            border-radius: 2px;
        }}

        QProgressBar#TrainingMetricProgress::chunk {{
            background: {accent};
            border-radius: 2px;
        }}

        QProgressBar#TrainingMetricProgress[available="false"]::chunk {{
            background: {faint};
        }}

        QWidget#TrainingTelemetryGraph {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QFrame#TrainingAssessmentCard {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QFrame#TrainingAssessmentCard[health="stable"] {{
            border-color: {success_border};
        }}

        QFrame#TrainingAssessmentCard[health="memory_pressure"],
        QFrame#TrainingAssessmentCard[health="accelerator_unavailable"] {{
            background: {danger_background};
            border-color: {danger_border};
        }}

        QFrame#TrainingAssessmentCard[health="gpu_underused"],
        QFrame#TrainingAssessmentCard[health="data_supply"],
        QFrame#TrainingAssessmentCard[health="monitor_unavailable"] {{
            border-color: {warning_border};
        }}

        QLabel#TrainingAssessmentTitle {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#TrainingAssessmentDetail {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QFrame#TrainingLogConsole {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QLabel#TrainingLogTitle {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 12px;
            font-weight: 900;
        }}

        QLabel#TrainingLogNewLines {{
            color: {accent};
            background: {surface};
            border: 1px solid {success_border};
            border-radius: 8px;
            padding: 3px 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QComboBox#TrainingLogFilter, QLineEdit#TrainingLogSearch {{
            min-height: 30px;
            max-height: 30px;
        }}

        QComboBox#TrainingLogFilter {{
            min-width: 94px;
            max-width: 118px;
        }}

        QLineEdit#TrainingLogSearch {{
            min-width: 130px;
            max-width: 220px;
        }}

        QPushButton#TrainingLogToggleButton,
        QPushButton#TrainingLogActionButton {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 11px;
        }}

        QPushButton#TrainingLogToggleButton:checked {{
            color: {text};
            background: {selection};
            border-color: {success_border};
        }}

        QPlainTextEdit#TrainingLogOutput {{
            color: {text};
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 8px;
            font-family: "Cascadia Mono", "Consolas";
            font-size: 10px;
            selection-background-color: {selection};
        }}

        QFrame#TrainingRecoveryCard {{
            background: {danger_background};
            border: 1px solid {danger_border};
            border-radius: 14px;
        }}

        QFrame#TrainingInputNotice {{
            background: {danger_background};
            border: 1px solid {danger_border};
            border-radius: 14px;
        }}

        QLabel#TrainingInputNoticeTitle {{
            color: {danger_text};
            background: transparent;
            border: 0;
            font-size: 12px;
            font-weight: 900;
        }}

        QLabel#TrainingInputNoticeDetail {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#TrainingInputNoticeBadge {{
            min-width: 76px;
            padding: 4px 9px;
            color: {danger_text};
            background: {surface};
            border: 1px solid {danger_border};
            border-radius: 9px;
            font-size: 9px;
            font-weight: 900;
        }}

        QComboBox#TrainingExcludedClipCombo {{
            min-height: 32px;
            max-height: 32px;
        }}

        QPushButton#TrainingExcludedClipButton {{
            min-height: 32px;
            max-height: 32px;
            padding: 0 14px;
        }}

        QLabel#TrainingRecoveryCode {{
            color: {danger_text};
            background: {surface};
            border: 1px solid {danger_border};
            border-radius: 8px;
            padding: 3px 8px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#TrainingRecoveryTitle {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 12px;
            font-weight: 900;
        }}

        QLabel#TrainingRecoveryDetail {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 700;
        }}

        QPushButton#TrainingRecoverySecondaryButton {{
            min-height: 32px;
            max-height: 32px;
            padding: 0 14px;
        }}

        QLabel#TrainingStatusTitle {{
            color: {text};
            font-size: 15px;
            font-weight: 900;
        }}

        QLabel#TrainingStatusTitle[phase="complete"],
        QLabel#TrainingStatusTitle[phase="index_ready"] {{
            color: {accent};
        }}

        QLabel#TrainingStatusTitle[phase="failed"] {{
            color: {danger_text};
        }}

        QLabel#TrainingStageText, QLabel#TrainingFieldLabel {{
            color: {muted};
            font-size: 10px;
            font-weight: 800;
        }}

        QLabel#TrainingCardTitle {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
        }}

        QLabel#TrainingActivityText {{
            color: {accent};
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#TrainingActivityText[state="quiet"] {{
            color: {muted};
        }}

        QLabel#TrainingActivityText[state="stale"] {{
            color: {warning_text};
        }}

        QFrame#TrainingActivityCard {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QLabel#TrainingActivityDetail {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 800;
        }}

        QLabel#TrainingProgressHeading {{
            color: {text};
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#TrainingProgressText, QLabel#TrainingRuntimeText {{
            color: {muted};
            font-size: 10px;
            font-weight: 800;
        }}

        QLabel#TrainingProfileBadge, QLabel#TrainingComputeBadge, QLabel#TrainingEpochBadge {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
            padding: 4px 9px;
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#TrainingEpochBadge {{
            color: {text};
        }}

        QLabel#TrainingComputeBadge {{
            color: {text};
        }}

        QWidget#TrainingWorkflow {{
            background: transparent;
        }}

        QFrame#WorkflowStage {{
            background: transparent;
            border: 0;
        }}

        QLabel#WorkflowStageMarker {{
            color: {faint};
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#WorkflowStageLabel {{
            color: {faint};
            font-size: 9px;
            font-weight: 800;
        }}

        QLabel#WorkflowStageMarker[stageState="active"] {{
            color: {accent_text};
            background: {accent};
            border-color: {accent};
        }}

        QLabel#WorkflowStageLabel[stageState="active"] {{
            color: {text};
        }}

        QLabel#WorkflowStageMarker[stageState="complete"] {{
            color: {success_text};
            background: {success_background};
            border-color: {success_border};
        }}

        QLabel#WorkflowStageLabel[stageState="complete"] {{
            color: {success_text};
        }}

        QLabel#WorkflowStageMarker[stageState="failed"] {{
            color: {danger_text};
            background: {danger_background};
            border-color: {danger_border};
        }}

        QLabel#WorkflowStageLabel[stageState="failed"] {{
            color: {danger_text};
        }}

        QFrame#WorkflowConnector {{
            min-width: 14px;
            max-height: 1px;
            background: {border};
            border: 0;
        }}

        QFrame#WorkflowConnector[stageState="complete"] {{
            background: {success_border};
        }}

        QFrame#TrainingMetric {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QLabel#TrainingMetricLabel {{
            color: {faint};
            font-size: 9px;
            font-weight: 800;
        }}

        QLabel#TrainingMetricValue {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
        }}

        QFrame#TrainingPreflightCheck {{
            background: {surface};
            border: 1px solid {border};
            border-left: 3px solid {border};
            border-radius: 9px;
        }}

        QFrame#TrainingPreflightCheck[checkLevel="ready"] {{
            border-left-color: {success_border};
        }}

        QFrame#TrainingPreflightCheck[checkLevel="warning"] {{
            border-left-color: {warning_border};
        }}

        QFrame#TrainingPreflightCheck[checkLevel="blocker"] {{
            border-left-color: {danger_border};
        }}

        QLabel#TrainingPreflightTitle {{
            color: {text};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#TrainingPreflightDetail {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 9px;
            font-weight: 700;
        }}

        QLabel#TrainingReadinessBadge {{
            padding: 4px 9px;
            color: {faint};
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#TrainingReadinessBadge[readiness="ready"] {{
            color: {success_text};
            background: {success_background};
            border-color: {success_border};
        }}

        QLabel#TrainingReadinessBadge[readiness="review"] {{
            color: {warning_text};
            background: {warning_background};
            border-color: {warning_border};
        }}

        QLabel#TrainingReadinessBadge[readiness="blocked"] {{
            color: {danger_text};
            background: {danger_background};
            border-color: {danger_border};
        }}

        QFrame#TrainingModeControl, QFrame#TrainingPresetControl {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QPushButton#TrainingModeButton, QPushButton#TrainingPresetButton {{
            min-width: 76px;
            min-height: 26px;
            max-height: 26px;
            padding: 0 10px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QPushButton#TrainingModeButton:hover,
        QPushButton#TrainingModeButton[pointerState="hover"],
        QPushButton#TrainingPresetButton:hover,
        QPushButton#TrainingPresetButton[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#TrainingModeButton:checked,
        QPushButton#TrainingPresetButton:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QPushButton#TrainingModeButton:pressed,
        QPushButton#TrainingModeButton[pointerState="pressed"],
        QPushButton#TrainingPresetButton:pressed,
        QPushButton#TrainingPresetButton[pointerState="pressed"] {{
            background: {pressed};
        }}

        QPushButton#TrainingModeButton:disabled,
        QPushButton#TrainingPresetButton:disabled {{
            color: {faint};
            background: transparent;
            border-color: transparent;
        }}

        QPushButton#TrainingModeButton:checked:disabled,
        QPushButton#TrainingPresetButton:checked:disabled {{
            color: {muted};
            background: {selection};
            border-color: {border};
        }}

        QLabel#TrainingPresetSummary {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QWidget#TrainingFieldHeader {{
            background: transparent;
            border: 0;
        }}

        QPushButton#InfoPopoverButton {{
            min-width: 18px;
            max-width: 18px;
            min-height: 18px;
            max-height: 18px;
            padding: 0;
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
        }}

        QPushButton#InfoPopoverButton:hover,
        QPushButton#InfoPopoverButton[pointerState="hover"] {{
            color: {text};
            background: {hover};
            border-color: {button_border};
        }}

        QPushButton#InfoPopoverButton:pressed,
        QPushButton#InfoPopoverButton[pointerState="pressed"] {{
            color: {text};
            background: {pressed};
            border-color: {accent};
        }}

        QToolTip {{
            color: {text};
            background: {raised};
            border: 1px solid {button_border};
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 10px;
        }}

        QLabel#TrainingStartHint {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QSpinBox#TrainingSpinBox {{
            min-height: 34px;
            max-height: 34px;
        }}

        QSpinBox#TrainingSpinBox:disabled {{
            color: {faint};
            background: {surface};
            border-color: {border};
        }}

        QLabel#TrainingDeviceValue {{
            min-height: 34px;
            max-height: 34px;
            padding: 0 11px;
            color: {text};
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 11px;
            font-weight: 800;
        }}

        QScrollArea#ModelTrainingScroll,
        QScrollArea#ModelTrainingScroll > QWidget > QWidget {{
            background: transparent;
            border: 0;
        }}

        QLabel#TrainingDeviceValue:disabled {{
            color: {faint};
        }}

        QPushButton#TrainingStopButton {{
            min-width: 90px;
            min-height: 34px;
            max-height: 34px;
        }}

        QProgressBar#TrainingProgress, QProgressBar#TrainingStageProgress {{
            min-height: 8px;
            max-height: 8px;
            border: 0;
            border-radius: 4px;
            background: {surface};
            color: transparent;
        }}

        QProgressBar#TrainingProgress::chunk, QProgressBar#TrainingStageProgress::chunk {{
            background: {accent};
            border-radius: 4px;
        }}

        QWidget#SongListRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 16px;
        }}

        QWidget#SongListRow:hover {{
            background: {hover};
        }}

        QWidget#SongListRow[workSong="true"] {{
            background: {warning_background};
            border: 1px solid {warning_border};
        }}

        QWidget#SongListRow[workSong="true"]:hover {{
            background: {warning_background};
            border-color: {warning_text};
        }}

        QWidget#SongListRow[workSongPulse="true"] {{
            background: {warning_background};
            border: 2px solid {warning_text};
        }}

        QFrame#LibraryPreviewDivider {{
            background: {border};
            border: 0;
        }}

        QWidget#LibraryPreviewTransport {{
            background: transparent;
            border: 0;
        }}

        QWidget#ModelListRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QWidget#ModelListRow:hover {{
            background: {hover};
        }}

        QWidget#ModelListRow[selected="true"] {{
            background: {selection};
            border: 1px solid {tab_active_border};
        }}

        QWidget#ShareProgressAction,
        QWidget#ModelRowActionSlot {{
            background: transparent;
            border: 0;
        }}

        QLabel#RowShareProgressLabel {{
            color: {muted};
            font-size: 10px;
            font-weight: 800;
        }}

        QLabel#ShareCopiedLabel {{
            color: {success_text};
            background: {success_background};
            border: 1px solid {success_border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
        }}

        QPushButton#WorkShareButton,
        QPushButton#WorkSharedButton {{
            min-height: 32px;
            max-height: 32px;
            padding: 0 12px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 900;
        }}

        QPushButton#WorkSharedButton {{
            color: {success_text};
            background: {success_background};
            border-color: {success_border};
        }}

        QProgressBar#RowShareProgress {{
            min-height: 4px;
            max-height: 4px;
            background: {border};
            border: 0;
            border-radius: 2px;
        }}

        QProgressBar#RowShareProgress::chunk {{
            background: {accent};
            border-radius: 2px;
        }}

        QLabel#ModelRowTitle, QLabel#ModelDetailTitle {{
            color: {text};
            font-size: 15px;
            font-weight: 900;
        }}

        QLabel#ModelRowMeta, QLabel#ModelDetailLabel, QLabel#ModelSummaryLabel {{
            color: {muted};
            font-size: 11px;
            font-weight: 700;
        }}

        QLabel#ModelStatusBadge, QLabel#ModelModeBadge {{
            color: {text};
            background: {background};
            border: 1px solid {border};
            border-radius: 9px;
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#ModelStatusBadge[status="resume"], QLabel#ModelModeBadge[managed="true"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#ModelStatusBadge[status="missing"],
        QLabel#ModelStatusBadge[status="checkpoint"],
        QLabel#ModelStatusBadge[status="runtime"] {{
            color: #c93d3d;
            border-color: #c93d3d;
        }}

        QLabel#ModelDetailValue {{
            color: {text};
            font-size: 12px;
            font-weight: 700;
        }}

        QLabel#ModelSourcePath {{
            color: {muted};
            background: {raised};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 10px;
            font-size: 11px;
        }}

        QLabel#ArtifactName {{
            color: {text};
            font-size: 11px;
            font-weight: 800;
        }}

        QLabel#ArtifactValue {{
            color: {muted};
            font-size: 10px;
        }}

        QLabel#ArtifactState {{
            color: {muted};
            background: {background};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 2px 6px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#ArtifactState[state="ready"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#ArtifactState[state="missing"], QLabel#ArtifactState[state="mismatch"] {{
            color: #c93d3d;
            border-color: #c93d3d;
        }}

        QWidget#SongActionSlot {{
            background: transparent;
            border: 0;
        }}

        QWidget#WorkSongRevealSlot {{
            background: transparent;
            border: 0;
        }}

        QPushButton#WorkSongRevealButton {{
            min-width: 34px;
            max-width: 34px;
            min-height: 34px;
            max-height: 34px;
            padding: 0;
            color: {warning_text};
            background: {warning_background};
            border: 1px solid {warning_border};
            border-radius: 10px;
        }}

        QPushButton#WorkSongRevealButton:hover,
        QPushButton#WorkSongRevealButton[pointerState="hover"] {{
            color: {text};
            background: {hover};
            border-color: {warning_text};
        }}

        QPushButton#WorkSongRevealButton:pressed,
        QPushButton#WorkSongRevealButton[pointerState="pressed"] {{
            color: {text};
            background: {pressed};
            border-color: {warning_text};
        }}

        QPushButton#WorkSongRevealButton:checked {{
            color: {warning_text};
            background: {warning_background};
            border: 2px solid {warning_text};
        }}

        QPushButton#WorkSongRevealButton:checked:hover,
        QPushButton#WorkSongRevealButton:checked[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#WorkSongRevealButton:checked:pressed,
        QPushButton#WorkSongRevealButton:checked[pointerState="pressed"] {{
            color: {text};
            background: {pressed};
        }}

        #LibraryRowTitle {{
            color: {text};
            font-size: 14px;
            font-weight: 900;
        }}

        QLabel#LibraryRowMeta {{
            color: {muted};
            font-size: 12px;
            font-weight: 700;
        }}

        QLabel#LibraryDetailTitle {{
            color: {text};
            font-size: 18px;
            font-weight: 900;
        }}

        QLabel#LibraryDetailMeta, QLabel#LibraryStageSummary {{
            color: {muted};
            font-size: 11px;
            font-weight: 700;
        }}

        QScrollArea#LibraryAssetScroll {{
            background: {surface};
            border: 0;
        }}

        QScrollArea#LibraryAssetScroll > QWidget > QWidget,
        QWidget#LibraryAssetViewport,
        QWidget#LibraryAssetContent {{
            background: {surface};
        }}

        QFrame#LibraryAssetRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#LibraryAssetRow:hover {{
            background: {hover};
        }}

        QFrame#LibraryAssetRow[previewExpanded="true"] {{
            background: {selection};
            border: 1px solid {tab_active_border};
        }}

        QWidget#LibraryAssetPreviewTransport {{
            background: transparent;
            border: 0;
        }}

        QLabel#LibraryAssetSelectedCount {{
            color: {muted};
            font-size: 10px;
            font-weight: 800;
        }}

        QCheckBox#LibraryAssetCheckBox {{
            background: transparent;
            border: 0;
            spacing: 0;
        }}

        QCheckBox#LibraryAssetCheckBox::indicator {{
            width: 16px;
            height: 16px;
            background: {surface};
            border: 1px solid {button_border};
            border-radius: 4px;
        }}

        QCheckBox#LibraryAssetCheckBox::indicator:hover {{
            background: {hover};
            border-color: {focus};
        }}

        QCheckBox#LibraryAssetCheckBox::indicator:checked {{
            background: {accent};
            border-color: {accent};
            image: url("{check_icon}");
        }}

        QCheckBox#LibraryAssetCheckBox::indicator:disabled {{
            background: {card};
            border-color: {border};
        }}

        QLabel#LibraryAssetRole {{
            color: {text};
            font-size: 11px;
            font-weight: 900;
        }}

        QLabel#LibraryAssetName {{
            color: {text};
            font-size: 12px;
            font-weight: 800;
        }}

        QLabel#LibraryAssetMeta {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#LibraryAssetBadge {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            min-height: 22px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#LibraryAssetBadge[active="true"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#LibraryEmptyState {{
            color: {muted};
            background: {raised};
            border: 1px dashed {border};
            border-radius: 14px;
            padding: 28px;
            font-size: 12px;
            font-weight: 700;
        }}

        QScrollArea#ExportScroll,
        QScrollArea#ExportScroll > QWidget > QWidget {{
            background: {surface};
            border: 0;
        }}

        QFrame#AudioExportControls,
        QFrame#VideoExportControls {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QLabel#ExportSettingsTitle {{
            color: {text};
            font-size: 13px;
            font-weight: 900;
        }}

        QFrame#ExportPresetBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QPushButton#ExportPresetButton {{
            min-height: 38px;
            padding: 0 6px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            font-size: 9px;
            font-weight: 800;
        }}

        QPushButton#ExportPresetButton:hover {{
            color: {text};
            background: {hover};
        }}

        QPushButton#ExportPresetButton:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QPushButton#ExportPresetButton:disabled {{
            color: {faint};
            background: transparent;
        }}

        QLabel#CollapsibleHeaderSummary {{
            color: {faint};
            font-size: 9px;
            font-weight: 700;
        }}

        QPushButton#RvcInferencePresetButton {{
            min-width: 0;
            min-height: 30px;
            padding: 0 5px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            font-size: 9px;
            font-weight: 800;
        }}

        QPushButton#RvcInferencePresetButton:hover {{
            color: {text};
            background: {hover};
        }}

        QPushButton#RvcInferencePresetButton:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QFrame#RvcAdvancedSettingsPanel {{
            background: transparent;
            border: 0;
        }}

        QLabel#RvcInferenceSliderValue {{
            color: {text};
            font-size: 10px;
            font-weight: 800;
        }}

        QSlider#RvcInferenceSlider {{
            min-height: 24px;
        }}

        QLabel#RvcInferenceCustomBadge {{
            padding: 2px 7px;
            color: {tab_active_text};
            background: {tab_active};
            border: 1px solid {tab_active_border};
            border-radius: 7px;
            font-size: 9px;
            font-weight: 800;
        }}

        QFrame#RvcInferenceDetailsPanel {{
            background: transparent;
            border: 0;
        }}

        QLabel#AudioExportSummary {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#ExportFieldLabel {{
            color: {muted};
            font-size: 10px;
            font-weight: 800;
        }}

        QComboBox#ExportSettingCombo {{
            min-height: 30px;
        }}

        QCheckBox#ExportDitherCheck {{
            color: {text};
            min-height: 30px;
            padding-left: 2px;
            font-size: 10px;
            font-weight: 700;
        }}

        QProgressBar#ExportInlineProgress {{
            height: 6px;
            background: {surface};
            border: 0;
            border-radius: 3px;
        }}

        QProgressBar#ExportInlineProgress::chunk {{
            background: {accent};
            border-radius: 3px;
        }}

        QLabel#AudioExportStatus {{
            color: {muted};
            background: transparent;
            border: 0;
            font-size: 10px;
            font-weight: 700;
        }}

        QFrame#ExportRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#ExportRow:hover {{
            background: {hover};
        }}

        QWidget#ExportName {{
            color: {text};
            font-size: 12px;
            font-weight: 800;
        }}

        QLabel#ExportMeta {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#ExportEmptyState {{
            color: {muted};
            background: {raised};
            border: 1px dashed {border};
            border-radius: 14px;
            padding: 28px;
            font-size: 12px;
            font-weight: 700;
        }}

        QLabel#SourceBadge {{
            color: {source_local_text};
            background: {source_local_background};
            border: 1px solid {source_local_border};
            border-radius: 10px;
            font-size: 10px;
            font-weight: 900;
            min-height: 24px;
        }}

        QLabel#SourceBadge[sourceType="youtube"] {{
            color: {source_youtube_text};
            background: {source_youtube_background};
            border-color: {source_youtube_border};
        }}

        QLabel#SourceBadge[sourceType="output"] {{
            color: {source_output_text};
            background: {source_output_background};
            border-color: {source_output_border};
        }}

        QFrame#MiniWaveform {{
            background: transparent;
            border: 0;
        }}

        QFrame#InsetCard {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QFrame#ConversionVocalPool {{
            background: {card};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QScrollArea#SoundPoolListScroll,
        QScrollArea#SoundPoolListScroll > QWidget > QWidget,
        QWidget#SoundPoolListContent {{
            background: transparent;
            border: 0;
        }}

        QFrame#ConversionVocalCard {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 13px;
        }}

        QFrame#ConversionVocalCard:hover {{
            background: {hover};
            border-color: {button_border};
        }}

        QFrame#ConversionVocalCard[selected="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QLabel#VocalTakeMetadata {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QFrame#ModelSummaryCard, QFrame#ModelListSurface, QFrame#ModelDetailSurface {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QFrame#ModelMaintenanceCard {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#DatasetColumn, QFrame#DatasetFooter {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QFrame#DatasetTransferRail {{
            background: transparent;
            border: 0;
        }}

        QFrame#DatasetClipEditor {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 14px;
        }}

        QLabel#DatasetEditorTitle {{
            color: {text};
            font-size: 13px;
            font-weight: 900;
        }}

        QLabel#DatasetEditorMeta, QLabel#DatasetEditorTime {{
            color: {muted};
            font-size: 10px;
            font-weight: 800;
        }}

        QLabel#DatasetEditorSelection {{
            color: {text};
            font-size: 11px;
            font-weight: 800;
        }}

        QWidget#ClipEditorHeader {{
            background: transparent;
            border: 0;
        }}

        QFrame#DatasetHeaderNavigation,
        QFrame#DatasetPlaybackGroup {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QLabel#DatasetNavigationPosition {{
            min-width: 46px;
            color: {muted};
            font-size: 10px;
            font-weight: 850;
        }}

        QFrame#DatasetTimingGroup {{
            min-height: 30px;
            max-height: 30px;
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
        }}

        QFrame#DatasetEditorDivider {{
            background: {border};
            border: 0;
        }}

        QLabel#DatasetReviewBadge {{
            min-width: 76px;
            min-height: 22px;
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#DatasetReviewBadge[state="ready"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#DatasetReviewBadge[state="editing"] {{
            color: {text};
            border-color: {text};
        }}

        QFrame#DatasetAnalysisBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QFrame#DatasetCommandBar,
        QFrame#DatasetAudioInspector {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QWidget#DatasetInspectorHeader {{
            background: transparent;
            border: 0;
            border-radius: 0;
        }}

        QLabel#DatasetShortcutKey {{
            min-width: 34px;
            max-width: 34px;
            min-height: 22px;
            max-height: 22px;
            color: {muted};
            background: {raised};
            border: 1px solid {border};
            border-radius: 6px;
            font-size: 8px;
            font-weight: 900;
        }}

        QFrame#DatasetToolPanel,
        QStackedWidget#DatasetInspectorStack {{
            background: transparent;
            border: 0;
        }}

        QFrame#DatasetToolSection {{
            background: transparent;
            border: 0;
        }}

        QLabel#DatasetToolSectionLabel {{
            color: {muted};
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#DatasetToolHint {{
            color: {faint};
            font-size: 9px;
            font-weight: 700;
        }}

        QLabel#DatasetToolValue {{
            color: {text};
            font-size: 10px;
            font-weight: 850;
        }}

        QFrame#DatasetToolDivider {{
            background: {border};
            border: 0;
        }}

        QProgressBar#DatasetToolProgress {{
            min-height: 4px;
            max-height: 4px;
            border: 0;
            border-radius: 2px;
            background: {border};
        }}

        QProgressBar#DatasetToolProgress::chunk {{
            border-radius: 2px;
            background: {accent};
        }}

        QFrame#DatasetInspectorContent {{
            background: {raised};
            border: 0;
            border-top: 1px solid {border};
        }}

        QLabel#DatasetInspectorTitle {{
            color: {muted};
            font-size: 9px;
            font-weight: 900;
        }}

        QFrame#DatasetInspectorTabs {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
        }}

        QPushButton#DatasetInspectorTab {{
            min-width: 88px;
            min-height: 24px;
            max-height: 24px;
            padding: 0 10px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QPushButton#DatasetInspectorTab:hover,
        QPushButton#DatasetInspectorTab[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#DatasetInspectorTab:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QScrollArea#DatasetAnalysisScroll,
        QScrollArea#DatasetAnalysisScroll > QWidget > QWidget,
        QWidget#DatasetAnalysisContent {{
            background: transparent;
            border: 0;
        }}

        QFrame#DatasetAnalysisMetric,
        QFrame#DatasetAnalysisSection {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QLabel#DatasetAnalysisMetricLabel,
        QLabel#DatasetAnalysisMeta,
        QLabel#DatasetAnalysisStatus {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#DatasetAnalysisMetricValue {{
            color: {text};
            font-size: 18px;
            font-weight: 900;
        }}

        QLabel#DatasetAnalysisSectionTitle {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
        }}

        QProgressBar#DatasetAnalysisProgress {{
            min-height: 5px;
            max-height: 5px;
            border: 0;
            border-radius: 2px;
            background: {border};
            text-align: center;
            color: transparent;
        }}

        QProgressBar#DatasetAnalysisProgress::chunk {{
            border-radius: 2px;
            background: {accent};
        }}

        QWidget#PitchHistogram {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QFrame#DatasetQualityRow {{
            background: transparent;
            border: 0;
            border-bottom: 1px solid {border};
        }}

        QLabel#DatasetQualityValue {{
            color: {text};
            font-size: 11px;
            font-weight: 900;
        }}

        QListWidget#DatasetIssueList {{
            min-height: 210px;
            background: transparent;
            border: 0;
            outline: 0;
        }}

        QListWidget#DatasetIssueList::item {{
            background: transparent;
            border: 0;
            padding: 0;
        }}

        QListWidget#DatasetIssueList::item:selected {{
            background: transparent;
        }}

        QWidget#DatasetIssueRow {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QWidget#DatasetIssueRow:hover {{
            background: {hover};
            border-color: {button_border};
        }}

        QLabel#DatasetIssueTitle {{
            color: {text};
            font-size: 11px;
            font-weight: 800;
        }}

        QLabel#DatasetIssueBadge {{
            min-width: 64px;
            min-height: 22px;
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#DatasetIssueBadge[severity="attention"] {{
            color: {warning_text};
            background: {warning_background};
            border-color: {warning_border};
        }}

        QLabel#DatasetAnalysisLabel {{
            color: {text};
            font-size: 9px;
            font-weight: 900;
        }}

        QSpinBox#DatasetAnalysisSpin {{
            min-height: 28px;
            max-height: 28px;
            padding-left: 8px;
            border-radius: 8px;
            font-size: 10px;
            font-weight: 800;
        }}

        QPushButton#DatasetAnalyzeButton {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 14px;
            border-radius: 8px;
            color: {accent_text};
            background: {accent};
            border-color: {accent};
            font-size: 10px;
            font-weight: 900;
        }}

        QPushButton#DatasetAnalyzeButton:hover,
        QPushButton#DatasetAnalyzeButton[pointerState="hover"] {{
            background: {active_hover};
        }}

        QPushButton#DatasetAnalyzeButton:pressed,
        QPushButton#DatasetAnalyzeButton[pointerState="pressed"] {{
            background: {active_pressed};
        }}

        QPushButton#DatasetAnalyzeButton[keyboardFocus="true"] {{
            background: {active_hover};
            border-color: {focus};
        }}

        QPushButton#DatasetAnalyzeButton:disabled {{
            color: {faint};
            background: {raised};
            border-color: {border};
        }}

        QFrame#DatasetResultTabs {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
        }}

        QPushButton#DatasetResultTab {{
            min-width: 90px;
            min-height: 24px;
            max-height: 24px;
            padding: 0 10px;
            color: {muted};
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QPushButton#DatasetResultTab:hover,
        QPushButton#DatasetResultTab[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#DatasetResultTab:pressed,
        QPushButton#DatasetResultTab[pointerState="pressed"] {{
            color: {text};
            background: {pressed};
        }}

        QPushButton#DatasetResultTab:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QPushButton#DatasetResultTab:checked:hover,
        QPushButton#DatasetResultTab[pointerState="hover"]:checked {{
            color: {tab_active_text};
            background: {tab_active_hover};
        }}

        QPushButton#DatasetResultTab:checked:pressed,
        QPushButton#DatasetResultTab[pointerState="pressed"]:checked {{
            color: {tab_active_text};
            background: {tab_active_pressed};
        }}

        QPushButton#DatasetResultTab[keyboardFocus="true"] {{
            border-color: {focus};
        }}

        QPushButton#DatasetResultTab:disabled {{
            color: {faint};
            background: transparent;
            border-color: transparent;
        }}

        QLabel#DatasetColumnTitle {{
            color: {text};
            font-size: 13px;
            font-weight: 900;
        }}

        QLabel#DatasetCountBadge {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
            min-width: 24px;
            max-width: 24px;
            min-height: 20px;
            max-height: 20px;
            font-size: 10px;
            font-weight: 900;
        }}

        QListWidget#DatasetList {{
            color: {text};
            background: {surface};
            border: 1px solid {border};
            border-radius: 12px;
            padding: 4px;
        }}

        QListWidget#DatasetList[dragging="true"] {{
            background: {selection};
            border-color: {text};
        }}

        QListWidget#DatasetList::item,
        QListWidget#DatasetList::item:hover,
        QListWidget#DatasetList::item:selected {{
            background: transparent;
            margin: 2px 0;
        }}

        QListWidget#DatasetClipList, QListWidget#DatasetSuggestionList {{
            color: {text};
            background: {surface};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 4px;
        }}

        QListWidget#DatasetClipList::item, QListWidget#DatasetSuggestionList::item {{
            color: {muted};
            background: {background};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 5px 9px;
            margin: 2px 4px 2px 0;
        }}

        QListWidget#DatasetClipList::item:hover, QListWidget#DatasetSuggestionList::item:hover {{
            color: {text};
            background: {hover};
        }}

        QListWidget#DatasetClipList::item:selected {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QListWidget#DatasetSuggestionList::item:selected {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QListWidget#DatasetSuggestionList::indicator {{
            width: 12px;
            height: 12px;
            border: 1px solid {border};
            border-radius: 4px;
            background: {surface};
        }}

        QListWidget#DatasetSuggestionList::indicator:checked {{
            background: {accent};
            border: 3px solid {surface};
        }}

        QStackedWidget#DatasetResultStack, QStackedWidget#DatasetActionStack {{
            background: transparent;
            border: 0;
        }}

        QWidget#DatasetActionPage {{
            background: transparent;
            border: 0;
        }}

        QWidget#DatasetAudioRow {{
            background: {background};
            border: 1px solid {border};
            border-radius: 11px;
        }}

        QWidget#DatasetAudioRow:hover {{
            background: {hover};
        }}

        QWidget#DatasetAudioRow[selected="true"] {{
            background: {selection};
            border-color: {tab_active_border};
        }}

        QLabel#DatasetItemTitle {{
            color: {text};
            font-size: 11px;
            font-weight: 900;
        }}

        QLabel#DatasetItemMeta, QLabel#DatasetSummary, QLabel#DatasetStatus {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#DatasetItemBadge {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            min-width: 54px;
            min-height: 22px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#DatasetItemBadge[kind="ready"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#DatasetItemBadge[kind="editing"] {{
            color: {text};
            border-color: {text};
        }}

        QFrame#ArtifactRepairRow {{
            background: transparent;
            border: 0;
            border-bottom: 1px solid {border};
            border-radius: 0;
        }}

        QScrollArea#ModelDetailScroll, QWidget#ModelDetailContent {{
            background: transparent;
            border: 0;
        }}

        QFrame#ModelDetailsGrid {{
            background: transparent;
            border: 0;
        }}

        QLabel#ModelSummaryValue {{
            color: {text};
            font-size: 22px;
            font-weight: 900;
        }}

        QFrame#ProcessingQueuePanel {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 15px;
        }}

        QFrame#ProcessingQueueHeader, QWidget#ProcessingQueueBody,
        QWidget#ProcessingQueueTaskContainer {{
            background: transparent;
            border: 0;
        }}

        QLabel#ProcessingQueueTitle {{
            color: {text};
            font-size: 13px;
            font-weight: 900;
        }}

        QLabel#ProcessingQueueActivity {{
            color: {muted};
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 900;
        }}

        QLabel#ProcessingQueueActivity[active="true"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QPushButton#ProcessingQueueToggle {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QScrollArea#ProcessingQueueScroll {{
            background: transparent;
            border: 0;
        }}

        QFrame#ProcessingTaskRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 11px;
        }}

        QFrame#ProcessingTaskRow[status="failed"] {{
            border-color: #c93d3d;
        }}

        QFrame#ProcessingTaskRow[status="cancelled"] {{
            border-color: {muted};
        }}

        #ProcessingTaskTitle {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
        }}

        #ProcessingTaskDetail, QLabel#ProcessingQueueEmpty {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#ProcessingTaskStatus {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 2px 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#ProcessingTaskStatus[status="completed"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#ProcessingTaskStatus[status="failed"] {{
            color: #c93d3d;
            border-color: #c93d3d;
        }}

        QLabel#ProcessingTaskStatus[status="cancelled"] {{
            color: {muted};
            border-color: {muted};
        }}

        QProgressBar#ProcessingTaskProgress {{
            min-height: 5px;
            max-height: 5px;
            border: 0;
            border-radius: 2px;
            background: {surface};
        }}

        QProgressBar#ProcessingTaskProgress::chunk {{
            background: {accent};
            border-radius: 2px;
        }}

        QPushButton#ProcessingQueueClear {{
            min-height: 24px;
            max-height: 24px;
            padding: 0 8px;
            border: 1px solid transparent;
            background: transparent;
            color: {muted};
            font-size: 10px;
        }}

        QPushButton#ProcessingQueueClear:hover,
        QPushButton#ProcessingQueueClear[pointerState="hover"] {{
            color: {text};
            background: {hover};
        }}

        QPushButton#ProcessingQueueClear:pressed,
        QPushButton#ProcessingQueueClear[pointerState="pressed"] {{
            color: {text};
            background: {pressed};
        }}

        QPushButton#ProcessingQueueClear[keyboardFocus="true"] {{
            color: {text};
            border-color: {focus};
        }}

        QPushButton#ProcessingQueueClear:disabled {{
            color: {faint};
            background: transparent;
            border-color: transparent;
        }}

        QWidget#ToastStack {{
            background: transparent;
            border: 0;
        }}

        QFrame#ToastCard {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 13px;
        }}

        QFrame#ToastCard[status="failed"] {{
            border-color: #c93d3d;
        }}

        QLabel#ToastTitle {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
        }}

        QLabel#ToastMessage {{
            color: {muted};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#ToastStatus {{
            color: {tab_active_text};
            background: {tab_active};
            border: 1px solid {tab_active_border};
            border-radius: 8px;
            padding: 2px 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#ToastStatus[status="failed"] {{
            color: #c93d3d;
            background: transparent;
            border-color: #c93d3d;
        }}

        QPushButton#ToastCloseButton {{
            min-width: 24px;
            max-width: 24px;
            min-height: 24px;
            max-height: 24px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QFrame#LogDrawer {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 16px;
        }}

        QWidget#LogDrawerPage {{
            background: transparent;
            border: 0;
        }}

        QLabel#LogDrawerTitle {{
            color: {text};
            font-size: 17px;
            font-weight: 900;
        }}

        QPushButton#LogDrawerIconButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#LogDrawerTaskFolderButton {{
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
            padding: 0;
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
        }}

        QPushButton#LogDrawerTaskFolderButton:hover {{
            background: {hover};
        }}

        QPushButton#LogDrawerActionButton {{
            min-height: 32px;
            max-height: 32px;
            padding: 0 14px;
            color: {text};
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 800;
        }}

        QPushButton#LogDrawerActionButton:hover {{
            background: {hover};
        }}

        QPushButton#LogDrawerActionButton:pressed {{
            background: {pressed};
        }}

        QPushButton#LogDrawerActionButton:disabled,
        QPushButton#LogDrawerTaskFolderButton:disabled {{
            color: {faint};
            background: transparent;
            border-color: {border};
        }}

        QLabel#LogDrawerDiagnosticStatus {{
            color: {muted};
            font-size: 9px;
            font-weight: 700;
        }}

        QListWidget#LogActivityList {{
            background: transparent;
            border: 0;
            outline: 0;
        }}

        QListWidget#LogActivityList::item,
        QListWidget#LogActivityList::item:hover,
        QListWidget#LogActivityList::item:selected {{
            background: transparent;
            margin: 3px 0;
        }}

        QWidget#ActivityTaskRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QWidget#ActivityTaskRow:hover {{
            background: {hover};
        }}

        QWidget#ActivityTaskRow[selected="true"] {{
            background: {selection};
            border-color: {tab_active_border};
        }}

        QLabel#ActivityTaskTitle {{
            color: {text};
            font-size: 11px;
            font-weight: 900;
        }}

        QLabel#ActivityTaskMeta, QLabel#LogPathLabel {{
            color: {muted};
            font-size: 9px;
            font-weight: 700;
        }}

        QLabel#ActivityTaskStatus {{
            color: {muted};
            background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 2px 7px;
            font-size: 9px;
            font-weight: 900;
        }}

        QLabel#ActivityTaskStatus[status="completed"] {{
            color: {tab_active_text};
            background: {tab_active};
            border-color: {tab_active_border};
        }}

        QLabel#ActivityTaskStatus[status="failed"] {{
            color: #c93d3d;
            border-color: #c93d3d;
        }}

        QPlainTextEdit#LogDetailText, QPlainTextEdit#ApplicationLogText {{
            background: {raised};
            color: {text};
            border: 1px solid {border};
            border-radius: 11px;
            padding: 10px;
            selection-background-color: {selection};
            font-family: "Cascadia Mono", "Consolas";
            font-size: 10px;
        }}

        QLabel#TransportTime {{
            color: {muted};
            font-size: 12px;
            font-weight: 800;
        }}

        QFrame#TrackActionGroup {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QFrame#TrackActionDivider {{
            background: {border};
            border: 0;
        }}

        QFrame#TrackMixerStrip {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 10px;
        }}

        QLabel#TrackMixerLabel {{
            color: {muted};
            font-size: 9px;
            font-weight: 900;
            letter-spacing: 1px;
        }}

        QLabel#VolumeValue {{
            color: {text};
            font-size: 11px;
            font-weight: 900;
        }}

        QComboBox#TrackVersionCombo {{
            min-height: 30px;
            max-height: 30px;
            padding-left: 10px;
            background: {raised};
            border-radius: 9px;
            font-size: 11px;
        }}

        QLabel#ProgressValue {{
            color: {text};
            font-size: 12px;
            font-weight: 800;
            min-width: 34px;
        }}

        QFrame#DropZone {{
            background: {raised};
            border: 1px dashed {faint};
            border-radius: 18px;
        }}

        QFrame#DropZone[dragging="true"] {{
            background: {selection};
            border: 1px solid {text};
        }}

        QLabel#DropTitle {{
            color: {text};
            font-size: 15px;
            font-weight: 900;
        }}

        QLabel#DropFileName {{
            color: {muted};
            font-size: 12px;
            font-weight: 700;
        }}

        QPushButton {{
            min-height: 34px;
            padding: 0 18px;
            border: 1px solid {button_border};
            border-radius: 10px;
            background: transparent;
            color: {text};
            font-weight: 700;
            outline: 0;
        }}

        QPushButton:hover,
        QPushButton[pointerState="hover"] {{
            background: {hover};
        }}

        QPushButton:pressed,
        QPushButton[pointerState="pressed"] {{
            background: {pressed};
        }}

        QPushButton[keyboardFocus="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QPushButton:disabled {{
            color: {faint};
            border-color: {border};
            background: {raised};
        }}

        QPushButton#PrimaryButton, QPushButton#DatasetEditorPrimaryButton {{
            background: {accent};
            color: {accent_text};
            border-color: {accent};
        }}

        QPushButton#PrimaryButton:hover,
        QPushButton#PrimaryButton[pointerState="hover"],
        QPushButton#DatasetEditorPrimaryButton:hover,
        QPushButton#DatasetEditorPrimaryButton[pointerState="hover"] {{
            background: {active_hover};
        }}

        QPushButton#PrimaryButton:pressed,
        QPushButton#PrimaryButton[pointerState="pressed"],
        QPushButton#DatasetEditorPrimaryButton:pressed,
        QPushButton#DatasetEditorPrimaryButton[pointerState="pressed"] {{
            background: {active_pressed};
        }}

        QPushButton#PrimaryButton[keyboardFocus="true"],
        QPushButton#DatasetEditorPrimaryButton[keyboardFocus="true"] {{
            background: {active_hover};
            border-color: {focus};
        }}

        QPushButton#DangerButton {{
            color: #fff7f5;
            background: #b43a32;
            border-color: #b43a32;
        }}

        QPushButton#DangerButton:hover,
        QPushButton#DangerButton[pointerState="hover"] {{
            background: #c84940;
            border-color: #c84940;
        }}

        QPushButton#DangerButton:pressed,
        QPushButton#DangerButton[pointerState="pressed"] {{
            background: #963029;
            border-color: #963029;
        }}

        QPushButton#PrimaryButton:disabled,
        QPushButton#DatasetEditorPrimaryButton:disabled {{
            color: {faint};
            background: {raised};
            border-color: {border};
        }}

        QPushButton#ModelIconButton {{
            min-width: 30px;
            min-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#ModelAddButton {{
            min-height: 32px;
            padding: 0 14px;
            border-radius: 9px;
            font-weight: 800;
        }}

        QPushButton#ModelAddChoice, QPushButton#ModelAddOption {{
            text-align: left;
            padding: 12px 16px;
            border-radius: 12px;
            font-weight: 800;
        }}

        QPushButton#ModelAddChoice:hover,
        QPushButton#ModelAddChoice[pointerState="hover"],
        QPushButton#ModelAddOption:hover,
        QPushButton#ModelAddOption[pointerState="hover"] {{
            background: {hover};
            border-color: {focus};
        }}

        QPushButton#ModelAddOption:checked {{
            color: {accent_text};
            background: {accent};
            border-color: {accent};
        }}

        QFrame#DriveAccountCard, QFrame#DriveFileCard, QFrame#DriveResultCard {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QLabel#DriveAccountBadge {{
            color: {tab_active_text};
            background: {tab_active};
            border: 1px solid {tab_active_border};
            border-radius: 10px;
            font-size: 14px;
            font-weight: 900;
        }}

        QLineEdit#ModelAddDriveLink {{
            min-height: 34px;
            padding: 0 11px;
            color: {text};
            background: {background};
            border: 1px solid {border};
            border-radius: 9px;
            selection-background-color: {selection};
        }}

        QPushButton#ModelWorkspaceBackButton {{
            min-width: 34px;
            max-width: 34px;
            min-height: 34px;
            max-height: 34px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#ModelArtifactButton {{
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DatasetIconButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DatasetTransferButton {{
            min-width: 38px;
            max-width: 38px;
            min-height: 38px;
            max-height: 38px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DatasetEditorIconButton {{
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DatasetEditorIconButton:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-radius: 8px;
        }}

        QPushButton#DatasetFlatIconButton {{
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DatasetEditorSecondaryButton,
        QPushButton#DatasetEditorPrimaryButton,
        QPushButton#DatasetReadyButton {{
            font-family: "Malgun Gothic", "Segoe UI", "Arial";
            font-size: 11px;
            font-weight: 800;
        }}

        QPushButton#DatasetEditorSecondaryButton {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 12px;
            border-radius: 9px;
            background: {surface};
        }}

        QPushButton#DatasetEditorPrimaryButton {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 12px;
            border-radius: 9px;
        }}

        QPushButton#DatasetEditorPrimaryButton[active="true"],
        QPushButton#DatasetEditorPrimaryButton[active="true"]:disabled {{
            color: {accent_text};
            background: {accent};
            border-color: {accent};
        }}

        QPushButton#DatasetEditorSecondaryButton:hover,
        QPushButton#DatasetEditorSecondaryButton[pointerState="hover"] {{
            background: {hover};
        }}

        QPushButton#DatasetEditorSecondaryButton:pressed,
        QPushButton#DatasetEditorSecondaryButton[pointerState="pressed"] {{
            background: {pressed};
        }}

        QPushButton#DatasetEditorSecondaryButton[keyboardFocus="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QPushButton#DatasetEditorSecondaryButton:disabled {{
            color: {faint};
            background: {raised};
            border-color: {border};
        }}

        QPushButton#DatasetReadyButton {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 12px;
            color: {accent_text};
            background: {accent};
            border-color: {accent};
            border-radius: 9px;
        }}

        QPushButton#DatasetReadyButton:hover,
        QPushButton#DatasetReadyButton[pointerState="hover"] {{
            background: {active_hover};
            border-color: {active_hover};
        }}

        QPushButton#DatasetReadyButton:pressed,
        QPushButton#DatasetReadyButton[pointerState="pressed"] {{
            background: {active_pressed};
            border-color: {active_pressed};
        }}

        QPushButton#DatasetReadyButton[keyboardFocus="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QPushButton#DatasetReadyButton:disabled {{
            color: {muted};
            background: {surface};
            border-color: {border};
        }}

        QFrame#SegmentedControl {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 20px;
        }}

        QPushButton#SegmentButton {{
            min-height: 36px;
            padding: 0 10px;
            border: 1px solid transparent;
            border-radius: 16px;
            background: transparent;
            color: {muted};
        }}

        QPushButton#SegmentButton:hover,
        QPushButton#SegmentButton[pointerState="hover"] {{
            background: {selection};
            color: {text};
        }}

        QPushButton#SegmentButton:pressed,
        QPushButton#SegmentButton[pointerState="pressed"] {{
            background: {pressed};
            color: {text};
        }}

        QPushButton#SegmentButton:checked {{
            background: {tab_active};
            color: {tab_active_text};
            border-color: {tab_active_border};
        }}

        QPushButton#SegmentButton:checked:hover,
        QPushButton#SegmentButton[pointerState="hover"]:checked {{
            background: {tab_active_hover};
            color: {tab_active_text};
        }}

        QPushButton#SegmentButton:checked:pressed,
        QPushButton#SegmentButton[pointerState="pressed"]:checked {{
            background: {tab_active_pressed};
            color: {tab_active_text};
        }}

        QPushButton#SegmentButton[keyboardFocus="true"] {{
            border-color: {focus};
        }}

        QPushButton#SegmentButton:disabled {{
            color: {faint};
            background: transparent;
            border-color: transparent;
        }}

        QLabel#SeparationRecipeField {{
            color: {muted};
            font-size: 11px;
            font-weight: 650;
        }}

        QLabel#SeparationRecipeValue {{
            color: {text};
            font-size: 11px;
            font-weight: 850;
        }}

        QLabel#SeparationAssetStatus {{
            padding: 3px 8px;
            border: 1px solid {border};
            border-radius: 8px;
            color: {muted};
            background: {raised};
            font-size: 10px;
            font-weight: 800;
        }}

        QLabel#SeparationAssetStatus[availability="ready"] {{
            color: {success_text};
            background: {success_background};
            border-color: {success_border};
        }}

        QLabel#SeparationAssetStatus[availability="download"] {{
            color: {warning_text};
            background: {warning_background};
            border-color: {warning_border};
        }}

        QPushButton#IconButton {{
            min-width: 34px;
            max-width: 34px;
            padding: 0;
            border-radius: 10px;
        }}

        QPushButton#ControlIconButton {{
            min-width: 34px;
            max-width: 34px;
            min-height: 34px;
            max-height: 34px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#VideoSourceActionButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#EmbeddedActionButton,
        QPushButton#VideoOriginalUrlButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#TransportPlayButton {{
            min-width: 34px;
            max-width: 34px;
            min-height: 34px;
            max-height: 34px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#ThemeToggleButton {{
            min-width: 66px;
            max-width: 66px;
            min-height: 26px;
            max-height: 26px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#TitleBarLanguageButton {{
            min-width: 40px;
            max-width: 40px;
            min-height: 24px;
            max-height: 24px;
            padding: 0;
            border: 1px solid {border};
            border-radius: 9px;
            background: {raised};
            color: {text};
            font-size: 10px;
            font-weight: 900;
        }}

        QPushButton#GoogleAccountButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 24px;
            max-height: 24px;
            padding: 0;
            border: 1px solid {border};
            border-radius: 9px;
            background: {raised};
        }}

        QPushButton#ProcessingQueueButton {{
            min-width: 48px;
            max-width: 48px;
            min-height: 26px;
            max-height: 26px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#GoogleAccountButton[connected="true"] {{
            border-color: {success_border};
            background: {success_background};
        }}

        QPushButton#GoogleAccountButton:hover,
        QPushButton#GoogleAccountButton[pointerState="hover"] {{
            background: {hover};
            border-color: {faint};
        }}

        QPushButton#GoogleAccountButton:pressed,
        QPushButton#GoogleAccountButton[pointerState="pressed"] {{
            background: {pressed};
            border-color: {text};
        }}

        QPushButton#GoogleAccountButton:disabled {{
            background: {surface};
            border-color: {border};
        }}

        QPushButton#GoogleAccountButton::menu-indicator {{
            image: none;
            width: 0;
            height: 0;
        }}

        QPushButton#TitleBarLanguageButton:hover,
        QPushButton#TitleBarLanguageButton[pointerState="hover"] {{
            background: {hover};
            border-color: {faint};
        }}

        QPushButton#TitleBarLanguageButton:pressed,
        QPushButton#TitleBarLanguageButton[pointerState="pressed"] {{
            background: {pressed};
            border-color: {text};
        }}

        QPushButton#TitleBarLanguageButton[keyboardFocus="true"] {{
            border-color: {focus};
        }}

        QPushButton#TitleBarLanguageButton::menu-indicator {{
            image: none;
            width: 0;
            height: 0;
        }}

        QMenu {{
            background: {surface};
            color: {text};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 6px;
        }}

        QMenu::item {{
            min-width: 112px;
            padding: 8px 16px 8px 28px;
            border-radius: 6px;
        }}

        QMenu::item:selected {{
            background: {hover};
        }}

        QMenu::indicator:checked {{
            image: none;
            width: 7px;
            height: 7px;
            border-radius: 3px;
            background: {accent};
        }}

        QFrame#GoogleStorageSummary {{
            background: transparent;
            border: 0;
        }}

        QLabel#GoogleStorageIdentity {{
            color: {text};
            font-weight: 800;
        }}

        QLabel#GoogleStorageEmail,
        QLabel#GoogleStorageDetail {{
            color: {muted};
            font-size: 11px;
        }}

        QLabel#GoogleStorageDetail[storageState="warning"] {{
            color: {warning_text};
        }}

        QLabel#GoogleStorageDetail[storageState="danger"] {{
            color: {danger_text};
        }}

        QProgressBar#GoogleStorageBar {{
            min-height: 7px;
            max-height: 7px;
            border: 0;
            border-radius: 3px;
            background: {raised};
        }}

        QProgressBar#GoogleStorageBar::chunk {{
            border-radius: 3px;
            background: {success_text};
        }}

        QProgressBar#GoogleStorageBar[storageState="warning"]::chunk {{
            background: {warning_text};
        }}

        QProgressBar#GoogleStorageBar[storageState="danger"]::chunk {{
            background: {danger_text};
        }}

        QProgressBar#GoogleStorageBar[storageState="unknown"]::chunk {{
            background: {faint};
        }}

        QPushButton#WindowControlButton, QPushButton#WindowCloseButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            border-radius: 8px;
            background: transparent;
            color: {text};
            font-weight: 900;
        }}

        QPushButton#SvgIconButton {{
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DangerIconButton {{
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#TrackActionButton, QPushButton#TrackMuteButton {{
            min-width: 26px;
            max-width: 26px;
            min-height: 26px;
            max-height: 26px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DropFileButton {{
            min-width: 58px;
            max-width: 58px;
            min-height: 58px;
            max-height: 58px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            min-height: 34px;
            padding: 0 10px;
            background: {raised};
            color: {text};
            border: 1px solid {border};
            border-radius: 9px;
            selection-background-color: {selection};
        }}

        QComboBox {{
            padding-right: 30px;
        }}

        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 28px;
            border: 0;
            border-left: 1px solid {border};
            background: transparent;
        }}

        QComboBox::down-arrow {{
            image: url("{chevron_down}");
            width: 9px;
            height: 6px;
        }}

        QSpinBox, QDoubleSpinBox {{
            padding-right: 28px;
        }}

        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            width: 24px;
            border: 0;
            border-left: 1px solid {border};
            background: transparent;
        }}

        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: 8px;
        }}

        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: 8px;
        }}

        QSpinBox::up-button:hover, QSpinBox::down-button:hover,
        QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
        QComboBox::drop-down:hover {{
            background: {hover};
        }}

        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{chevron_up}");
            width: 8px;
            height: 5px;
        }}

        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{chevron_down}");
            width: 8px;
            height: 5px;
        }}

        QPlainTextEdit#ModelNotesInput {{
            padding: 8px 10px;
            background: {raised};
            color: {text};
            border: 1px solid {border};
            border-radius: 9px;
            selection-background-color: {selection};
        }}

        QLineEdit#InlineTitleEdit {{
            min-height: 26px;
            max-height: 26px;
            padding: 0 8px;
            border-radius: 7px;
            font-weight: 800;
        }}

        QComboBox QAbstractItemView {{
            background: {surface};
            color: {text};
            border: 1px solid {border};
            selection-background-color: {selection};
            selection-color: {text};
            outline: 0;
        }}

        QListWidget {{
            background: transparent;
            border: 0;
            outline: 0;
        }}

        QListWidget::item {{
            margin: 4px 0;
            border-radius: 14px;
        }}

        QListWidget::item:selected {{
            background: {selection};
        }}

        QListWidget::item:hover {{
            background: {hover};
        }}

        QListWidget#ModelList::item,
        QListWidget#ModelList::item:hover,
        QListWidget#ModelList::item:selected {{
            background: transparent;
            margin: 3px 0;
        }}

        QProgressBar {{
            height: 12px;
            background: {raised};
            border: 1px solid {border};
            border-radius: 6px;
            text-align: center;
            color: transparent;
        }}

        QProgressBar::chunk {{
            background: {accent};
            border-radius: 5px;
        }}

        QProgressBar#ModelImportProgress {{
            height: 8px;
        }}

        QProgressBar#DatasetProgress {{
            height: 6px;
        }}

        QProgressBar#ActionProgress {{
            height: 8px;
            background: {raised};
            border: 1px solid {border};
            border-radius: 4px;
        }}

        QProgressBar#ActionProgress::chunk {{
            background: {accent};
            border-radius: 3px;
        }}

        QSlider::groove:horizontal {{
            height: 3px;
            background: {border};
            border-radius: 1px;
        }}

        QSlider {{
            background: transparent;
            min-height: 18px;
        }}

        QSlider::sub-page:horizontal {{
            background: {text};
            border-radius: 1px;
        }}

        QSlider::handle:horizontal {{
            width: 12px;
            height: 12px;
            margin: -5px 0;
            border-radius: 6px;
            background: {text};
        }}

        QScrollArea {{
            border: 0;
            background: transparent;
        }}

        QScrollBar:vertical {{
            width: 8px;
            background: transparent;
            margin: 0;
        }}

        QScrollBar::handle:vertical {{
            min-height: 40px;
            background: {border};
            border-radius: 4px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {faint};
        }}

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            border: 0;
            background: transparent;
            height: 0;
        }}

        QScrollBar:horizontal {{
            height: 8px;
            background: transparent;
            margin: 0;
        }}

        QScrollBar::handle:horizontal {{
            min-width: 40px;
            background: {border};
            border-radius: 4px;
        }}

        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal,
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {{
            border: 0;
            background: transparent;
            width: 0;
        }}

        QSizeGrip {{
            background: transparent;
            width: 14px;
            height: 14px;
        }}
    """
