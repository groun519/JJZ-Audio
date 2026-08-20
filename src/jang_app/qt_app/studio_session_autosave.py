from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from jang_app.services.studio_session import StudioSession

if TYPE_CHECKING:
    from jang_app.services.studio_assets import StudioSoundAsset


class StudioSessionAutosave(QObject):
    save_failed = Signal(str)
    save_state_changed = Signal(str, str)

    def __init__(
        self,
        save_session: Callable[
            [str, StudioSession, tuple[StudioSoundAsset, ...]],
            object,
        ],
        *,
        delay_ms: int = 300,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._save_session = save_session
        self._pending: dict[
            str,
            tuple[StudioSession, tuple[StudioSoundAsset, ...]],
        ] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.flush)

    def queue(
        self,
        song_id: str,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...],
    ) -> None:
        if not song_id:
            return
        for pending_song_id in tuple(self._pending):
            if pending_song_id != song_id:
                self._flush_song(pending_song_id)
        self._pending[song_id] = (session, assets)
        self.save_state_changed.emit(song_id, "pending")
        self._timer.start()

    def flush(self) -> bool:
        self._timer.stop()
        saved = True
        for song_id in tuple(self._pending):
            saved = self._flush_song(song_id) and saved
        return saved

    def _flush_song(self, song_id: str) -> bool:
        pending = self._pending.get(song_id)
        if pending is None:
            return True
        session, assets = pending
        self.save_state_changed.emit(song_id, "saving")
        try:
            self._save_session(song_id, session, assets)
        except KeyError as exc:
            self._pending.pop(song_id, None)
            self.save_failed.emit(str(exc))
            self.save_state_changed.emit(song_id, "failed")
            return False
        except Exception as exc:
            logging.getLogger("jang_app").exception(
                "Studio session autosave failed | song=%s",
                song_id,
            )
            self.save_failed.emit(str(exc))
            self.save_state_changed.emit(song_id, "failed")
            return False
        if self._pending.get(song_id) is pending:
            self._pending.pop(song_id, None)
        logging.getLogger("jang_app").info(
            "Studio session saved | song=%s tracks=%s clips=%s",
            song_id,
            len(session.tracks),
            sum(len(track.clips) for track in session.tracks),
        )
        self.save_state_changed.emit(song_id, "saved")
        return True

    def discard(self, song_id: str) -> None:
        self._pending.pop(song_id, None)
        if not self._pending:
            self._timer.stop()
