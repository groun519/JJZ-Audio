from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from jang_app.services.studio_session import StudioSession

if TYPE_CHECKING:
    from jang_app.services.studio_assets import StudioSoundAsset


class StudioSessionAutosave(QObject):
    save_failed = Signal(str)
    save_state_changed = Signal(str, str)
    _background_finished = Signal(object)

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
            tuple[int, StudioSession, tuple[StudioSoundAsset, ...]],
        ] = {}
        self._inflight: tuple[
            str,
            tuple[int, StudioSession, tuple[StudioSoundAsset, ...]],
            Future[object],
        ] | None = None
        self._generation_lock = RLock()
        self._generations: dict[str, int] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="jjzero-studio-save",
        )
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._start_background_save)
        self._background_finished.connect(self._finish_background_save)
        self.destroyed.connect(self._shutdown_executor)

    def queue(
        self,
        song_id: str,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...],
    ) -> None:
        if not song_id:
            return
        generation = self._advance_generation(song_id)
        self._pending[song_id] = (generation, session, assets)
        self.save_state_changed.emit(song_id, "pending")
        self._timer.start()

    def flush(self) -> bool:
        self._timer.stop()
        saved = True
        inflight = self._inflight
        if inflight is not None:
            future = inflight[2]
            try:
                future.result()
            except Exception:
                pass
            saved = self._finish_background_save(future) and saved
        for song_id in tuple(self._pending):
            saved = self._flush_song_sync(song_id) and saved
        return saved

    def _start_background_save(self) -> None:
        if self._inflight is not None or not self._pending:
            return
        song_id = next(iter(self._pending))
        pending = self._pending.pop(song_id)
        generation, session, assets = pending
        self.save_state_changed.emit(song_id, "saving")
        future = self._executor.submit(
            self._save_if_current,
            song_id,
            generation,
            session,
            assets,
        )
        self._inflight = (song_id, pending, future)
        future.add_done_callback(self._background_finished.emit)

    def _finish_background_save(self, future: Future[object]) -> bool:
        inflight = self._inflight
        if inflight is None or inflight[2] is not future:
            return True
        song_id, pending, _future = inflight
        generation, session, _assets = pending
        self._inflight = None
        try:
            future.result()
        except KeyError as exc:
            if self._is_current(song_id, generation):
                self.save_failed.emit(str(exc))
                self.save_state_changed.emit(song_id, "failed")
                saved = False
            else:
                saved = True
        except Exception as exc:
            if self._is_current(song_id, generation):
                self._pending.setdefault(song_id, pending)
                logging.getLogger("jang_app").exception(
                    "Studio session autosave failed | song=%s",
                    song_id,
                )
                self.save_failed.emit(str(exc))
                self.save_state_changed.emit(song_id, "failed")
                saved = False
            else:
                saved = True
        else:
            if not self._is_current(song_id, generation):
                saved = True
            elif song_id in self._pending:
                logging.getLogger("jang_app").info(
                    "Studio session save superseded | song=%s",
                    song_id,
                )
                saved = True
            else:
                self._log_saved(song_id, session)
                saved = True
        if self._pending:
            self._timer.start(0)
        return saved

    def _flush_song_sync(self, song_id: str) -> bool:
        pending = self._pending.get(song_id)
        if pending is None:
            return True
        generation, session, assets = pending
        if not self._is_current(song_id, generation):
            self._pending.pop(song_id, None)
            return True
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
        self._log_saved(song_id, session)
        return True

    def _log_saved(self, song_id: str, session: StudioSession) -> None:
        logging.getLogger("jang_app").info(
            "Studio session saved | song=%s tracks=%s clips=%s",
            song_id,
            len(session.tracks),
            sum(len(track.clips) for track in session.tracks),
        )
        self.save_state_changed.emit(song_id, "saved")

    def discard(self, song_id: str) -> None:
        self._advance_generation(song_id)
        self._pending.pop(song_id, None)
        if not self._pending:
            self._timer.stop()
        inflight = self._inflight
        if inflight is not None and inflight[0] == song_id:
            try:
                inflight[2].result()
            except Exception:
                pass
            self._finish_background_save(inflight[2])

    def _save_if_current(
        self,
        song_id: str,
        generation: int,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...],
    ) -> object:
        if not self._is_current(song_id, generation):
            return None
        return self._save_session(song_id, session, assets)

    def _advance_generation(self, song_id: str) -> int:
        with self._generation_lock:
            generation = self._generations.get(song_id, 0) + 1
            self._generations[song_id] = generation
            return generation

    def _is_current(self, song_id: str, generation: int) -> bool:
        with self._generation_lock:
            return self._generations.get(song_id, 0) == generation

    def _shutdown_executor(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
