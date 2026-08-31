from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.clip_waveform_view import ClipWaveformView
from jang_app.qt_app.studio_editor import StudioTimelineView, _WAVEFORM_EXECUTOR
from jang_app.qt_app.waveform_thumbnail import (
    WaveformThumbnail,
    _WAVEFORM_EXECUTOR as _THUMBNAIL_WAVEFORM_EXECUTOR,
)
from jang_app.qt_app.widgets import WaveformView, _WAVEFORM_VIEW_EXECUTOR
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    TRACK_ORIGINAL_VOCAL,
    StudioAssetRef,
    StudioClip,
    StudioSession,
    StudioTrack,
)


class WaveformRequestLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_waveform_view_cancels_previous_path_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_path, second_path = _audio_paths(Path(temporary))
            first = Future()
            second = Future()
            view = WaveformView()

            with patch.object(
                _WAVEFORM_VIEW_EXECUTOR,
                "submit",
                side_effect=(first, second),
            ):
                view.resize(800, 80)
                view.set_path(first_path)
                view.set_path(second_path)

            self.assertTrue(first.cancelled())
            view.close()

    def test_thumbnail_cancels_previous_lazy_path_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_path, second_path = _audio_paths(Path(temporary))
            first = Future()
            thumbnail = WaveformThumbnail()

            with patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit", return_value=first):
                thumbnail.set_path(first_path)
                thumbnail._ensure_loading()
                thumbnail.set_path(second_path)

            self.assertTrue(first.cancelled())
            thumbnail.close()

    def test_clip_waveform_cancels_previous_audio_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_path, second_path = _audio_paths(Path(temporary))
            first = Future()
            second = Future()
            view = ClipWaveformView()

            with patch(
                "jang_app.qt_app.clip_waveform_view._WAVEFORM_EXECUTOR.submit",
                side_effect=(first, second),
            ):
                view.set_audio(first_path, 2_000, ())
                view.set_audio(second_path, 2_000, ())

            self.assertTrue(first.cancelled())
            view.close()

    def test_studio_timeline_cancels_waveforms_removed_by_session_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, _unused = _audio_paths(Path(temporary))
            asset = StudioSoundAsset(
                StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL),
                "Original Vocal",
                path,
                2_000,
            )
            reference = asset.reference
            session = StudioSession(
                tracks=(
                    StudioTrack(
                        "track-original-vocal",
                        "Original Vocal",
                        TRACK_ORIGINAL_VOCAL,
                        clips=(StudioClip("clip-1", reference, 0, 0, 2_000),),
                    ),
                )
            )
            first = Future()
            timeline = StudioTimelineView()

            with patch(
                "jang_app.qt_app.studio_editor.waveform_cache_key",
                return_value=(str(path), 1, 1, 900),
            ):
                timeline.set_context(session, (asset,))
                with patch.object(_WAVEFORM_EXECUTOR, "submit", return_value=first):
                    timeline._request_waveforms()
                timeline.update_session(StudioSession())

            self.assertTrue(first.cancelled())
            timeline.close()


def _audio_paths(root: Path) -> tuple[Path, Path]:
    first = root / "first.wav"
    second = root / "second.wav"
    samples = np.full(8_000, 0.25, dtype=np.float32)
    sf.write(first, samples, 8_000)
    sf.write(second, samples, 8_000)
    return first, second


if __name__ == "__main__":
    unittest.main()
