from __future__ import annotations

from jang_app.config import ASSETS_DIR


def next_theme_mode(theme_mode: str) -> str:
    return "dark" if theme_mode == "white" else "white"


def build_stylesheet(theme_mode: str) -> str:
    icon_tone = "light" if theme_mode == "dark" else "dark"
    chevron_down = (ASSETS_DIR / f"control_chevron_down_{icon_tone}.svg").as_posix()
    chevron_up = (ASSETS_DIR / f"control_chevron_up_{icon_tone}.svg").as_posix()
    if theme_mode == "dark":
        return _stylesheet(
            background="#151515",
            chrome="#111111",
            surface="#1b1b1a",
            card="#212120",
            raised="#272725",
            text="#ecebe7",
            muted="#aaa8a1",
            faint="#6c6b66",
            border="#383835",
            button_border="#484843",
            accent="#efeee9",
            accent_text="#171717",
            hover="#30302e",
            pressed="#3a3a37",
            selection="#323230",
            active_hover="#e0dfd9",
            active_pressed="#c9c8c2",
            focus="#898780",
            tab_active="#30302e",
            tab_active_text="#ecebe7",
            tab_active_hover="#393936",
            tab_active_pressed="#444440",
            tab_active_border="#4b4b46",
            source_local_text="#c7d6e8",
            source_local_background="#202a34",
            source_local_border="#40566c",
            source_youtube_text="#ffd4d4",
            source_youtube_background="#3a2022",
            source_youtube_border="#7a3a3f",
            source_output_text="#c9f0dc",
            source_output_background="#1f3128",
            source_output_border="#3f6b53",
            chevron_down=chevron_down,
            chevron_up=chevron_up,
        )

    return _stylesheet(
        background="#f6f3ec",
        chrome="#fffdf7",
        surface="#fffdf7",
        card="#fffdf7",
        raised="#ebe7dd",
        text="#10100e",
        muted="#6e6a61",
        faint="#aaa397",
        border="#d8d0c2",
        button_border="#10100e",
        accent="#10100e",
        accent_text="#fffdf7",
        hover="#e7e1d5",
        pressed="#d1c8b8",
        selection="#ded6ca",
        active_hover="#2b2a26",
        active_pressed="#46443e",
        focus="#6e6a61",
        tab_active="#10100e",
        tab_active_text="#fffdf7",
        tab_active_hover="#2b2a26",
        tab_active_pressed="#46443e",
        tab_active_border="#10100e",
        source_local_text="#244664",
        source_local_background="#e5eef5",
        source_local_border="#9bb3c6",
        source_youtube_text="#8a2930",
        source_youtube_background="#f6e4e4",
        source_youtube_border="#d7a2a5",
        source_output_text="#24543c",
        source_output_background="#e2f0e8",
        source_output_border="#9abda8",
        chevron_down=chevron_down,
        chevron_up=chevron_up,
    )


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
    chevron_down: str,
    chevron_up: str,
) -> str:
    return f"""
        QWidget {{
            background: {background};
            color: {text};
            font-family: "Malgun Gothic", "Segoe UI", "Arial";
            font-size: 13px;
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

        QFrame#NavigationGroupDivider {{
            background: {border};
            border: 0;
        }}

        QWidget#AppContent {{
            background: {background};
            border: 0;
        }}

        QFrame#WorkspaceTransportDock {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 16px;
        }}

        QFrame#WorkspaceTransportDivider {{
            background: {border};
            border: 0;
        }}

        QLabel#WorkBadge {{
            color: {tab_active_text};
            background: {tab_active};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
            min-height: 22px;
        }}

        QLabel#WorkSourceBadge {{
            color: {source_local_text};
            background: {source_local_background};
            border: 1px solid {source_local_border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
            min-height: 22px;
        }}

        QLabel#WorkSourceBadge[sourceType="youtube"] {{
            color: {source_youtube_text};
            background: {source_youtube_background};
            border-color: {source_youtube_border};
        }}

        QLabel#WorkSourceBadge[sourceType="output"] {{
            color: {source_output_text};
            background: {source_output_background};
            border-color: {source_output_border};
        }}

        QLabel#WorkStateBadge {{
            color: {text};
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
            min-height: 22px;
        }}

        QComboBox#WorkSongCombo, QComboBox#ExportSongCombo {{
            min-height: 32px;
            max-height: 32px;
            font-size: 13px;
            font-weight: 850;
            background: {raised};
        }}

        QComboBox#WorkSongCombo QLineEdit, QComboBox#ExportSongCombo QLineEdit {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 8px;
            background: transparent;
            border: 0;
            border-radius: 0;
            font-size: 13px;
            font-weight: 850;
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

        QFrame#VideoPreviewPanel {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 18px;
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

        QScrollArea#StudioStepScroll {{
            background: transparent;
            border: 0;
        }}

        QScrollArea#StudioStepScroll > QWidget > QWidget {{
            background: transparent;
        }}

        QFrame#Card, QFrame#TrackCard {{
            background: {card};
            border: 1px solid {border};
            border-radius: 18px;
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

        QWidget#SongListRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 16px;
        }}

        QWidget#SongListRow:hover {{
            background: {hover};
        }}

        QWidget#SongListRow[selected="true"] {{
            background: {selection};
            border: 1px solid {tab_active_border};
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

        #LibraryRowTitle {{
            color: {text};
            font-size: 14px;
            font-weight: 900;
        }}

        QFrame#LibraryPreviewDivider {{
            background: {border};
            border: 0;
        }}

        QWidget#LibraryPreviewTransport {{
            background: transparent;
            border: 0;
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

        QFrame#ExportRow {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#ExportRow:hover {{
            background: {hover};
        }}

        QLabel#ExportName {{
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

        QLabel#ProcessingTaskTitle {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
        }}

        QLabel#ProcessingTaskDetail, QLabel#ProcessingQueueEmpty {{
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

        QLabel#PlayerContext {{
            color: {tab_active_text};
            background: {tab_active};
            border-radius: 10px;
            font-size: 11px;
            font-weight: 900;
            min-height: 24px;
        }}

        QLabel#PlayerTitle {{
            color: {text};
            font-size: 13px;
            font-weight: 800;
        }}

        QLabel#PlayerTime, QLabel#TransportTime {{
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

        QPushButton#PrimaryButton {{
            background: {accent};
            color: {accent_text};
            border-color: {accent};
        }}

        QPushButton#PrimaryButton:hover,
        QPushButton#PrimaryButton[pointerState="hover"] {{
            background: {active_hover};
        }}

        QPushButton#PrimaryButton:pressed,
        QPushButton#PrimaryButton[pointerState="pressed"] {{
            background: {active_pressed};
        }}

        QPushButton#PrimaryButton[keyboardFocus="true"] {{
            background: {active_hover};
            border-color: {focus};
        }}

        QPushButton#PrimaryButton:disabled {{
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
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border: 0;
            background: transparent;
        }}

        QPushButton#DatasetEditorIconButton:checked {{
            color: {tab_active_text};
            background: {tab_active};
            border-radius: 8px;
        }}

        QPushButton#DatasetEditorSecondaryButton {{
            min-height: 30px;
            max-height: 30px;
            padding: 0 12px;
            border-radius: 9px;
            background: {surface};
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
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
        }}

        QPushButton#DatasetReadyButton:hover,
        QPushButton#DatasetReadyButton[pointerState="hover"] {{
            background: {hover};
        }}

        QPushButton#DatasetReadyButton:pressed,
        QPushButton#DatasetReadyButton[pointerState="pressed"] {{
            background: {pressed};
        }}

        QPushButton#DatasetReadyButton[keyboardFocus="true"] {{
            background: {selection};
            border-color: {focus};
        }}

        QPushButton#DatasetReadyButton:disabled {{
            color: {muted};
            background: {surface};
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

        QPushButton#WindowControlButton, QPushButton#WindowCloseButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 26px;
            max-height: 26px;
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

        QLineEdit, QComboBox, QSpinBox {{
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

        QSpinBox {{
            padding-right: 28px;
        }}

        QSpinBox::up-button, QSpinBox::down-button {{
            subcontrol-origin: border;
            width: 24px;
            border: 0;
            border-left: 1px solid {border};
            background: transparent;
        }}

        QSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: 8px;
        }}

        QSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: 8px;
        }}

        QSpinBox::up-button:hover, QSpinBox::down-button:hover,
        QComboBox::drop-down:hover {{
            background: {hover};
        }}

        QSpinBox::up-arrow {{
            image: url("{chevron_up}");
            width: 8px;
            height: 5px;
        }}

        QSpinBox::down-arrow {{
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
