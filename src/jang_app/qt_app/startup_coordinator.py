from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.config import APP_ICON_PATH
from jang_app.qt_app.startup_splash import StartupSplash
from jang_app.services.app_bootstrap import prepare_app_environment
from jang_app.services.settings import AppSettings, load_app_settings
from jang_app.services.startup_timing import StartupTimeline


PrepareEnvironment = Callable[[], object]
SettingsLoader = Callable[[], AppSettings]
WindowLoader = Callable[[], type[QWidget]]


@dataclass(frozen=True)
class _StartupStage:
    message: str
    progress: float
    action: Callable[[], None]


class StartupCoordinator(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        app: QApplication,
        timeline: StartupTimeline,
        logger: logging.Logger,
        *,
        splash: StartupSplash | None = None,
        prepare_environment: PrepareEnvironment = prepare_app_environment,
        settings_loader: SettingsLoader = load_app_settings,
        window_loader: WindowLoader | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._timeline = timeline
        self._logger = logger
        self._splash = splash or StartupSplash(APP_ICON_PATH)
        self._prepare_environment = prepare_environment
        self._settings_loader = settings_loader
        self._window_loader = window_loader or _load_main_window
        self._settings: AppSettings | None = None
        self._window_type: type[QWidget] | None = None
        self._window: QWidget | None = None
        self._stage_index = 0
        self._stages = (
            _StartupStage("Preparing local workspace", 0.14, self._prepare_storage),
            _StartupStage("Loading preferences", 0.28, self._load_settings),
            _StartupStage("Loading workspace modules", 0.48, self._load_window_type),
            _StartupStage("Restoring library and work session", 0.78, self._create_window),
            _StartupStage("Opening workspace", 0.96, self._show_window),
        )
        self._splash.close_requested.connect(lambda: self._app.exit(1))

    @property
    def splash(self) -> StartupSplash:
        return self._splash

    @property
    def window(self) -> QWidget | None:
        return self._window

    @property
    def timeline(self) -> StartupTimeline:
        return self._timeline

    def start(self) -> None:
        self._splash.show_centered()
        self._timeline.mark("splash_shown")
        QTimer.singleShot(0, self._run_next_stage)

    def _run_next_stage(self) -> None:
        if self._stage_index >= len(self._stages):
            self._finish()
            return
        stage = self._stages[self._stage_index]
        self._splash.set_stage(stage.message, stage.progress)
        self._app.processEvents()
        try:
            stage.action()
        except Exception as exc:
            self._fail(exc)
            return
        self._stage_index += 1
        QTimer.singleShot(0, self._run_next_stage)

    def _prepare_storage(self) -> None:
        self._prepare_environment()
        self._timeline.mark("storage_ready")

    def _load_settings(self) -> None:
        self._settings = self._settings_loader()
        self._timeline.mark("settings_loaded")

    def _load_window_type(self) -> None:
        self._window_type = self._window_loader()
        self._timeline.mark("main_window_imported")

    def _create_window(self) -> None:
        if self._settings is None or self._window_type is None:
            raise RuntimeError("Startup prerequisites are incomplete")
        self._window = self._window_type(self._settings)
        self._timeline.mark("main_window_created")

    def _show_window(self) -> None:
        if self._window is None:
            raise RuntimeError("Main window was not created")
        self._splash.finish(self._window)
        self._timeline.mark("window_shown")

    def _finish(self) -> None:
        if self._window is None:
            self._fail(RuntimeError("Startup completed without a main window"))
            return
        self._timeline.mark("event_loop_ready")
        self._logger.info(self._timeline.summary())
        self.finished.emit(self._window)

    def _fail(self, error: Exception) -> None:
        self._logger.exception("JJZero Audio startup failed")
        self._splash.show_error(str(error))
        self.failed.emit(str(error))


def _load_main_window() -> type[QWidget]:
    from jang_app.qt_app.main_window import MainWindow

    return MainWindow
