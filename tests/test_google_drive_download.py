from __future__ import annotations

import unittest

from jang_app.services.google_drive_download import (
    GoogleDriveDownloadError,
    google_drive_file_id,
)


class GoogleDriveDownloadTests(unittest.TestCase):
    def test_public_file_links_and_raw_ids_are_supported(self) -> None:
        file_id = "1AbCdEfGhIjKlMnOp"

        self.assertEqual(google_drive_file_id(file_id), file_id)
        self.assertEqual(
            google_drive_file_id(
                f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            ),
            file_id,
        )
        self.assertEqual(
            google_drive_file_id(
                f"https://drive.google.com/open?id={file_id}"
            ),
            file_id,
        )

    def test_non_drive_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(GoogleDriveDownloadError, "Google Drive"):
            google_drive_file_id(
                "https://example.com/file/d/1AbCdEfGhIjKlMnOp/view"
            )


if __name__ == "__main__":
    unittest.main()
