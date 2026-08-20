from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from jang_app.services.song_package import SongPackageStore
from jang_app.services.studio_project import (
    StudioProjectViewState,
    commit_studio_project_session,
    consume_studio_project_recovery_notice,
    ensure_studio_project,
    load_studio_project_view_state,
    recover_studio_project_session,
    remove_studio_project,
    restore_studio_project_revision,
    save_studio_project_assets,
    save_studio_project_view_state,
    studio_project_paths,
    studio_project_recovery_notice,
    studio_project_missing_asset_ids,
    studio_project_revisions,
)


class StudioProjectTests(unittest.TestCase):
    def test_legacy_session_is_migrated_once_and_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            paths = studio_project_paths(package)
            payload = _session_payload(package.song_id, "legacy")
            paths.legacy_session.parent.mkdir(parents=True, exist_ok=True)
            paths.legacy_session.write_text(json.dumps(payload), encoding="utf-8")

            migrated = ensure_studio_project(package)
            ensure_studio_project(package)

            self.assertEqual(json.loads(migrated.session.read_text(encoding="utf-8")), payload)
            self.assertEqual(
                json.loads((migrated.legacy_backup / "session.json").read_text(encoding="utf-8")),
                payload,
            )
            metadata = json.loads(migrated.metadata.read_text(encoding="utf-8"))
            self.assertTrue(metadata["migrated_from_legacy"])
            index = json.loads(migrated.index.read_text(encoding="utf-8"))
            self.assertEqual(index["projects"][0]["revision"], 1)
            self.assertEqual(
                [revision.revision for revision in studio_project_revisions(package)],
                [1],
            )

    def test_commits_are_revisioned_and_an_old_revision_can_be_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            first = _session_payload(package.song_id, "first")
            second = _session_payload(package.song_id, "second")

            commit_studio_project_session(package, first)
            commit_studio_project_session(package, second)
            revisions = studio_project_revisions(package)
            restore_studio_project_revision(package, 1)

            self.assertEqual([item.revision for item in revisions], [2, 1])
            self.assertEqual(revisions[0].clip_count, 1)
            current = json.loads(studio_project_paths(package).session.read_text(encoding="utf-8"))
            self.assertEqual(current["tracks"][0]["name"], "first")
            self.assertEqual(studio_project_revisions(package)[0].revision, 3)

    def test_invalid_current_session_recovers_latest_valid_journal_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            payload = _session_payload(package.song_id, "latest")
            commit_studio_project_session(package, payload)
            paths = studio_project_paths(package)
            with paths.journal.open("a", encoding="utf-8") as stream:
                stream.write("{partial")

            recovered, notice = recover_studio_project_session(package, None)

            self.assertEqual(recovered, payload)
            self.assertTrue(notice.recovered)
            self.assertTrue(studio_project_recovery_notice(package).recovered)
            self.assertTrue(consume_studio_project_recovery_notice(package).recovered)
            self.assertFalse(studio_project_recovery_notice(package).recovered)

    def test_checkpoint_recovers_when_journal_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            payload = _session_payload(package.song_id, "checkpoint")
            with patch("jang_app.services.studio_project.STUDIO_PROJECT_CHECKPOINT_INTERVAL", 1):
                commit_studio_project_session(package, payload)
            paths = studio_project_paths(package)
            paths.journal.unlink()

            recovered, notice = recover_studio_project_session(package, None)

            self.assertEqual(recovered, payload)
            self.assertTrue(notice.recovered)

    def test_valid_modified_session_is_not_replaced_only_for_checksum_difference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            committed = _session_payload(package.song_id, "committed")
            modified = _session_payload(package.song_id, "manual migration")
            commit_studio_project_session(package, committed)

            recovered, notice = recover_studio_project_session(package, modified)

            self.assertEqual(recovered, modified)
            self.assertFalse(notice.recovered)

    def test_view_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            state = StudioProjectViewState(12_345, 210, 36, 18, "clip-a", "track-a")

            save_studio_project_view_state(package, state)

            self.assertEqual(load_studio_project_view_state(package), state)

    def test_view_state_round_trips_multi_selection_and_reads_legacy_primary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            state = StudioProjectViewState(
                selected_clip_id="clip-b",
                selected_clip_ids=("clip-a", "clip-b"),
            )
            save_studio_project_view_state(package, state)

            self.assertEqual(load_studio_project_view_state(package), state)

            path = studio_project_paths(package).view_state
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.pop("selected_clip_ids")
            path.write_text(json.dumps(payload), encoding="utf-8")

            legacy = load_studio_project_view_state(package)
            self.assertEqual(legacy.selected_clip_ids, ("clip-b",))

    def test_missing_session_assets_remain_registered_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            payload = _session_payload(package.song_id, "missing")
            clip = payload["tracks"][0]["clips"][0]
            clip["asset"] = {
                "output_id": "output-a",
                "role": "audio",
                "filename": "source.wav",
            }

            save_studio_project_assets(package, (), payload)

            self.assertEqual(
                studio_project_missing_asset_ids(package),
                ("output-a:audio:source.wav",),
            )

    def test_removing_project_preserves_song_media(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package(Path(temporary))
            commit_studio_project_session(package, _session_payload(package.song_id, "saved"))
            paths = studio_project_paths(package)

            remove_studio_project(package)

            self.assertFalse(paths.root.exists())
            self.assertFalse(paths.index.exists())
            self.assertTrue(package.source_path.is_file())


def _package(root: Path):
    source = root / "source.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8_000)
        stream.writeframes(b"\x00\x00" * 800)
    store = SongPackageStore(root / "workspace" / "library" / "songs", root)
    package, _created = store.import_audio(source, title="Song")
    return package


def _session_payload(song_id: str, name: str) -> dict[str, object]:
    return {
        "version": 11,
        "song_id": song_id,
        "updated_at": "2026-08-20T00:00:00+00:00",
        "tracks": [
            {
                "track_id": "track-a",
                "name": name,
                "clips": [{"clip_id": "clip-a"}],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
