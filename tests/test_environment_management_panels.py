from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from jang_app.qt_app.environment_management_panels import (
    PcEnvironmentPanel,
    RvcEnvironmentPanel,
    StorageManagementPanel,
)
from jang_app.services.rvc_environment_status import (
    RvcEnvironmentCheck,
    RvcEnvironmentSnapshot,
)
from jang_app.services.rvc_hardware import GraphicsAdapter
from jang_app.services.i18n import tr
from jang_app.services.storage_management import (
    CleanupCandidate,
    StorageCategory,
    StorageCleanupPlan,
    StorageInventory,
)
from jang_app.services.system_environment import (
    MemoryInformation,
    PcEnvironmentSnapshot,
    ProcessorInformation,
)


class EnvironmentManagementPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_pc_panel_presents_selected_hardware_and_memory(self) -> None:
        panel = PcEnvironmentPanel()
        panel.set_snapshot(
            PcEnvironmentSnapshot(
                "Windows 11",
                ProcessorInformation("Test CPU", 8, 16, "AMD64"),
                MemoryInformation(32 * 1024**3, 8 * 1024**3),
                (
                    GraphicsAdapter(
                        "RTX Test",
                        "nvidia",
                        driver_version="1.2.3",
                        adapter_ram=12 * 1024**3,
                    ),
                ),
                "RTX Test",
                "cu128",
                datetime.now(UTC),
            )
        )

        self.assertEqual(panel.memory_bar.value(), 75)
        self.assertEqual(panel.hero.title_label.text(), "RTX Test")
        self.assertEqual(panel.status_label.property("status"), "completed")
        self.assertFalse(panel.scroll_area.isAncestorOf(panel.title_label))
        panel.close()

    def test_rvc_panel_separates_runtime_devices_and_checks(self) -> None:
        panel = RvcEnvironmentPanel()
        panel.set_snapshot(
            RvcEnvironmentSnapshot(
                "completed",
                "RVC is ready for conversion and model training.",
                Path("C:/Runtime/rvc"),
                "Managed installation",
                "cu128",
                "cu128",
                "3",
                "3.11.9",
                "2.7.1+cu128",
                "12.8",
                "",
                (12, 0),
                "cuda",
                "cuda",
                "RTX Test",
                "active",
                (
                    RvcEnvironmentCheck(
                        "runtime",
                        "Runtime executable",
                        "completed",
                        "Ready",
                    ),
                ),
                datetime.now(UTC),
                True,
            )
        )

        self.assertEqual(panel.status_label.property("status"), "completed")
        runtime_text = " ".join(
            label.text() for label in panel.runtime_card.findChildren(QLabel)
        )
        self.assertIn("2.7.1", runtime_text)
        self.assertEqual(panel.detailed_button.text(), tr("Run Detailed Check Again"))
        status_rows = panel.checks_card.findChildren(QLabel)
        self.assertTrue(status_rows)
        self.assertFalse(panel.scroll_area.isAncestorOf(panel.title_label))
        panel.close()

    def test_storage_panel_shows_capacity_and_safe_cleanup_only(self) -> None:
        panel = StorageManagementPanel()
        root = Path("C:/JJZero")
        panel.set_inventory(
            StorageInventory(
                root,
                100 * 1024**3,
                75 * 1024**3,
                25 * 1024**3,
                (
                    StorageCategory(
                        "library",
                        "Library",
                        "protected",
                        30 * 1024**3,
                        100,
                        (root / "Data",),
                    ),
                ),
                datetime.now(UTC),
            )
        )
        candidate = CleanupCandidate(
            "Temporary jobs",
            root / "Cache" / "old.tmp",
            root / "Cache",
            2 * 1024**3,
            4,
        )
        panel.set_cleanup_plan(StorageCleanupPlan((candidate,)))

        self.assertEqual(panel.storage_bar.value(), 75)
        self.assertTrue(panel.cleanup_button.isEnabled())
        self.assertIn("2.0 GB", panel.cleanup_summary.text())
        self.assertFalse(panel.scroll_area.isAncestorOf(panel.title_label))
        panel.close()


if __name__ == "__main__":
    unittest.main()
