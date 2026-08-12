from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.song_assets import (
    REMOVAL_VOCAL_OUTPUT,
    STAGE_EXPORT,
    STAGE_SOURCE,
    STAGE_STUDIO,
    STAGE_VOCAL,
)
from jang_app.services.song_library import SongLibrary
from jang_app.services.song_package import SongPackageStore


class SongAssetDetailsTests(unittest.TestCase):
    def test_catalogs_managed_stage_files_and_active_vocal_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            package = store.require(song.id)

            video = package.folder / "01_source" / "video" / "source.mp4"
            video.write_bytes(b"video")
            output = package.folder / "02_vocal" / "separations" / "run" / "htdemucs" / "source"
            output.mkdir(parents=True)
            (output / "vocals.wav").write_bytes(b"vocals")
            (output / "no_vocals.wav").write_bytes(b"instrumental")
            converted = output / "vocals_rvc_voice.wav"
            converted.write_bytes(b"converted")
            library.register_output(song.id, output, "Run 01")

            studio_file = package.folder / "03_studio" / "session.json"
            studio_file.write_text("{}", encoding="utf-8")
            export_file = package.folder / "04_exports" / "mix.wav"
            export_file.write_bytes(b"mix")

            details = library.asset_details(song.id)

            self.assertEqual(len(details.assets_for(STAGE_SOURCE)), 2)
            self.assertEqual(len(details.assets_for(STAGE_VOCAL)), 3)
            self.assertEqual(len(details.assets_for(STAGE_STUDIO)), 1)
            self.assertEqual(len(details.assets_for(STAGE_EXPORT)), 1)
            studio_asset = details.assets_for(STAGE_STUDIO)[0]
            self.assertEqual(studio_asset.role, "Studio Session")
            self.assertTrue(studio_asset.can_remove)
            active_vocal_paths = {asset.path for asset in details.assets_for(STAGE_VOCAL) if asset.is_active}
            self.assertEqual(
                active_vocal_paths,
                {(output / "vocals.wav").resolve(), (output / "no_vocals.wav").resolve(), converted.resolve()},
            )
            self.assertTrue(all(asset.is_managed for asset in details.assets))

    def test_external_output_assets_are_reported_as_linked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            external = project / "legacy-output"
            external.mkdir()
            (external / "vocals.wav").write_bytes(b"vocals")
            (external / "no_vocals.wav").write_bytes(b"instrumental")
            (external / "vocals_rvc_voice.wav").write_bytes(b"converted")
            library.register_output(song.id, external, "Legacy")

            vocal_assets = library.asset_details(song.id).assets_for(STAGE_VOCAL)

            self.assertEqual(len(vocal_assets), 3)
            self.assertTrue(all(not asset.is_managed for asset in vocal_assets))
            self.assertTrue(all(asset.can_remove for asset in vocal_assets))
            converted = next(asset for asset in vocal_assets if asset.role == "Converted Vocal")
            self.assertEqual(converted.removal_scope, REMOVAL_VOCAL_OUTPUT)


if __name__ == "__main__":
    unittest.main()
