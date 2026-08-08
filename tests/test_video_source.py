from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.song_assets import STAGE_SOURCE
from jang_app.services.song_library import SongLibrary
from jang_app.services.song_package import SongPackageStore
from jang_app.services.video_source import (
    VIDEO_KIND_FILE,
    VIDEO_KIND_YOUTUBE,
    VideoSource,
    VideoSourceStore,
)
from jang_app.services.youtube_video_download import YouTubeVideoDownloadResult


class VideoSourceStoreTests(unittest.TestCase):
    def test_imports_video_into_song_package_and_restores_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package(root)
            source = root / "incoming" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video source")
            original = source.read_bytes()
            progress = []
            store = VideoSourceStore()

            imported = store.import_file(package, source, progress.append)
            loaded = store.load(package)

            self.assertEqual(imported.kind, VIDEO_KIND_FILE)
            self.assertEqual(loaded, imported)
            self.assertEqual(imported.path.read_bytes(), original)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(imported.path.parent, package.folder / "01_source" / "video")
            self.assertEqual(progress[-1], 100)

    def test_explicit_url_overrides_inherited_youtube_source_and_clear_restores_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package(
                root,
                source_type="youtube",
                source_url="https://www.youtube.com/watch?v=source",
            )
            store = VideoSourceStore()

            inherited = store.resolve(package)
            explicit = store.set_url(package, "https://youtu.be/replacement")
            store.clear(package)

            self.assertEqual(inherited.kind, VIDEO_KIND_YOUTUBE)
            self.assertTrue(inherited.inherited)
            self.assertEqual(store.load(package), VideoSource())
            self.assertEqual(explicit.url, "https://youtu.be/replacement")
            self.assertEqual(store.resolve(package).url, inherited.url)

    def test_rejects_unsupported_file_and_invalid_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package(root)
            unsupported = root / "clip.txt"
            unsupported.write_text("not video", encoding="utf-8")
            store = VideoSourceStore()

            with self.assertRaises(ValueError):
                store.import_file(package, unsupported)
            with self.assertRaises(ValueError):
                store.set_url(package, "not-a-url")

    def test_materializes_youtube_source_and_persists_managed_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package(
                root,
                source_type="youtube",
                source_url="https://youtube.com/watch?v=source",
            )
            downloaded = package.folder / "01_source" / "video" / "downloaded.mp4"
            downloaded.parent.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"video")
            progress = []
            store = VideoSourceStore()

            with patch(
                "jang_app.services.video_source.download_youtube_video",
                return_value=YouTubeVideoDownloadResult(
                    package.source_url,
                    "Downloaded Video",
                    downloaded,
                ),
            ):
                materialized = store.materialize(package, progress.append)

            self.assertEqual(materialized.path, downloaded)
            self.assertEqual(store.load(package), materialized)
            self.assertEqual(materialized.url, package.source_url)

    def test_reuses_a_previous_managed_video_without_copying_it_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package(root)
            source = root / "first.mp4"
            source.write_bytes(b"first video")
            store = VideoSourceStore()

            imported = store.import_file(package, source)
            store.set_url(package, "https://youtu.be/replacement")

            available = store.managed_sources(package)
            selected = store.select_managed(package, imported.path)

            self.assertEqual([item.path for item in available], [imported.path])
            self.assertEqual(selected.path, imported.path)
            self.assertEqual(selected.path.read_bytes(), b"first video")
            self.assertEqual(store.load(package), selected)

    def test_rejects_selecting_a_video_outside_the_song_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package(root)
            outside = root / "outside.mp4"
            outside.write_bytes(b"video")

            with self.assertRaises(ValueError):
                VideoSourceStore().select_managed(package, outside)

    def test_song_library_catalogs_the_active_managed_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "source.wav"
            audio.write_bytes(b"audio")
            video = root / "source.mp4"
            video.write_bytes(b"video")
            package_store = SongPackageStore(root / "workspace" / "library" / "songs", root)
            library = SongLibrary(root / "missing.json", package_store)
            song = library.add_paths([audio])[0]

            attached = library.set_video_file(song.id, video)
            source_assets = library.asset_details(song.id).assets_for(STAGE_SOURCE)

            self.assertEqual(library.video_source(song.id), attached)
            video_assets = [asset for asset in source_assets if asset.role == "Source Video"]
            self.assertEqual([asset.path for asset in video_assets], [attached.path])
            self.assertTrue(video_assets[0].is_active)


def _package(root: Path, *, source_type: str = "local", source_url: str = ""):
    audio = root / "source.wav"
    audio.write_bytes(b"audio")
    store = SongPackageStore(root / "workspace" / "library" / "songs", root)
    package, _created = store.import_audio(
        audio,
        title="Song",
        source_type=source_type,
        source_url=source_url,
    )
    return package


if __name__ == "__main__":
    unittest.main()
