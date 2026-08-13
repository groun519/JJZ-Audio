from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.studio_sound_pool import StudioSoundPool
from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.widgets import COMPACT_ICON_BUTTON_SIZE
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    TRACK_CONVERTED_VOCAL,
    TRACK_INSTRUMENTAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioAssetRef,
)
from jang_app.services.i18n import tr
from jang_app.services.vocal_project import VocalConversionSettings, VocalTake


class StudioSoundPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_role_filter_and_search_keep_matching_assets(self) -> None:
        pool = StudioSoundPool()
        assets = _assets()
        pool.set_assets(assets)

        pool.role_buttons[TRACK_CONVERTED_VOCAL].click()
        self.assertEqual(pool.visible_asset_ids(), (assets[2].asset_id,))

        pool.role_buttons["all"].click()
        pool.search_edit.setText("maximum")
        self.assertEqual(pool.visible_asset_ids(), (assets[0].asset_id, assets[1].asset_id))
        self.assertEqual(pool.count_label.text(), "2 / 3")

    def test_card_selection_does_not_add_an_asset(self) -> None:
        pool = StudioSoundPool()
        asset = _assets()[0]
        pool.set_assets((asset,))

        self.assertFalse(hasattr(pool._cards[asset.asset_id], "add_button"))
        self.assertIsInstance(pool._cards[asset.asset_id], SoundPoolItemCard)

    def test_grid_adapts_to_width_and_list_mode_uses_one_column(self) -> None:
        host = QWidget()
        pool = StudioSoundPool(host)
        pool.set_assets(_assets())
        pool.resize(620, 500)
        pool.show()
        self.app.processEvents()

        self.assertGreaterEqual(pool.column_count(), 2)
        self.assertEqual(
            pool.grid_button.size().toTuple(),
            (COMPACT_ICON_BUTTON_SIZE, COMPACT_ICON_BUTTON_SIZE),
        )
        self.assertEqual(pool.list_button.size(), pool.grid_button.size())
        pool.list_button.click()
        self.assertEqual(pool.column_count(), 1)
        host.close()

    def test_list_mode_uses_one_compact_metadata_row_without_waveforms(self) -> None:
        pool = StudioSoundPool()
        assets = _assets()
        pool.resize(360, 500)
        pool.set_assets(assets)
        pool.show()
        self.app.processEvents()

        pool.list_button.click()
        self.app.processEvents()

        card = pool._cards[assets[0].asset_id]
        self.assertEqual(card.height(), 48)
        self.assertFalse(card.preview_widget.isVisible())
        self.assertEqual(card.source_badge.text(), tr("Vocal"))
        self.assertEqual(card.title_label.text(), tr("Maximum"))
        self.assertEqual(card.detail_label.text(), "maximum-vocals")
        self.assertEqual(card.duration_label.text(), "02:31")
        pool.close()

    def test_removable_pool_asset_exposes_one_delete_entry_point(self) -> None:
        pool = StudioSoundPool()
        asset = replace(_assets()[0], can_remove=True)
        removed = QSignalSpy(pool.remove_requested)
        pool.set_assets((asset,))
        card = pool._cards[asset.asset_id]

        self.assertIsNotNone(card.remove_button)
        card.remove_button.click()

        self.assertEqual(removed.count(), 1)
        self.assertIs(removed.at(0)[0], asset)

    def test_protected_pool_asset_has_no_misleading_delete_button(self) -> None:
        pool = StudioSoundPool()
        asset = _assets()[0]
        pool.set_assets((asset,))

        self.assertIsNone(pool._cards[asset.asset_id].remove_button)

    def test_cards_are_parented_and_create_no_popup_windows(self) -> None:
        pool = StudioSoundPool()
        probe = _TopLevelShowProbe()
        self.app.installEventFilter(probe)
        pool.show()
        self.app.processEvents()
        probe.events.clear()
        pool.set_assets(_assets())
        pool.set_assets(_assets()[:1])
        self.app.processEvents()

        self.assertTrue(all(card.parentWidget() is pool.content for card in pool._cards.values()))
        child_windows = [child for child in pool.findChildren(QWidget) if child.isWindow()]
        self.assertEqual(child_windows, [])
        self.assertEqual(probe.events, [])
        self.app.removeEventFilter(probe)
        pool.close()

    def test_identical_assets_reuse_existing_cards(self) -> None:
        pool = StudioSoundPool()
        assets = _assets()
        pool.set_assets(assets)
        cards = dict(pool._cards)
        pool._select_asset(assets[0].asset_id)

        pool.set_assets(assets)

        self.assertEqual(pool._cards, cards)
        self.assertIs(pool._cards[assets[0].asset_id], cards[assets[0].asset_id])
        self.assertTrue(pool._cards[assets[0].asset_id].property("selected"))

    def test_changed_asset_replaces_only_its_card(self) -> None:
        pool = StudioSoundPool()
        assets = _assets()
        pool.set_assets(assets)
        cards = dict(pool._cards)
        changed = replace(assets[1], label="Maximum / Updated Instrumental")

        pool.set_assets((assets[0], changed, assets[2]))

        self.assertIs(pool._cards[assets[0].asset_id], cards[assets[0].asset_id])
        self.assertIsNot(pool._cards[changed.asset_id], cards[changed.asset_id])
        self.assertIs(pool._cards[assets[2].asset_id], cards[assets[2].asset_id])

    def test_cards_use_consistent_role_badge_and_card_sizes(self) -> None:
        pool = StudioSoundPool()
        assets = _assets()
        pool.resize(300, 700)
        pool.set_assets(assets)
        pool.show()
        self.app.processEvents()

        cards = [pool._cards[asset.asset_id] for asset in assets]
        self.assertEqual(len({card.height() for card in cards}), 1)
        self.assertEqual(len({card.source_badge.width() for card in cards}), 1)
        pool.close()

    def test_converted_card_uses_model_pitch_and_result_context(self) -> None:
        take = VocalTake(
            "take-voice-a",
            "voice-a / Pitch -12",
            Path("rvc_0123456789.wav"),
            "2026-08-11T02:41:51+00:00",
            VocalConversionSettings(
                "models/voice-a.pth",
                "models/voice-a.index",
                -12,
                "cuda:0",
                "cuda:0",
                "rmvpe",
            ),
        )
        asset = StudioSoundAsset(
            StudioAssetRef("fast", TRACK_CONVERTED_VOCAL, "rvc_0123456789.wav"),
            "Fast Separation / rvc_0123456789",
            Path("rvc_0123456789.wav"),
            151_000,
            take,
        )
        pool = StudioSoundPool()
        pool.set_assets((asset,))
        card = pool._cards[asset.asset_id]

        self.assertEqual(card.title_label.text(), f"voice-a / {tr('Pitch')} -12")
        self.assertIn(tr("Fast Separation"), card.detail_label.text())
        self.assertNotIn("rvc_0123456789", card.title_label.text())

    def test_legacy_converted_filename_is_humanized(self) -> None:
        asset = StudioSoundAsset(
            StudioAssetRef(
                "legacy",
                TRACK_CONVERTED_VOCAL,
                "vocals_rvc_jin_pitch_m12_jin_rmvpe.wav",
            ),
            "htdemucs / vocals_rvc_jin_pitch_m12_jin_rmvpe",
            Path("vocals_rvc_jin_pitch_m12_jin_rmvpe.wav"),
            151_000,
        )
        pool = StudioSoundPool()
        pool.set_assets((asset,))

        self.assertEqual(
            pool._cards[asset.asset_id].title_label.text(),
            f"jin / {tr('Pitch')} -12",
        )

    def test_video_asset_uses_video_preview_and_filter(self) -> None:
        video = StudioSoundAsset(
            StudioAssetRef("video-source", TRACK_VIDEO, "source.mp4"),
            "Source Video",
            Path("source.mp4"),
            151_000,
            media_kind="video",
        )
        pool = StudioSoundPool()
        pool.set_assets((*_assets(), video))

        pool.role_buttons[TRACK_VIDEO].click()

        self.assertEqual(pool.visible_asset_ids(), (video.asset_id,))
        self.assertIs(pool._cards[video.asset_id].preview_widget, pool._cards[video.asset_id].video_thumbnail)

    def test_image_asset_uses_media_preview_and_filter(self) -> None:
        image = StudioSoundAsset(
            StudioAssetRef("image-source", TRACK_VIDEO, "cover.png"),
            "Cover Image",
            Path("cover.png"),
            151_000,
            media_kind="image",
            default_clip_duration_ms=5_000,
        )
        pool = StudioSoundPool()
        pool.set_assets((*_assets(), image))

        pool.role_buttons[TRACK_VIDEO].click()

        self.assertEqual(pool.visible_asset_ids(), (image.asset_id,))
        self.assertEqual(pool._cards[image.asset_id].duration_label.text(), "00:05")
        self.assertIs(pool._cards[image.asset_id].preview_widget, pool._cards[image.asset_id].video_thumbnail)


def _assets() -> tuple[StudioSoundAsset, ...]:
    return (
        StudioSoundAsset(
            StudioAssetRef("maximum", TRACK_ORIGINAL_VOCAL),
            "Maximum / Original Vocal",
            Path("maximum-vocals.wav"),
            151_000,
        ),
        StudioSoundAsset(
            StudioAssetRef("maximum", TRACK_INSTRUMENTAL),
            "Maximum / Instrumental",
            Path("maximum-instrumental.wav"),
            151_000,
        ),
        StudioSoundAsset(
            StudioAssetRef("high-quality", TRACK_CONVERTED_VOCAL, "voice.wav"),
            "High Quality / voice-rmvpe-p0",
            Path("voice.wav"),
            151_000,
        ),
    )


class _TopLevelShowProbe(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str]] = []

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            self.events.append((type(watched).__name__, watched.objectName()))
        return False


if __name__ == "__main__":
    unittest.main()
