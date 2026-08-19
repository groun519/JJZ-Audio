from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.timeline_range_clip import TimelineRangeLane
from jang_app.qt_app.vocal_split_timeline import VocalSplitTimelinePanel
from jang_app.qt_app.vocal_split_workspace import VocalSplitWorkspace
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_split import (
    VocalReferenceRegion,
    VocalSplitRun,
    VocalSplitStem,
)


class VocalSplitWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_left_panel_only_creates_a_group_from_the_selected_source(self) -> None:
        workspace = VocalSplitWorkspace()
        version = _version()
        workspace.set_versions((version,), version.job_dir)
        requested: list[SongVocalVersion] = []
        workspace.create_group_requested.connect(requested.append)

        workspace.create_group_button.click()

        self.assertEqual(requested, [version])
        self.assertTrue(workspace.method_panel.isAncestorOf(workspace.source_selector))
        self.assertTrue(workspace.method_panel.isAncestorOf(workspace.create_group_button))
        self.assertFalse(workspace.method_panel.isAncestorOf(workspace.action))
        self.assertFalse(hasattr(workspace, "recursive_input_card"))
        workspace.close()

    def test_new_group_starts_with_one_original_vocal(self) -> None:
        workspace = VocalSplitWorkspace()
        version = _version()
        workspace.set_versions((version,), version.job_dir)
        group = _run(version, "group-1", 1)

        selected = workspace.set_groups((group,), preferred_group_id=group.run_id)

        self.assertEqual(selected, group.stems[0])
        self.assertEqual(workspace.selected_group(), group)
        self.assertEqual(workspace.selected_stem(), group.stems[0])
        self.assertEqual(workspace.result_timeline.count_label.text(), "1")
        workspace.close()

    def test_timeline_accepts_a_variable_number_of_active_vocals(self) -> None:
        workspace = VocalSplitWorkspace()
        workspace.resize(1400, 800)
        version = _version()
        workspace.set_versions((version,), version.job_dir)
        group = _run(version, "group-1", 4)

        workspace.set_groups((group,))
        workspace.show()
        self.app.processEvents()

        self.assertEqual(len(workspace.result_timeline._track_rows), 4)
        self.assertEqual(workspace.result_timeline.count_label.text(), "4")
        self.assertTrue(
            all(row.isVisible() for row in workspace.result_timeline._track_rows.values())
        )
        workspace.close()

    def test_group_list_selects_one_group_for_the_timeline(self) -> None:
        workspace = VocalSplitWorkspace()
        version = _version()
        workspace.set_versions((version,), version.job_dir)
        newest = _run(version, "group-new", 2, created_at="2026-08-18T01:00:00+00:00")
        older = _run(version, "group-old", 3, created_at="2026-08-17T01:00:00+00:00")

        workspace.set_groups((newest, older))
        workspace.group_list._rows[older.run_id].activated.emit(older)
        self.app.processEvents()

        self.assertEqual(workspace.result_timeline.selected_group(), older)
        self.assertEqual(len(workspace.result_timeline._track_rows), 3)
        workspace.close()

    def test_changing_source_clears_previous_groups(self) -> None:
        workspace = VocalSplitWorkspace()
        first = _version(Path("first"), version_id="first")
        second = _version(Path("second"), version_id="second")
        workspace.set_versions((first, second), first.job_dir)
        workspace.set_groups((_run(first, "group-first", 1),))

        second_key = str(second.job_dir.expanduser().resolve())
        workspace.source_selector.cards[second_key].activated.emit(second_key)
        self.app.processEvents()

        self.assertIsNone(workspace.selected_group())
        self.assertIsNone(workspace.result_timeline.selected_group())
        self.assertEqual(workspace.group_list.count_label.text(), "0")
        workspace.close()

    def test_selected_vocal_owns_multiple_solo_reference_regions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = _version(root)
            group = _run(version, "group-1", 2, root=root)
            panel = VocalSplitTimelinePanel()
            panel.set_backend_status(True, "Model ready", minimum_reference_ms=500)
            panel.set_group(group)
            first, second = group.stems

            panel._add_reference_region(group, first, 7_000, 12_000)
            panel._add_reference_region(group, first, 18_000, 24_000)
            self.assertEqual(
                [(region.start_ms, region.end_ms) for region in panel.reference_regions()],
                [(7_000, 12_000), (18_000, 24_000)],
            )
            self.assertTrue(panel.action.button.isEnabled())

            panel._select_stem(group, second)
            self.assertEqual(panel.reference_regions(), ())
            self.assertFalse(panel.action.button.isEnabled())

            panel._select_stem(group, first)
            self.assertEqual(len(panel.reference_regions()), 2)
            panel.close()

    def test_editor_lane_moves_above_selected_row_without_rebuilding_tracks(self) -> None:
        panel = VocalSplitTimelinePanel()
        version = _version()
        group = _run(version, "group-1", 3)
        panel.set_group(group)
        rows_before = dict(panel._track_rows)
        target = group.stems[2]

        panel._select_stem(group, target)

        target_row = panel._track_rows[target.path.expanduser().resolve()]
        self.assertEqual(
            panel.track_layout.indexOf(panel.inline_editor) + 1,
            panel.track_layout.indexOf(target_row),
        )
        self.assertEqual(panel._track_rows, rows_before)
        self.assertTrue(panel.track_content.isAncestorOf(panel.inline_editor))
        panel.close()

    def test_reference_lane_updates_and_removes_only_the_selected_region(self) -> None:
        panel = VocalSplitTimelinePanel()
        version = _version()
        group = _run(version, "group-1", 2)
        panel.set_group(group)
        target = group.stems[1]
        panel._select_stem(group, target)
        panel._add_reference_region(group, target, 26_000, 34_000)
        panel._add_reference_region(group, target, 36_000, 44_000)
        first, second = panel.reference_regions()

        panel._update_reference_region(first.region_id, 25_000, 35_000)
        panel._remove_reference_region(second.region_id)

        self.assertEqual(len(panel.reference_regions()), 1)
        self.assertEqual(
            (panel.reference_regions()[0].start_ms, panel.reference_regions()[0].end_ms),
            (25_000, 35_000),
        )
        panel.close()

    def test_top_reference_clip_requests_removal_from_its_close_control(self) -> None:
        lane = TimelineRangeLane()
        lane.resize(800, 46)
        region = VocalReferenceRegion("solo-1", 10_000, 20_000)
        lane.set_duration_ms(40_000)
        lane.set_regions((region,), region.region_id)
        lane.show()
        self.app.processEvents()
        rect = lane._region_rect(region)
        removed: list[str] = []
        lane.region_remove_requested.connect(removed.append)

        QTest.mouseClick(
            lane,
            Qt.MouseButton.LeftButton,
            pos=lane._close_rect(rect).center().toPoint(),
        )

        self.assertEqual(removed, ["solo-1"])
        lane.close()

    def test_waveform_creates_and_trims_a_reference_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = _version(root)
            group = _run(version, "group-1", 1, root=root)
            panel = VocalSplitTimelinePanel()
            panel.resize(900, 420)
            panel.set_group(group)
            panel.show()
            self.app.processEvents()
            panel.reference_mode_button.click()
            waveform = next(iter(panel._track_rows.values())).waveform
            content = waveform.rect().adjusted(19, 15, -19, -15)
            start = QPoint(content.left() + content.width() // 4, content.center().y())
            end = QPoint(content.left() + content.width() // 2, content.center().y())

            QTest.mousePress(waveform, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(waveform, end, delay=10)
            QTest.mouseRelease(waveform, Qt.MouseButton.LeftButton, pos=end)

            self.assertEqual(len(panel.reference_regions()), 1)
            region = panel.reference_regions()[0]
            self.assertGreater(region.end_ms, region.start_ms)
            panel.reference_mode_button.click()
            self.app.processEvents()
            region_rect = waveform._region_rect(region)
            target_x = round(
                waveform._content_rect().left()
                + waveform._content_rect().width() * 0.75
            )
            QTest.mousePress(
                waveform,
                Qt.MouseButton.LeftButton,
                pos=QPoint(round(region_rect.right()), round(region_rect.center().y())),
            )
            QTest.mouseMove(
                waveform,
                QPoint(target_x, round(region_rect.center().y())),
                delay=10,
            )
            QTest.mouseRelease(
                waveform,
                Qt.MouseButton.LeftButton,
                pos=QPoint(target_x, round(region_rect.center().y())),
            )

            trimmed = panel.reference_regions()[0]
            self.assertEqual(trimmed.start_ms, region.start_ms)
            self.assertGreater(trimmed.end_ms, region.end_ms)
            panel.close()

    def test_group_delete_action_requests_the_whole_group(self) -> None:
        workspace = VocalSplitWorkspace()
        version = _version()
        group = _run(version, "group-1", 2)
        workspace.set_versions((version,), version.job_dir)
        workspace.set_groups((group,))
        requested: list[VocalSplitRun] = []
        workspace.remove_run_requested.connect(requested.append)

        workspace.group_list._rows[group.run_id].remove_button.click()

        self.assertEqual(requested, [group])
        workspace.close()

    def test_muting_one_timeline_track_keeps_other_track_audible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = _version(root)
            group = _run(version, "group-1", 2, root=root)
            panel = VocalSplitTimelinePanel()
            panel.set_group(group)
            first_path = group.stems[0].path.resolve()

            panel._track_rows[first_path].mute_button.click()

            tracks = panel.playback_tracks()
            self.assertEqual(tracks[0], (group.stems[0].path, 0.0))
            self.assertEqual(tracks[1], (group.stems[1].path, 1.0))
            panel.close()


def _version(
    root: Path = Path("."),
    *,
    version_id: str = "output-1",
) -> SongVocalVersion:
    return SongVocalVersion(
        version_id=version_id,
        label="Precision",
        job_dir=root / "run-1",
        added_at="2026-08-18T00:00:00+00:00",
        vocals_path=root / "vocals.wav",
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=(),
        separation_recipe_label="Precision Separation",
    )


def _run(
    version: SongVocalVersion,
    run_id: str,
    stem_count: int,
    *,
    root: Path | None = None,
    created_at: str = "2026-08-18T00:00:00+00:00",
) -> VocalSplitRun:
    stems: list[VocalSplitStem] = []
    for index in range(1, stem_count + 1):
        path = root / f"vocal-{index}.wav" if root is not None else Path(f"vocal-{index}.wav")
        if root is not None:
            _write_wave(path, 180 + index * 40)
        stems.append(
            VocalSplitStem(
                f"vocal-{index}",
                "vocal",
                "Original vocal" if stem_count == 1 else f"Vocal {index}",
                path,
                origin="root" if stem_count == 1 else "extracted",
            )
        )
    return VocalSplitRun(
        run_id,
        version.job_dir,
        version.vocals_path,
        "vocal-group-v2",
        "Vocal group",
        "",
        created_at,
        tuple(stems),
        tuple(stems),
        (),
    )


def _write_wave(path: Path, frequency: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(8_000 * math.sin(2 * math.pi * frequency * index / 8_000)),
                )
                for index in range(8_000)
            )
        )


if __name__ == "__main__":
    unittest.main()
