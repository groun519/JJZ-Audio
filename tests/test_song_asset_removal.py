from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from jang_app.services.song_asset_removal import SongAssetRemovalError
from jang_app.services.song_assets import STAGE_EXPORT, STAGE_SOURCE, STAGE_STUDIO, STAGE_VOCAL
from jang_app.services.song_library import SongLibrary
from jang_app.services.song_package import SongPackageStore
from jang_app.services.video_source import VideoSourceStore


class SongAssetRemovalTests(unittest.TestCase):
    def test_removes_managed_separation_as_one_output_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library, store, song = _library_with_song(Path(temporary))
            package = store.require(song.id)
            job_dir = package.folder / "02_vocal" / "separations" / "run-1" / "htdemucs" / "source"
            _write_output(job_dir)
            library.register_output(song.id, job_dir, "Run 1")

            vocal = library.asset_details(song.id).assets_for(STAGE_VOCAL)[0]
            result = library.remove_asset(song.id, vocal.path)

            self.assertFalse(job_dir.exists())
            self.assertEqual(store.require(song.id).outputs, ())
            self.assertEqual(result.removed_output_dir, job_dir.resolve())
            self.assertFalse(result.detached_only)

    def test_bulk_removal_deduplicates_assets_from_the_same_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library, store, song = _library_with_song(Path(temporary))
            package = store.require(song.id)
            job_dir = package.folder / "02_vocal" / "separations" / "run-1" / "htdemucs" / "source"
            _write_output(job_dir)
            converted = _write_wave(job_dir / "vocals_rvc_voice.wav")
            extra = job_dir / "notes.txt"
            extra.write_text("metadata", encoding="utf-8")
            library.register_output(song.id, job_dir, "Run 1")
            assets = library.asset_details(song.id).assets_for(STAGE_VOCAL)

            results = library.remove_assets(
                song.id,
                tuple(asset.path for asset in assets),
            )

            self.assertEqual(len(results), 1)
            self.assertFalse(job_dir.exists())
            self.assertFalse(converted.exists())
            self.assertFalse(extra.exists())
            self.assertEqual(store.require(song.id).outputs, ())

    def test_detaches_linked_separation_without_deleting_external_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library, store, song = _library_with_song(root)
            external = root / "external-output"
            _write_output(external)
            library.register_output(song.id, external, "Legacy")

            vocal = library.asset_details(song.id).assets_for(STAGE_VOCAL)[0]
            result = library.remove_asset(song.id, vocal.path)

            self.assertTrue(external.is_dir())
            self.assertTrue((external / "vocals.wav").is_file())
            self.assertEqual(store.require(song.id).outputs, ())
            self.assertTrue(result.detached_only)

    def test_linked_converted_vocal_can_detach_its_result_without_deleting_external_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library, store, song = _library_with_song(root)
            external = root / "external-output"
            _write_output(external)
            converted = _write_wave(external / "vocals_rvc_voice.wav")
            library.register_output(song.id, external, "Legacy")

            converted_asset = next(
                asset
                for asset in library.asset_details(song.id).assets_for(STAGE_VOCAL)
                if asset.path == converted
            )
            result = library.remove_asset(song.id, converted_asset.path)

            self.assertTrue(converted.is_file())
            self.assertTrue((external / "vocals.wav").is_file())
            self.assertEqual(store.require(song.id).outputs, ())
            self.assertTrue(result.detached_only)

    def test_removing_last_recovered_output_hides_the_empty_library_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external = root / "legacy-output"
            _write_output(external)
            store = SongPackageStore(root / "workspace" / "library" / "songs", root)
            library = SongLibrary(root / "missing.json", store)
            package = store.create_output_recovery("Recovered", external, "Legacy")
            vocal = library.asset_details(package.song_id).assets_for(STAGE_VOCAL)[0]

            library.remove_asset(package.song_id, vocal.path)

            self.assertEqual(library.items(), [])
            self.assertTrue(store.require(package.song_id, include_removed=True).removed)
            self.assertTrue((external / "vocals.wav").is_file())

    def test_removes_one_converted_take_and_preserves_other_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library, store, song = _library_with_song(Path(temporary))
            package = store.require(song.id)
            job_dir = package.folder / "02_vocal" / "separations" / "run-1" / "htdemucs" / "source"
            _write_output(job_dir)
            first = _write_wave(job_dir / "vocals_rvc_first.wav")
            second = _write_wave(job_dir / "vocals_rvc_second.wav")
            library.register_output(song.id, job_dir, "Run 1")
            library.activate_converted_output(job_dir, first)

            converted = next(
                asset
                for asset in library.asset_details(song.id).assets_for(STAGE_VOCAL)
                if asset.path == first.resolve()
            )
            library.remove_asset(song.id, converted.path)

            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(store.require(song.id).active_output.active_converted_path, second.resolve())

    def test_removes_video_and_export_but_protects_primary_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library, store, song = _library_with_song(root)
            package = store.require(song.id)
            source_video = root / "video.mp4"
            source_video.write_bytes(b"video")
            video = library.set_video_file(song.id, source_video)
            exported = package.folder / "04_exports" / "mix.wav"
            exported.write_bytes(b"mix")

            details = library.asset_details(song.id)
            source_assets = details.assets_for(STAGE_SOURCE)
            primary = next(asset for asset in source_assets if asset.role == "Source")
            video_asset = next(asset for asset in source_assets if asset.role == "Source Media")
            export_asset = details.assets_for(STAGE_EXPORT)[0]

            self.assertFalse(primary.can_remove)
            with self.assertRaises(SongAssetRemovalError):
                library.remove_asset(song.id, primary.path)
            library.remove_asset(song.id, video_asset.path)
            library.remove_asset(song.id, export_asset.path)

            self.assertFalse(video.path.exists())
            self.assertFalse(exported.exists())
            self.assertFalse(VideoSourceStore().load(package).is_configured)
            self.assertTrue(package.source_path.is_file())

    def test_removes_studio_session_without_touching_song_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library, store, song = _library_with_song(Path(temporary))
            package = store.require(song.id)
            session_path = package.folder / "03_studio" / "session.json"
            session_path.write_text("{}", encoding="utf-8")
            history_path = package.folder / "03_studio" / ".history" / "session-old.json"
            history_path.parent.mkdir(parents=True)
            history_path.write_text("{}", encoding="utf-8")
            studio_asset = library.asset_details(song.id).assets_for(STAGE_STUDIO)[0]

            library.remove_asset(song.id, studio_asset.path)

            self.assertFalse(session_path.exists())
            self.assertFalse(history_path.parent.exists())
            self.assertTrue(package.source_path.is_file())


def _library_with_song(root: Path):
    source = _write_wave(root / "source.wav")
    store = SongPackageStore(root / "workspace" / "library" / "songs", root)
    library = SongLibrary(root / "missing.json", store)
    song = library.add_paths([source])[0]
    return library, store, song


def _write_output(job_dir: Path) -> None:
    _write_wave(job_dir / "vocals.wav")
    _write_wave(job_dir / "no_vocals.wav")


def _write_wave(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16_000)
        stream.writeframes(b"\x00\x00" * 16_000)
    return path.resolve()


if __name__ == "__main__":
    unittest.main()
