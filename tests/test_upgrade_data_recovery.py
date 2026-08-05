from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.rvc_model_workspace import RvcModelWorkspace
from jang_app.services.song_library import SongLibrary
from jang_app.services.song_package import SongPackageStore


class UpgradeDataRecoveryTests(unittest.TestCase):
    def test_empty_update_workspace_does_not_hide_song_packages_or_linked_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            package_root = source_root / "src" / "jang_app"
            package_root.mkdir(parents=True)
            data_root = root / "data"
            media_root = root / "media"
            workspace = media_root / "workspace"

            source_audio = root / "source.wav"
            source_audio.write_bytes(b"audio")
            song_store = SongPackageStore(workspace / "library" / "songs", media_root)
            imported, _was_added = song_store.import_audio(source_audio, title="Preserved Song")

            external_model = root / "external-model"
            external_model.mkdir()
            inference_model = external_model / "preserved-voice.pth"
            inference_model.write_bytes(b"model")
            model_store = RvcModelWorkspace(workspace / "models")
            linked = model_store.link_folder(external_model)[0]

            settings = data_root / "settings"
            settings.mkdir(parents=True)
            empty_workspace = root / "empty" / "workspace"
            empty_workspace.mkdir(parents=True)
            (settings / "storage.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "workspace_root": str(empty_workspace),
                        "workspace_anchor": str(empty_workspace.parent),
                    }
                ),
                encoding="utf-8",
            )
            (settings / "initial_setup.json").write_text(
                json.dumps({"version": 1, "media_root": str(media_root)}),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package_root,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source_root,
            )
            recovered_songs = SongLibrary(
                settings / "song_library.json",
                SongPackageStore(paths.workspace_root / "library" / "songs", paths.workspace_anchor),
            ).items()
            recovered_models = RvcModelWorkspace(paths.workspace_root / "models").records()

            self.assertEqual(paths.workspace_source, "initial_setup")
            self.assertEqual([item.id for item in recovered_songs], [imported.song_id])
            self.assertEqual([record.model_id for record in recovered_models], [linked.model_id])
            self.assertEqual(recovered_models[0].mode, "linked")
            self.assertEqual(recovered_models[0].inference_model, inference_model.resolve())


if __name__ == "__main__":
    unittest.main()
