from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from tkinterdnd2 import TkinterDnD

from jang_app.config import LOG_FILE, SEPARATION_OUTPUT_DIR, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.pipeline.rvc_convert import RvcConversionError, convert_vocal_with_rvc
from jang_app.pipeline.separate import SeparationError, separate_audio
from jang_app.services.app_logging import get_logger
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.settings import AppSettings, RvcSettings, load_app_settings, save_app_settings
from jang_app.services.song_library import SongLibrary
from jang_app.ui.controls import CanvasButton
from jang_app.ui.drop_zone import DropZone
from jang_app.ui.progress_status import ProgressStatus
from jang_app.ui.rvc_convert_panel import RvcConvertPanel
from jang_app.ui.section_header import add_section_header
from jang_app.ui.settings_dialog import OutputSettingsDialog
from jang_app.ui.song_registration_page import SongRegistrationPage
from jang_app.ui.theme import apply_theme, theme_for_mode
from jang_app.ui.waveform_panel import WaveformPanel


MOON_ICON = "\u25d1"
SUN_ICON = "\u25cf"


class SeparationApp(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JJZero Audio")
        self.geometry("1260x760")
        self.minsize(1120, 700)
        settings = load_app_settings()
        self._settings = settings
        self._theme = theme_for_mode(settings.theme_mode)
        apply_theme(self, self._theme)
        self._song_library = SongLibrary()
        self._pages: dict[str, ttk.Frame] = {}
        self._nav_buttons: dict[str, CanvasButton] = {}
        self._active_page = ""
        self.input_path = tk.StringVar()
        self.selected_file = tk.StringVar(value="No audio selected.")
        self.output_root = tk.StringVar(value=str(settings.output_root))
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._logger = get_logger()
        self._latest_vocals_path: Path | None = None
        self._latest_instrumental_path: Path | None = None
        self._latest_job_dir: Path | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_workspace()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="App.TFrame", padding=(28, 22, 28, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text="JJZero Audio", style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            header,
            text="Split a local audio file into vocals and instrumental.",
            style="Muted.TLabel",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        nav = ttk.Frame(header, style="App.TFrame")
        nav.grid(row=2, column=0, sticky="w", pady=(14, 0))
        self._add_nav_button(nav, "songs", "Songs", 0)
        self._add_nav_button(nav, "studio", "Studio", 1)

        self.theme_button = CanvasButton(
            header,
            text=self._theme_toggle_icon(),
            command=self._toggle_theme_mode,
            theme=self._theme,
            variant="tool",
            width=38,
            height=32,
        )
        self.theme_button.grid(
            row=0,
            column=1,
            sticky="ne",
            rowspan=2,
            padx=(18, 0),
        )
        self.settings_button = CanvasButton(
            header,
            text="Settings",
            command=self._open_settings,
            theme=self._theme,
            variant="tool",
            width=98,
            height=32,
        )
        self.settings_button.grid(
            row=0,
            column=2,
            sticky="ne",
            rowspan=2,
            padx=(8, 0),
        )

    def _add_nav_button(self, parent: ttk.Frame, page_name: str, label: str, column: int) -> None:
        button = CanvasButton(
            parent,
            text=label,
            command=lambda name=page_name: self._show_page(name),
            theme=self._theme,
            variant="tool",
            width=78,
            height=30,
        )
        button.grid(row=0, column=column, sticky="w", padx=(0, 8))
        self._nav_buttons[page_name] = button

    def _build_workspace(self) -> None:
        workspace = ttk.Frame(self, style="App.TFrame", padding=(28, 0, 28, 18))
        workspace.grid(row=1, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)

        self._page_container = ttk.Frame(workspace, style="App.TFrame")
        self._page_container.grid(row=0, column=0, sticky="nsew")
        self._page_container.columnconfigure(0, weight=1)
        self._page_container.rowconfigure(0, weight=1)

        self._build_song_page(self._page_container)
        self._build_studio_page(self._page_container)
        self._show_page("songs")

    def _build_song_page(self, parent: ttk.Frame) -> None:
        self.song_page = SongRegistrationPage(
            parent,
            self._song_library,
            self._handle_registered_song,
            self._theme,
        )
        self.song_page.grid(row=0, column=0, sticky="nsew")
        self._pages["songs"] = self.song_page

    def _build_studio_page(self, parent: ttk.Frame) -> None:
        self.studio_page = ttk.Frame(parent, style="App.TFrame")
        self.studio_page.grid(row=0, column=0, sticky="nsew")
        self.studio_page.columnconfigure(0, weight=0, minsize=380)
        self.studio_page.columnconfigure(1, weight=1)
        self.studio_page.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.studio_page, style="App.TFrame")
        controls.grid(row=0, column=0, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1, uniform="left_control_sections")
        controls.rowconfigure(1, weight=1, uniform="left_control_sections")

        self._build_separation_panel(controls, 0)
        self._build_conversion_controls(controls, 1)

        self.waveform_panel = WaveformPanel(
            self.studio_page,
            self._theme,
            self._settings.output_root,
            self._handle_output_sound_set_selected,
        )
        self.waveform_panel.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        self._pages["studio"] = self.studio_page

    def _show_page(self, page_name: str) -> None:
        if page_name == self._active_page:
            return

        if self._active_page == "songs" and hasattr(self, "song_page"):
            self.song_page.stop_playback()
        if self._active_page == "studio" and hasattr(self, "waveform_panel"):
            self.waveform_panel.stop_playback()

        for name, page in self._pages.items():
            if name == page_name:
                page.grid()
            else:
                page.grid_remove()
        self._active_page = page_name
        self._sync_nav_buttons()

    def _sync_nav_buttons(self) -> None:
        for name, button in self._nav_buttons.items():
            button.configure(variant="primary" if name == self._active_page else "tool")

    def _handle_registered_song(self, path: Path) -> None:
        self._set_input_path(path)
        self.progress_status.reset("Song selected from registration page.")
        self._show_page("studio")

    def _build_separation_panel(self, parent: ttk.Frame, row: int) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        panel.grid(row=row, column=0, sticky="nsew", pady=(0, 8))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        add_section_header(panel, 0, "01", "Input", "Choose a local audio file.")
        self.drop_zone = DropZone(
            panel,
            self._handle_dropped_file,
            self.selected_file,
            theme=self._theme,
            accepted_extensions=SUPPORTED_AUDIO_EXTENSIONS,
        )
        self.drop_zone.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        ttk.Frame(panel, style="Divider.TFrame", height=1).grid(row=2, column=0, sticky="ew", pady=16)
        add_section_header(panel, 3, "02", "Separation", "Split vocals and instrumental.")
        self._build_run_controls(panel, 4)

    def _build_run_controls(self, parent: ttk.Frame, row: int) -> None:
        actions = ttk.Frame(parent, style="PanelBody.TFrame")
        actions.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)

        self.run_button = CanvasButton(
            actions,
            text="Separate",
            command=self._start_separation,
            theme=self._theme,
            variant="primary",
            width=332,
            height=34,
        )
        self.run_button.grid(row=0, column=0, sticky="ew")

        self.progress_status = ProgressStatus(actions)
        self.progress_status.grid(row=1, column=0, sticky="ew", pady=(12, 0))

    def _build_conversion_controls(self, parent: ttk.Frame, row: int) -> None:
        self.convert_panel = RvcConvertPanel(
            parent,
            self._settings,
            self._start_rvc_conversion,
            self._set_rvc_settings,
            self._open_settings,
            self._theme,
        )
        self.convert_panel.grid(row=row, column=0, sticky="nsew", pady=(8, 0))

    def _open_settings(self) -> None:
        OutputSettingsDialog(self, self._settings, self._set_settings)

    def _set_settings(self, settings: AppSettings) -> None:
        theme_changed = settings.theme_mode != self._settings.theme_mode
        self._settings = settings
        if theme_changed:
            self._apply_theme_mode()
        self.output_root.set(str(settings.output_root))
        self.convert_panel.update_settings(settings)
        self.waveform_panel.set_output_root(settings.output_root)

    def _set_rvc_settings(self, rvc_settings: RvcSettings) -> None:
        settings = AppSettings(
            output_root=self._settings.output_root,
            rvc=rvc_settings,
            theme_mode=self._settings.theme_mode,
        )
        save_app_settings(settings)
        self._set_settings(settings)

    def _toggle_theme_mode(self) -> None:
        next_mode = "dark" if self._settings.theme_mode == "white" else "white"
        settings = AppSettings(
            output_root=self._settings.output_root,
            rvc=self._settings.rvc,
            theme_mode=next_mode,
        )
        save_app_settings(settings)
        self._set_settings(settings)

    def _apply_theme_mode(self) -> None:
        self._theme = theme_for_mode(self._settings.theme_mode)
        apply_theme(self, self._theme)
        if hasattr(self, "theme_button"):
            self.theme_button.configure(text=self._theme_toggle_icon())
            self.theme_button.set_theme(self._theme)
        if hasattr(self, "settings_button"):
            self.settings_button.set_theme(self._theme)
        for button in self._nav_buttons.values():
            button.set_theme(self._theme)
        self._sync_nav_buttons()
        if hasattr(self, "song_page"):
            self.song_page.set_theme(self._theme)
        if hasattr(self, "run_button"):
            self.run_button.set_theme(self._theme)
        if hasattr(self, "drop_zone"):
            self.drop_zone.set_theme(self._theme)
        if hasattr(self, "convert_panel"):
            self.convert_panel.set_theme(self._theme)
        if hasattr(self, "waveform_panel"):
            self.waveform_panel.set_theme(self._theme)

    def _theme_toggle_icon(self) -> str:
        return MOON_ICON if self._settings.theme_mode == "white" else SUN_ICON

    def _handle_output_sound_set_selected(self, sound_set: OutputSoundSet) -> None:
        self._latest_vocals_path = sound_set.vocals_path
        self._latest_instrumental_path = sound_set.instrumental_path
        self._latest_job_dir = sound_set.job_dir
        self.convert_panel.set_convert_enabled(True)
        self.convert_panel.set_progress(0, "Ready to convert vocals.")

    def _handle_dropped_file(self, path: Path) -> None:
        self._set_input_path(path)
        self.progress_status.reset("Audio file selected.")

    def _set_input_path(self, path: Path) -> None:
        self.input_path.set(str(path))
        self.selected_file.set(path.name)
        self._clear_latest_outputs()
        self.waveform_panel.show_empty()

    def _clear_latest_outputs(self) -> None:
        self._latest_vocals_path = None
        self._latest_instrumental_path = None
        self._latest_job_dir = None
        if hasattr(self, "convert_panel"):
            self.convert_panel.set_convert_enabled(False)
            self.convert_panel.reset_status("Separate audio before converting.")

    def _start_separation(self) -> None:
        input_value = self.input_path.get().strip()
        output_value = self.output_root.get().strip()
        if not input_value:
            messagebox.showwarning("Missing input", "Select an audio file first.")
            return
        if not output_value:
            messagebox.showwarning("Missing output", "Select an output folder first.")
            return

        self.run_button.configure(state="disabled")
        self.convert_panel.set_convert_enabled(False)
        self.convert_panel.reset_status("Waiting for separated vocal.")
        self._set_progress(0, "Separating audio... 0%")

        worker = threading.Thread(
            target=self._run_separation,
            args=(Path(input_value), Path(output_value)),
            daemon=True,
        )
        worker.start()

    def _run_separation(self, input_path: Path, output_root: Path) -> None:
        try:
            result = separate_audio(
                input_path=input_path,
                output_root=output_root,
                progress_callback=self._report_progress,
            )
        except SeparationError as exc:
            self._logger.warning("Separation failed: %s", exc)
            self._events.put(("error", str(exc)))
        except Exception as exc:
            self._logger.exception("Unexpected separation error")
            self._events.put(("error", f"Unexpected error: {exc}"))
        else:
            self._events.put(("success", result))

    def _start_rvc_conversion(self) -> None:
        if not self.convert_panel.apply_settings():
            return
        if self._latest_vocals_path is None or self._latest_job_dir is None:
            messagebox.showwarning("Missing vocal", "Separate audio before converting vocals.")
            return
        if not self._settings.rvc.voice_model:
            messagebox.showwarning("Missing RVC model", "Select an RVC voice model in Settings first.")
            return

        self.waveform_panel.stop_playback()
        self.run_button.configure(state="disabled")
        self.convert_panel.set_convert_enabled(False)
        self.convert_panel.set_progress(10, "Converting vocal with RVC...")
        worker = threading.Thread(
            target=self._run_rvc_conversion,
            args=(self._latest_vocals_path, self._latest_job_dir),
            daemon=True,
        )
        worker.start()

    def _run_rvc_conversion(self, vocals_path: Path, job_dir: Path) -> None:
        try:
            result = convert_vocal_with_rvc(vocals_path, job_dir, self._settings.rvc)
        except RvcConversionError as exc:
            self._logger.warning("RVC conversion failed: %s", exc)
            self._events.put(("rvc_error", str(exc)))
        except Exception as exc:
            self._logger.exception("Unexpected RVC conversion error")
            self._events.put(("rvc_error", f"Unexpected error: {exc}"))
        else:
            self._events.put(("rvc_success", result))

    def _report_progress(self, percent: int) -> None:
        self._events.put(("progress", percent))

    def _poll_events(self) -> None:
        try:
            event, payload = self._events.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_events)
            return

        if event == "progress":
            self._set_progress(int(payload))
            self.after(100, self._poll_events)
            return

        self.run_button.configure(state="normal")
        if event == "success":
            result = payload
            self._latest_vocals_path = result.vocals_path
            self._latest_instrumental_path = result.accompaniment_path
            self._latest_job_dir = result.job_dir
            self.convert_panel.set_convert_enabled(True)
            self._set_progress(100)
            self._show_result_waveforms(result.vocals_path, result.accompaniment_path)
            self.progress_status.set_text(f"Output ready: {result.job_dir}")
            self.convert_panel.set_progress(0, "Ready to convert vocals.")
        elif event == "rvc_success":
            result = payload
            self.convert_panel.set_convert_enabled(True)
            self._show_converted_vocal(result.output_path)
            self.convert_panel.set_progress(100, f"Converted vocal ready: {result.output_path}")
        elif event == "rvc_error":
            if self._latest_vocals_path is not None:
                self.convert_panel.set_convert_enabled(True)
            self.convert_panel.set_progress(0, f"RVC failed. Log file: {LOG_FILE}")
        else:
            self.progress_status.set_text(f"Failed. Log file: {LOG_FILE}")
            messagebox.showerror("Separation failed", f"{payload}\n\nLog file:\n{LOG_FILE}")

        self.after(100, self._poll_events)

    def _set_progress(self, percent: int, text: str | None = None) -> None:
        value = max(0, min(100, percent))
        self.progress_status.set_progress(value, text or f"Separating audio... {value}%")

    def _show_result_waveforms(self, vocals_path: Path, accompaniment_path: Path) -> None:
        try:
            self.waveform_panel.show_files(vocals_path, accompaniment_path)
        except Exception:
            self._logger.exception("Failed to render waveform preview")

    def _show_converted_vocal(self, converted_vocals_path: Path) -> None:
        if self._latest_instrumental_path is None:
            return
        try:
            self.waveform_panel.show_converted_vocal(converted_vocals_path, self._latest_instrumental_path)
        except Exception:
            self._logger.exception("Failed to render converted waveform preview")

    def _handle_close(self) -> None:
        if hasattr(self, "song_page"):
            self.song_page.stop_playback()
        self.waveform_panel.stop_playback()
        self.destroy()


def main() -> None:
    SEPARATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    get_logger().info("Starting JJZero Audio")
    app = SeparationApp()
    app.mainloop()
