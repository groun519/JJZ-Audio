from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.song_package import SongPackageStore
from jang_app.services.studio_session import (
    StudioSession,
    StudioMasterState,
    StudioTimelineState,
    StudioTrackState,
    load_studio_session,
    save_studio_session,
    studio_session_path,
)


class StudioSessionTests(unittest.TestCase):
    def test_track_mix_state_is_saved_in_song_studio_stage_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")
            session = StudioSession(
                original_vocal=StudioTrackState(muted=True, volume_percent=125),
                instrumental=StudioTrackState(muted=False, volume_percent=80),
                converted_vocal=StudioTrackState(muted=False, volume_percent=175),
                timeline=StudioTimelineState(start_ms=12_000, end_ms=94_000),
                master=StudioMasterState(gain_db=-4, stereo_width_percent=135),
            )

            saved_path = save_studio_session(package, session)
            restored = load_studio_session(package)

            self.assertEqual(saved_path, package.folder / "03_studio" / "session.json")
            self.assertEqual(restored.original_vocal, session.original_vocal)
            self.assertEqual(restored.instrumental, session.instrumental)
            self.assertEqual(restored.converted_vocal, session.converted_vocal)
            self.assertEqual(restored.timeline, session.timeline)
            self.assertEqual(restored.master, session.master)
            self.assertTrue(restored.updated_at)
            self.assertEqual(source.read_bytes(), b"source")

    def test_invalid_or_out_of_range_session_data_uses_safe_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")
            session_path = studio_session_path(package)
            session_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "tracks": {
                            "original_vocal": {"muted": True, "volume_percent": 999},
                            "instrumental": {"muted": "yes", "volume_percent": -50},
                            "converted_vocal": {"volume_percent": "invalid"},
                        },
                        "timeline": {"start_ms": 9000, "end_ms": 4000},
                        "master": {"gain_db": 999, "stereo_width_percent": -20},
                    }
                ),
                encoding="utf-8",
            )

            restored = load_studio_session(package)

            self.assertEqual(restored.original_vocal, StudioTrackState(True, 200))
            self.assertEqual(restored.instrumental, StudioTrackState(False, 0))
            self.assertEqual(restored.converted_vocal, StudioTrackState(False, 100))
            self.assertEqual(restored.timeline, StudioTimelineState())
            self.assertEqual(restored.master, StudioMasterState(gain_db=12, stereo_width_percent=0))

            session_path.write_text("not-json", encoding="utf-8")
            self.assertEqual(load_studio_session(package), StudioSession())


if __name__ == "__main__":
    unittest.main()
