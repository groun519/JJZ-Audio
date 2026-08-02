from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from jang_app.services.studio_session import StudioSession


class StudioSessionAutosave(QObject):
    save_failed = Signal(str)

    def __init__(
        self,
        save_session: Callable[[str, StudioSession], object],
        *,
        delay_ms: int = 300,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._save_session = save_session
        self._pending: tuple[str, StudioSession] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.flush)

    def queue(self, song_id: str, session: StudioSession) -> None:
        if not song_id:
            return
        if self._pending is not None and self._pending[0] != song_id:
            self.flush()
        self._pending = (song_id, session)
        self._timer.start()

    def flush(self) -> None:
        self._timer.stop()
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        song_id, session = pending
        try:
            self._save_session(song_id, session)
        except (KeyError, OSError) as exc:
            self.save_failed.emit(str(exc))
