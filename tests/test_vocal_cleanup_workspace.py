from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import MainWindow
from jang_app.qt_app.vocal_cleanup_workspace import (
    PLAYBACK_ORIGINAL,
    PLAYBACK_PROCESSED,
    VocalCleanupWorkspace,
)
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_cleanup import (
    VOCAL_CLEANUP_EFFECT_DENOISE,
    VOCAL_CLEANUP_EFFECTS,
    VocalCleanupProject,
    VocalCleanupRegion,
    VocalCleanupResult,
)
from jang_app.services.vocal_cleanup_store import VocalCleanupStore


class VocalCleanupWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_workspace_loads_regions_results_and_preview_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "vocals.wav"
            processed = root / "processed.wav"
            removed = root / "removed.wav"
            result_path = root / "clean.wav"
            for path in (source, processed, removed, result_path):
                _write_wav(path)
            version = _version(root, source)
            project = VocalCleanupProject(
                source,
                "fingerprint",
                regions=(
                    VocalCleanupRegion(
                        "region-1",
                        250,
                        900,
                        "dereverb",
                        "standard",
                        processed,
                        removed,
                        "2026-08-20T00:00:00+00:00",
                    ),
                ),
                results=(
                    VocalCleanupResult(
                        "result-1",
                        "Clean vocal 1",
                        result_path,
                        "2026-08-20T00:00:00+00:00",
                    ),
                ),
            )
            workspace = VocalCleanupWorkspace()
            workspace.set_versions((version,), version.job_dir)
            workspace.set_project(project)
            requests: list[tuple[object, int, int, str, str]] = []
            workspace.preview_requested.connect(
                lambda *values: requests.append(values)
            )

            workspace._on_selection_changed(1_000, 1_750)
            workspace.preview_action.button.click()

            self.assertEqual(len(workspace.region_lane._regions), 1)
            self.assertEqual(workspace.result_pool.count_label.text(), "1")
            self.assertEqual(workspace._playback_mode, PLAYBACK_PROCESSED)
            self.assertEqual(
                requests,
                [(version, 1_000, 1_750, "dereverb", "standard")],
            )
            workspace.close()

    def test_all_workspace_surfaces_are_parented_before_show(self) -> None:
        workspace = VocalCleanupWorkspace()
        workspace.resize(1400, 800)
        workspace.show()
        self.app.processEvents()

        for child in (
            workspace.source_panel,
            workspace.timeline_panel,
            workspace.inspector_panel,
            workspace.render_bar,
            workspace.transport_bar,
        ):
            self.assertIs(child.window(), workspace)

        workspace.close()

    def test_tool_change_discards_preview_and_requests_selected_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "vocals.wav"
            processed = root / "processed.wav"
            removed = root / "removed.wav"
            for path in (source, processed, removed):
                _write_wav(path)
            version = _version(root, source)
            workspace = VocalCleanupWorkspace()
            workspace.set_versions((version,), version.job_dir)
            workspace.set_project(VocalCleanupProject(source, "fingerprint"))
            workspace._on_selection_changed(300, 1_100)
            workspace.set_preview_paths(processed, removed)
            requests: list[tuple[object, int, int, str, str]] = []
            invalidations: list[bool] = []
            workspace.preview_requested.connect(lambda *values: requests.append(values))
            workspace.preview_invalidated.connect(lambda: invalidations.append(True))

            workspace.tool_buttons[VOCAL_CLEANUP_EFFECT_DENOISE].click()
            workspace.preview_action.button.click()

            self.assertEqual(
                workspace.tool_detail_stack.currentIndex(),
                VOCAL_CLEANUP_EFFECTS.index(VOCAL_CLEANUP_EFFECT_DENOISE),
            )
            self.assertFalse(workspace.preview_action.preview_available())
            self.assertEqual(workspace._playback_mode, PLAYBACK_ORIGINAL)
            self.assertEqual(len(invalidations), 1)
            self.assertEqual(
                requests,
                [(version, 300, 1_100, VOCAL_CLEANUP_EFFECT_DENOISE, "standard")],
            )
            workspace.close()

    def test_preview_actions_offer_retry_cancel_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "vocals.wav"
            processed = root / "processed.wav"
            removed = root / "removed.wav"
            for path in (source, processed, removed):
                _write_wav(path)
            workspace = VocalCleanupWorkspace()
            workspace.set_project(VocalCleanupProject(source, "fingerprint"))
            cancelled: list[bool] = []
            committed: list[bool] = []
            workspace.cancel_preview_requested.connect(lambda: cancelled.append(True))
            workspace.commit_preview_requested.connect(lambda: committed.append(True))

            workspace.set_preview_paths(processed, removed)
            workspace.preview_action.cancel_button.click()
            workspace.preview_action.commit_button.click()

            self.assertTrue(workspace.preview_action.preview_available())
            self.assertTrue(workspace.preview_action.cancel_button.isVisibleTo(workspace))
            self.assertEqual(cancelled, [True])
            self.assertEqual(committed, [True])
            workspace.clear_pending_preview()
            self.assertFalse(workspace.preview_action.preview_available())
            self.assertEqual(workspace._playback_mode, PLAYBACK_ORIGINAL)
            workspace.close()

    def test_rendered_cleanup_result_is_offered_as_conversion_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "vocals.wav"
            _write_wav(source)
            version = _version(root, source)
            store = VocalCleanupStore()
            project = store.load(root, source)
            result_path = store.create_result_path(root)
            _write_wav(result_path)
            store.register_result(root, project, result_path)
            window = type(
                "WindowStub",
                (),
                {"vocal_cleanup_store": store},
            )()

            choices = MainWindow._conversion_input_choices(window, (version,))

            self.assertEqual([choice.kind for choice in choices], ["original", "cleanup"])
            self.assertEqual(choices[1].path, result_path.resolve())


def _version(root: Path, source: Path) -> SongVocalVersion:
    return SongVocalVersion(
        version_id="precision",
        label="Precision Separation",
        job_dir=root,
        added_at="2026-08-20T00:00:00+00:00",
        vocals_path=source,
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=(),
        separation_recipe_label="Precision Separation",
    )


def _write_wav(path: Path, *, seconds: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\x00\x00" * 8_000 * seconds)
