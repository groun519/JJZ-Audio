from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_inspector import StudioInspector
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import COMPACT_ICON_BUTTON_SIZE, TimecodeSpinBox
from jang_app.services.i18n import tr
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    MEDIA_FILL,
    TRACK_CONVERTED_VOCAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioEffect,
    StudioMediaSettings,
    StudioTrack,
)


class StudioInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_timecode_editor_formats_and_parses_milliseconds(self) -> None:
        spin = TimecodeSpinBox()

        self.assertEqual(spin.textFromValue(72_345), "01:12.345")
        self.assertEqual(spin.textFromValue(3_672_345), "01:01:12.345")
        self.assertEqual(spin.valueFromText("01:12.345"), 72_345)
        self.assertEqual(spin.valueFromText("1:01:12.345"), 3_672_345)
        spin.lineEdit().setText("01:12.345")
        self.assertTrue(spin.lineEdit().hasAcceptableInput())
        spin.interpretText()
        self.assertEqual(spin.value(), 72_345)

    def test_context_switches_between_empty_clip_and_track_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "vocals.wav"
            sf.write(path, np.ones(16_000, dtype=np.float32), 8_000)
            reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
            asset = StudioSoundAsset(reference, "Maximum / Original Vocal", path, 2_000)
            clip = StudioClip(
                "clip-1",
                reference,
                500,
                0,
                2_000,
                gain_db=-2.5,
                fade_in_ms=100,
                fade_out_ms=200,
            )
            track = StudioTrack(
                "track-original-vocal",
                "Original Vocal",
                TRACK_ORIGINAL_VOCAL,
                pan_percent=-20,
                clips=(clip,),
            )
            inspector = StudioInspector()
            changed = QSignalSpy(inspector.clip_values_changed)

            inspector.set_selection(track, clip, asset)
            self.assertEqual(inspector.stack.currentIndex(), inspector.CLIP_PAGE)
            self.assertEqual(inspector.duration_value.text(), "00:02.000")
            self.assertEqual(inspector.gain_spin.value(), -2.5)
            self.assertEqual(inspector.gain_spin.minimum(), -100.0)
            self.assertEqual(inspector.gain_spin.maximum(), 30.0)
            self.assertEqual(inspector.gain_slider.minimum(), -1_000)
            self.assertEqual(inspector.gain_slider.maximum(), 300)
            self.assertEqual(inspector.gain_spin.width(), 112)
            inspector.setStyleSheet(build_stylesheet("dark"))
            inspector.resize(300, 720)
            inspector.show()
            self.app.processEvents()
            self.assertEqual(inspector.gain_spin.width(), 112)
            self.assertGreaterEqual(inspector.gain_slider.width(), 100)
            self.assertEqual(inspector.clip_mute_button.text(), "")
            self.assertFalse(hasattr(inspector, "remove_button"))
            self.assertEqual(inspector.clip_mute_button.icon_name(), "speaker")
            self.assertEqual(
                inspector.clip_mute_button.size().toTuple(),
                (COMPACT_ICON_BUTTON_SIZE, COMPACT_ICON_BUTTON_SIZE),
            )
            self.assertGreaterEqual(
                inspector.clip_section.header_layout.indexOf(inspector.clip_mute_button),
                0,
            )
            inspector.fade_in_spin.setValue(150)
            inspector._emit_clip_values()
            self.assertEqual(changed.count(), 1)
            self.assertEqual(changed.at(0)[6], 150)

            inspector.clip_mute_button.click()
            self.assertEqual(changed.count(), 2)
            self.assertTrue(changed.at(1)[5])
            self.assertEqual(inspector.clip_mute_button.toolTip(), tr("Unmute Clip"))

            inspector.set_selection(track, None, None)
            self.assertEqual(inspector.stack.currentIndex(), inspector.TRACK_PAGE)
            self.assertEqual(inspector.pan_slider.value(), -20)

            inspector.clear_selection()
            self.assertEqual(inspector.stack.currentIndex(), inspector.EMPTY_PAGE)
            inspector.close()

    def test_clip_effects_add_reverb_tabs_and_forward_changes(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effect = StudioEffect("fx-reverb", "reverb")
        clip = StudioClip("clip-1", reference, 0, 0, 2_000, effects=(effect,))
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(clip,),
        )
        inspector = StudioInspector()
        changed = QSignalSpy(inspector.effect_changed)
        removed = QSignalSpy(inspector.effect_remove_requested)

        inspector.set_selection(track, clip, None)

        self.assertEqual(inspector.effect_tab_ids(), (effect.effect_id,))
        inspector.open_effect_tab(effect.effect_id)
        self.assertEqual(inspector.clip_detail_stack.currentIndex(), 1)
        editor = inspector.effect_editors[effect.effect_id]
        editor.controls["dry_wet_percent"].setValue(44)
        editor._emit_changed()
        editor.remove_button.click()

        self.assertEqual(changed.at(0)[0], clip.clip_id)
        self.assertEqual(changed.at(0)[1].reverb.dry_wet_percent, 44)
        self.assertEqual(tuple(removed.at(0)), (clip.clip_id, effect.effect_id))
        inspector.close()

    def test_character_effects_use_the_shared_inspector_editor(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effects = (
            StudioEffect("fx-radio", "radio_filter"),
            StudioEffect("fx-ring", "ring_modulator"),
            StudioEffect("fx-bits", "bitcrusher"),
            StudioEffect("fx-drive", "distortion"),
            StudioEffect("fx-level", "level_match"),
        )
        clip = StudioClip("clip-1", reference, 0, 0, 2_000, effects=effects)
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(clip,),
        )
        inspector = StudioInspector()

        inspector.set_selection(track, clip, None)

        self.assertEqual(inspector.effect_tab_ids(), tuple(effect.effect_id for effect in effects))
        self.assertEqual(
            {editor.effect_kind for editor in inspector.effect_editors.values()},
            {"radio_filter", "ring_modulator", "bitcrusher", "distortion", "level_match"},
        )
        level_editor = inspector.effect_editors["fx-level"]
        self.assertFalse(level_editor.reference_status.property("available"))

        converted_reference = StudioAssetRef("output-1", TRACK_CONVERTED_VOCAL, "rvc.wav")
        converted_clip = replace(clip, asset=converted_reference)
        converted_track = replace(track, role=TRACK_CONVERTED_VOCAL, clips=(converted_clip,))
        inspector.set_selection(converted_track, converted_clip, None)
        self.assertTrue(level_editor.reference_status.property("available"))
        inspector.close()

    def test_media_clip_controls_follow_image_and_video_capabilities(self) -> None:
        image_reference = StudioAssetRef("image", TRACK_VIDEO, "cover.png")
        image_asset = StudioSoundAsset(
            image_reference,
            "Cover",
            Path("cover.png"),
            30_000,
            media_kind="image",
        )
        image_clip = StudioClip(
            "image-clip",
            image_reference,
            0,
            0,
            5_000,
            media=StudioMediaSettings(fit_mode=MEDIA_FILL, scale_percent=125),
        )
        track = StudioTrack("media-track", "Media", TRACK_VIDEO, clips=(image_clip,))
        inspector = StudioInspector()
        changed = QSignalSpy(inspector.media_values_changed)

        inspector.set_selection(track, image_clip, image_asset)

        self.assertTrue(inspector.media_section.isVisibleTo(inspector))
        self.assertTrue(inspector.image_controls.isVisibleTo(inspector))
        self.assertFalse(inspector.source_audio_button.isVisibleTo(inspector))
        self.assertFalse(inspector.source_section.isVisibleTo(inspector))
        self.assertTrue(inspector.fit_buttons[MEDIA_FILL].isChecked())
        inspector.image_duration_spin.setValue(7_500)
        inspector.scale_spin.setValue(140)
        inspector._emit_media_values()
        self.assertEqual(changed.at(0)[1], 7_500)
        self.assertEqual(changed.at(0)[2].scale_percent, 140)

        video_reference = StudioAssetRef("video", TRACK_VIDEO, "source.mp4")
        video_asset = StudioSoundAsset(
            video_reference,
            "Source",
            Path("source.mp4"),
            30_000,
            media_kind="video",
        )
        video_clip = StudioClip("video-clip", video_reference, 0, 2_000, 8_000)
        inspector.set_selection(
            StudioTrack("media-track", "Media", TRACK_VIDEO, clips=(video_clip,)),
            video_clip,
            video_asset,
        )

        self.assertFalse(inspector.image_controls.isVisibleTo(inspector))
        self.assertTrue(inspector.source_audio_button.isVisibleTo(inspector))
        self.assertTrue(inspector.source_section.isVisibleTo(inspector))
        self.assertTrue(inspector.source_section.content.isVisibleTo(inspector))
        inspector.source_audio_button.click()
        self.assertTrue(changed.at(changed.count() - 1)[2].source_audio_enabled)
        inspector.close()

    def test_selecting_another_clip_resets_the_active_effect_tab(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effect = StudioEffect("fx-reverb", "reverb")
        first_clip = StudioClip("clip-1", reference, 0, 0, 1_000, effects=(effect,))
        second_clip = StudioClip("clip-2", reference, 1_000, 1_000, 2_000, effects=(effect,))
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(first_clip, second_clip),
        )
        inspector = StudioInspector()

        inspector.set_selection(track, first_clip, None)
        inspector.open_effect_tab(effect.effect_id)
        self.assertEqual(inspector.clip_detail_stack.currentIndex(), 1)

        inspector.set_selection(track, second_clip, None)

        self.assertEqual(inspector.clip_detail_stack.currentIndex(), 0)
        self.assertTrue(inspector.clip_tab_button.isChecked())
        inspector.close()

    def test_repeated_effect_refresh_reuses_the_existing_tab_and_editor(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effect = StudioEffect("fx-reverb", "reverb")
        clip = StudioClip("clip-1", reference, 0, 0, 2_000, effects=(effect,))
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(clip,),
        )
        inspector = StudioInspector()
        changed = QSignalSpy(inspector.effect_changed)

        inspector.set_selection(track, clip, None)
        button = inspector.effect_tab_buttons[effect.effect_id]
        editor = inspector.effect_editors[effect.effect_id]
        updated_effect = replace(
            effect,
            reverb=replace(effect.reverb, dry_wet_percent=61),
        )
        updated_clip = replace(clip, effects=(updated_effect,))

        for _ in range(3):
            inspector.set_selection(track, updated_clip, None)

        self.assertIs(inspector.effect_tab_buttons[effect.effect_id], button)
        self.assertIs(inspector.effect_editors[effect.effect_id], editor)
        self.assertEqual(inspector.clip_tabs_layout.count(), 3)
        self.assertEqual(inspector.clip_detail_stack.count(), 2)
        self.assertEqual(editor.controls["dry_wet_percent"].value(), 61)

        editor._emit_changed()
        self.assertEqual(changed.count(), 1)
        inspector.close()


if __name__ == "__main__":
    unittest.main()
