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
            background="#080808",
            surface="#111111",
            raised="#191919",
            text="#f7f4ec",
            muted="#a9a49a",
            faint="#5f5b54",
            border="#34312d",
            accent="#f7f4ec",
            accent_text="#090909",
            hover="#23211f",
            selection="#2c2a27",
            chevron_down=chevron_down,
            chevron_up=chevron_up,
        )

    return _stylesheet(
        background="#f6f3ec",
        surface="#fffdf7",
        raised="#ebe7dd",
        text="#10100e",
        muted="#6e6a61",
        faint="#aaa397",
        border="#d8d0c2",
        accent="#10100e",
        accent_text="#fffdf7",
        hover="#e7e1d5",
        selection="#ded6ca",
        chevron_down=chevron_down,
        chevron_up=chevron_up,
    )


def _stylesheet(
    *,
    background: str,
    surface: str,
    raised: str,
    text: str,
    muted: str,
    faint: str,
    border: str,
    accent: str,
    accent_text: str,
    hover: str,
    selection: str,
    chevron_down: str,
    chevron_up: str,
) -> str:
    return f"""
        QWidget {{
            background: {background};
            color: {text};
            font-family: "Segoe UI", "Malgun Gothic", "Arial";
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
            background: {surface};
            border: 0;
            border-bottom: 1px solid {border};
            border-radius: 0;
        }}

        QFrame#WindowTitleBar QLabel#AppTitle {{
            font-size: 16px;
            font-weight: 900;
            letter-spacing: 0;
        }}

        QFrame#NavigationBar {{
            background: {background};
            border: 0;
            border-radius: 0;
        }}

        QWidget#AppContent {{
            background: {background};
            border: 0;
        }}

        QFrame#WorkContextBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 16px;
        }}

        QLabel#WorkBadge {{
            color: {accent_text};
            background: {accent};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
            min-height: 22px;
        }}

        QLabel#WorkSourceBadge {{
            color: {text};
            background: {raised};
            border: 1px solid {border};
            border-radius: 9px;
            font-size: 10px;
            font-weight: 900;
            min-height: 22px;
        }}

        QLabel#WorkSourceBadge[sourceType="youtube"] {{
            color: {accent_text};
            background: {accent};
            border-color: {accent};
        }}

        QLabel#WorkSourceBadge[sourceType="output"] {{
            color: {text};
            background: {selection};
            border-color: {faint};
        }}

        QLabel#WorkTitle {{
            color: {text};
            font-size: 13px;
            font-weight: 900;
        }}

        QLabel#WorkDetail, QLabel#WorkOutput {{
            color: {muted};
            font-size: 11px;
            font-weight: 700;
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

        QFrame#Panel, QFrame#Card, QFrame#TrackCard {{
            background: {surface};
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
            border: 1px solid {text};
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
            border: 1px solid {text};
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
            color: {accent_text};
            background: {accent};
            border-color: {accent};
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
            color: {accent_text};
            background: {accent};
            border-color: {accent};
        }}

        QLabel#ArtifactState[state="missing"], QLabel#ArtifactState[state="mismatch"] {{
            color: #c93d3d;
            border-color: #c93d3d;
        }}

        QWidget#SongActionSlot {{
            background: transparent;
            border: 0;
        }}

        QLabel#LibraryRowTitle {{
            color: {text};
            font-size: 14px;
            font-weight: 900;
        }}

        QLabel#LibraryRowMeta {{
            color: {muted};
            font-size: 12px;
            font-weight: 700;
        }}

        QLabel#SourceBadge {{
            color: {text};
            background: {background};
            border: 1px solid {border};
            border-radius: 10px;
            font-size: 10px;
            font-weight: 900;
            min-height: 24px;
        }}

        QLabel#SourceBadge[sourceType="youtube"] {{
            color: {accent_text};
            background: {accent};
            border-color: {accent};
        }}

        QLabel#SourceBadge[sourceType="output"] {{
            color: {text};
            background: {selection};
            border-color: {faint};
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

        QFrame#GlobalPlayerBar {{
            background: {surface};
            border: 1px solid {border};
            border-radius: 18px;
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
            color: {accent_text};
            background: {accent};
            border-color: {accent};
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
            color: {accent_text};
            background: {accent};
            border-color: {accent};
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
            border: 0;
            background: transparent;
            color: {muted};
            font-size: 10px;
        }}

        QPushButton#ProcessingQueueClear:hover {{
            color: {text};
            background: {hover};
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
            color: {accent_text};
            background: {accent};
            border: 1px solid {accent};
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
            border-color: {text};
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
            color: {accent_text};
            background: {accent};
            border-color: {accent};
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
            color: {accent_text};
            background: {accent};
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

        QLabel#PlayerTime {{
            color: {muted};
            font-size: 12px;
            font-weight: 800;
        }}

        QFrame#VideoPreviewSurface {{
            background: #000000;
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#TrackControlStrip {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#TrackControlDivider {{
            background: {border};
            border: 0;
        }}

        QLabel#TrackTime {{
            color: {muted};
            font-size: 12px;
            font-weight: 800;
        }}

        QLabel#VolumeValue {{
            color: {text};
            font-size: 12px;
            font-weight: 900;
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
            border: 1px solid {text};
            border-radius: 10px;
            background: transparent;
            color: {text};
            font-weight: 700;
        }}

        QPushButton:hover {{
            background: {hover};
        }}

        QPushButton:pressed {{
            background: {selection};
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

        QPushButton#PrimaryButton:hover {{
            background: {text};
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

        QPushButton#NavButton {{
            min-width: 108px;
            min-height: 32px;
            border-radius: 17px;
            border-color: {border};
            background: transparent;
        }}

        QPushButton#NavButton:checked {{
            background: {accent};
            color: {accent_text};
            border-color: {accent};
        }}

        QFrame#NavigationBar QPushButton#NavButton:hover {{
            background: {hover};
            color: {text};
        }}

        QFrame#NavigationBar QPushButton#NavButton:checked {{
            background: {accent};
            color: {accent_text};
            border-color: {accent};
        }}

        QFrame#SegmentedControl {{
            background: {raised};
            border: 1px solid {border};
            border-radius: 20px;
        }}

        QPushButton#SegmentButton {{
            min-height: 36px;
            padding: 0 10px;
            border: 0;
            border-radius: 16px;
            background: transparent;
            color: {muted};
        }}

        QPushButton#SegmentButton:hover {{
            background: {hover};
            color: {text};
        }}

        QPushButton#SegmentButton:checked {{
            background: {accent};
            color: {accent_text};
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

        QPushButton#ThemeToggleButton {{
            min-width: 66px;
            max-width: 66px;
            min-height: 26px;
            max-height: 26px;
            padding: 0;
            border: 0;
            background: transparent;
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

        QPushButton#TrackIconButton {{
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
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
