from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.google_drive_controller import GoogleDriveController
from jang_app.services.drive_share_catalog import DriveShareRecord
from jang_app.services.google_drive import GoogleDriveQuota
from jang_app.services.google_drive_share import GoogleDriveShareResult, drive_share_target_id
from jang_app.services.model_share_package import create_model_share_package
from jang_app.services.rvc_model_workspace import RvcModelWorkspace


class GoogleDriveControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_remote_policy_disables_sharing_and_can_be_reenabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            statuses: list[str] = []
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=lambda *_args, **_kwargs: None,
                model_status=statuses.append,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            availability = QSignalSpy(controller.feature_availability_changed)
            unavailable = QSignalSpy(controller.account_unavailable)
            controller._get_service = lambda: SimpleNamespace(account=None)

            controller.set_feature_enabled(False, "Sharing disabled")
            controller.open_export_share(root / "mix.wav")
            controller.set_feature_enabled(True)

            self.assertEqual([availability.at(index)[0] for index in range(2)], [False, True])
            self.assertEqual(unavailable.at(0)[0], "Sharing disabled")
            self.assertEqual(statuses, [])
            self.assertEqual(controller._pending_shares, {})
            self.assertEqual(controller._active_shares, {})
            parent.close()

    def test_permanent_api_error_disables_the_feature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=lambda *_args, **_kwargs: None,
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            availability = QSignalSpy(controller.feature_availability_changed)

            disabled = controller._disable_for_error(
                "GoogleDriveUnavailableError: Drive API disabled"
            )

            self.assertTrue(disabled)
            self.assertFalse(availability.at(0)[0])
            self.assertEqual(controller._runtime_error, "GoogleDriveUnavailableError: Drive API disabled")
            parent.close()

    def test_share_runs_without_dialog_and_copies_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            link = "https://drive.google.com/file/d/test/view"
            record = DriveShareRecord(
                source_path=str(source.resolve()),
                source_size=source.stat().st_size,
                source_modified_ns=source.stat().st_mtime_ns,
                category="exports",
                file_id="test",
                file_name=source.name,
                share_link=link,
                shared_at="2026-08-07T00:00:00+00:00",
            )

            def run_worker(worker, on_success, on_failed, _action, **_kwargs):
                try:
                    on_success(worker._task(worker.progress_changed.emit))
                except Exception as exc:  # pragma: no cover - verifies failure wiring
                    on_failed(str(exc))

            service = SimpleNamespace(
                account=SimpleNamespace(email="user@example.com"),
                existing_share=lambda _source, _category: None,
                share_file=lambda _source, _category, **kwargs: _share_result(
                    kwargs["progress"], record
                ),
            )
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=run_worker,
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = service
            started = QSignalSpy(controller.share_started)
            progressed = QSignalSpy(controller.share_progress)
            succeeded = QSignalSpy(controller.share_succeeded)

            controller.open_export_share(source)

            target_id = drive_share_target_id(source)
            self.assertEqual(started.at(0)[0], target_id)
            self.assertEqual(progressed.at(progressed.count() - 1), [target_id, 100])
            self.assertEqual(succeeded.at(0), [target_id, link])
            self.assertEqual(QApplication.clipboard().text(), link)
            self.assertEqual(controller._active_shares, {})
            parent.close()

    def test_duplicate_share_click_does_not_start_another_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            workers: list[object] = []
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=lambda worker, *_args, **_kwargs: workers.append(worker),
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = SimpleNamespace(
                account=SimpleNamespace(email="user@example.com"),
                existing_share=lambda _source, _category: None,
            )
            started = QSignalSpy(controller.share_started)

            controller.open_export_share(source)
            controller.open_export_share(source)

            self.assertEqual(len(workers), 1)
            self.assertEqual(started.count(), 1)
            controller.shutdown()
            parent.close()

    def test_share_preflight_blocks_when_google_drive_space_is_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio" * 256)
            workers: list[object] = []
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=lambda worker, *_args, **_kwargs: workers.append(worker),
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = SimpleNamespace(
                account=SimpleNamespace(email="user@example.com"),
                existing_share=lambda _source, _category: None,
            )
            controller._quota = GoogleDriveQuota(
                limit_bytes=source.stat().st_size - 1,
                usage_bytes=0,
                drive_usage_bytes=0,
            )
            failed = QSignalSpy(controller.share_failed)
            started = QSignalSpy(controller.share_started)

            controller.open_export_share(source)

            self.assertEqual(workers, [])
            self.assertEqual(started.count(), 0)
            self.assertEqual(failed.count(), 1)
            self.assertEqual(failed.at(0)[0], drive_share_target_id(source))
            self.assertIn("용량", failed.at(0)[1])
            parent.close()

    def test_disconnected_share_resumes_after_account_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            link = "https://drive.google.com/file/d/resumed/view"
            record = DriveShareRecord(
                source_path=str(source.resolve()),
                source_size=source.stat().st_size,
                source_modified_ns=source.stat().st_mtime_ns,
                category="exports",
                file_id="resumed",
                file_name=source.name,
                share_link=link,
                shared_at="2026-08-07T00:00:00+00:00",
            )

            class Service:
                account = None

                def existing_share(self, _source, _category):
                    return None

                def connect(self, *, cancelled):
                    self.account = SimpleNamespace(email="user@example.com")
                    return self.account

                def quota(self):
                    return SimpleNamespace()

                def share_file(self, _source, _category, **kwargs):
                    return _share_result(kwargs["progress"], record)

            def run_worker(worker, on_success, on_failed, _action, **_kwargs):
                try:
                    on_success(worker._task(worker.progress_changed.emit))
                except Exception as exc:  # pragma: no cover - verifies failure wiring
                    on_failed(str(exc))

            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=run_worker,
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = Service()
            succeeded = QSignalSpy(controller.share_succeeded)

            controller.open_export_share(source)

            self.assertEqual(succeeded.at(0), [drive_share_target_id(source), link])
            self.assertEqual(controller._pending_shares, {})
            self.assertEqual(controller._active_shares, {})
            parent.close()

    def test_existing_export_share_copies_without_creating_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            link = "https://drive.google.com/file/d/cached/view"
            record = DriveShareRecord(
                source_path=str(source.resolve()),
                source_size=source.stat().st_size,
                source_modified_ns=source.stat().st_mtime_ns,
                category="exports",
                file_id="cached",
                file_name=source.name,
                share_link=link,
                shared_at="2026-08-07T00:00:00+00:00",
            )
            workers: list[object] = []
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=lambda worker, *_args, **_kwargs: workers.append(worker),
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = SimpleNamespace(
                account=SimpleNamespace(email="user@example.com"),
                existing_share=lambda _source, _category: GoogleDriveShareResult(
                    record, reused=True
                ),
            )
            started = QSignalSpy(controller.share_started)
            succeeded = QSignalSpy(controller.share_succeeded)

            controller.open_export_share(source)

            self.assertEqual(workers, [])
            self.assertEqual(started.count(), 0)
            self.assertEqual(succeeded.at(0), [drive_share_target_id(source), link])
            self.assertEqual(QApplication.clipboard().text(), link)
            parent.close()

    def test_existing_model_share_skips_packaging_and_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "voice.pth"
            model.write_bytes(b"model")
            workspace = RvcModelWorkspace(root / "models")
            model_record = workspace.link_inference_file(model)
            cache_dir = root / "cache"
            package = create_model_share_package(
                model_record,
                cache_dir / "model_shares" / model_record.model_id,
            )
            link = "https://drive.google.com/file/d/model-cached/view"
            share_record = DriveShareRecord(
                source_path=str(package.path.resolve()),
                source_size=package.path.stat().st_size,
                source_modified_ns=package.path.stat().st_mtime_ns,
                category="models",
                file_id="model-cached",
                file_name=package.path.name,
                share_link=link,
                shared_at="2026-08-07T00:00:00+00:00",
            )
            workers: list[object] = []
            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=cache_dir),
                oauth_asset=root / "oauth.json",
                model_workspace=workspace,
                run_worker=lambda worker, *_args, **_kwargs: workers.append(worker),
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = SimpleNamespace(
                account=SimpleNamespace(email="user@example.com"),
                existing_share=lambda source, category: (
                    GoogleDriveShareResult(share_record, reused=True)
                    if source == package.path and category == "models"
                    else None
                ),
            )
            started = QSignalSpy(controller.share_started)

            controller.open_model_share(model_record)

            self.assertEqual(workers, [])
            self.assertEqual(started.count(), 0)
            self.assertEqual(QApplication.clipboard().text(), link)
            parent.close()

    def test_delete_export_share_runs_remote_delete_and_emits_deleted_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            link = "https://drive.google.com/file/d/delete/view"
            record = DriveShareRecord(
                source_path=str(source.resolve()),
                source_size=source.stat().st_size,
                source_modified_ns=source.stat().st_mtime_ns,
                category="exports",
                file_id="delete",
                file_name=source.name,
                share_link=link,
                shared_at="2026-08-07T00:00:00+00:00",
            )
            delete_calls: list[tuple[Path, str]] = []

            def delete_share(path, category, *, progress):
                delete_calls.append((path, category))
                progress(100)
                return True

            def run_worker(worker, on_success, on_failed, _action, **_kwargs):
                try:
                    on_success(worker._task(worker.progress_changed.emit))
                except Exception as exc:  # pragma: no cover - verifies failure wiring
                    on_failed(str(exc))

            parent = QWidget()
            controller = GoogleDriveController(
                parent,
                paths=SimpleNamespace(cache_dir=root / "cache"),
                oauth_asset=root / "oauth.json",
                model_workspace=RvcModelWorkspace(root / "models"),
                run_worker=run_worker,
                model_status=lambda _message: None,
                models_imported=lambda _records: None,
                logger=logging.getLogger("test.google-drive"),
            )
            controller._service = SimpleNamespace(
                account=SimpleNamespace(email="user@example.com"),
                existing_share=lambda _source, _category: GoogleDriveShareResult(
                    record, reused=True
                ),
                delete_share=delete_share,
            )
            started = QSignalSpy(controller.share_started)
            deleted = QSignalSpy(controller.share_deleted)

            controller.delete_export_share(source)

            target_id = drive_share_target_id(source)
            self.assertEqual(started.at(0)[0], target_id)
            self.assertEqual(deleted.at(0)[0], target_id)
            self.assertEqual(delete_calls, [(source, "exports")])
            self.assertEqual(controller._active_shares, {})
            parent.close()


def _share_result(progress, record: DriveShareRecord) -> GoogleDriveShareResult:
    progress(35)
    progress(100)
    return GoogleDriveShareResult(record, reused=False)


if __name__ == "__main__":
    unittest.main()
