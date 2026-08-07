from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.workers import TaskWorker
from jang_app.services.app_paths import AppPaths
from jang_app.services.google_drive import GoogleDriveCancelled, GoogleDriveUnavailableError
from jang_app.services.google_drive_download import download_public_drive_file
from jang_app.services.google_drive_share import (
    GoogleDriveShareResult,
    GoogleDriveShareService,
    create_google_drive_share_service,
    drive_share_target_id,
)
from jang_app.services.google_oauth import GoogleOAuthConfigurationError
from jang_app.services.model_share_package import (
    ImportedSharedModel,
    ModelShareCancelled,
    create_model_share_package,
    find_current_model_share_package,
    import_model_share_package,
)
from jang_app.services.rvc_model_workspace import RvcModelRecord, RvcModelWorkspace


WorkerRunner = Callable[..., None]


@dataclass(frozen=True)
class _DriveShareTarget:
    target_id: str
    source: Path
    title: str
    category: str
    model: RvcModelRecord | None = None


class GoogleDriveController(QObject):
    account_changed = Signal(object)
    account_busy_changed = Signal(bool)
    account_error = Signal(str)
    account_unavailable = Signal(str)
    feature_availability_changed = Signal(bool)
    share_started = Signal(str)
    share_progress = Signal(str, int)
    share_succeeded = Signal(str, str)
    share_failed = Signal(str, str)
    share_deleted = Signal(str)

    def __init__(
        self,
        parent: QWidget,
        *,
        paths: AppPaths,
        oauth_asset: Path,
        model_workspace: RvcModelWorkspace,
        run_worker: WorkerRunner,
        model_status: Callable[[str], None],
        models_imported: Callable[[tuple[RvcModelRecord, ...]], None],
        logger: logging.Logger,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._oauth_asset = oauth_asset
        self._model_workspace = model_workspace
        self._run_worker = run_worker
        self._model_status = model_status
        self._models_imported = models_imported
        self._logger = logger
        self._service: GoogleDriveShareService | None = None
        self._service_error = ""
        self._policy_error = ""
        self._runtime_error = ""
        self._account_cancellation: Event | None = None
        self._account_running = False
        self._pending_shares: dict[str, _DriveShareTarget] = {}
        self._pending_deletes: dict[str, _DriveShareTarget] = {}
        self._active_shares: dict[str, Event] = {}

    def set_feature_enabled(self, is_enabled: bool, reason: str = "") -> None:
        was_enabled = not self._policy_error
        self._policy_error = "" if is_enabled else (
            reason.strip() or "Google Drive sharing is temporarily unavailable."
        )
        if self._policy_error:
            self._cancel_account()
            self._cancel_shares(self._policy_error)
            self.feature_availability_changed.emit(False)
            self.account_unavailable.emit(self._policy_error)
            return
        if not was_enabled:
            self.refresh_account_state()

    def refresh_account_state(self) -> None:
        unavailable = self._unavailable_reason()
        if unavailable:
            self.feature_availability_changed.emit(False)
            self.account_unavailable.emit(unavailable)
            return
        service = self._get_service()
        if service is None:
            self.feature_availability_changed.emit(False)
            self.account_unavailable.emit(self._unavailable_reason())
            return
        self.feature_availability_changed.emit(True)
        self.account_changed.emit(service.account)

    def connect_account(self) -> None:
        self._connect_account()

    def switch_account(self) -> None:
        self._connect_account(switch_account=True)

    def disconnect_account(self) -> None:
        service = self._get_service()
        if service is None or self._account_running:
            return
        self._cancel_shares("Google Drive account disconnected.")
        self._account_running = True
        self.account_busy_changed.emit(True)

        def disconnect(progress: Callable[[int], None]) -> None:
            progress(10)
            service.disconnect()
            progress(100)

        self._run_worker(
            TaskWorker(disconnect),
            lambda _result: self._on_disconnected(),
            self._on_account_action_failed,
            None,
            task_title="Disconnect Google Drive",
            task_detail=service.account.email if service.account is not None else "",
        )

    def open_export_share(self, path: Path) -> None:
        if self._reject_unavailable_action():
            return
        self._request_share(self._export_target(path))

    def open_model_share(self, record: RvcModelRecord) -> None:
        if self._reject_unavailable_action(notify_model=True):
            return
        if record.inference_model is None or not record.inference_model.is_file():
            self._model_status("This model has no inference PTH to share.")
            return
        self._request_share(self._model_target(record))

    def delete_export_share(self, path: Path) -> None:
        if not self._reject_unavailable_action():
            self._request_delete(self._export_target(path))

    def delete_model_share(self, record: RvcModelRecord) -> None:
        if not self._reject_unavailable_action(notify_model=True):
            self._request_delete(self._model_target(record))

    def is_export_shared(self, path: Path) -> bool:
        return self._target_is_shared(self._export_target(path))

    def is_model_shared(self, record: RvcModelRecord) -> bool:
        if not record.can_convert:
            return False
        return self._target_is_shared(self._model_target(record))

    def import_model_link(self, link: str) -> None:
        self._model_status("Downloading shared model...")

        def import_model(progress: Callable[[int], None]) -> ImportedSharedModel:
            package_path = download_public_drive_file(
                link,
                self._paths.cache_dir / "drive_downloads",
                progress=lambda value: progress(value * 55 // 100),
            )
            return import_model_share_package(
                package_path,
                self._model_workspace,
                progress=lambda value: progress(55 + value * 45 // 100),
            )

        self._run_worker(
            TaskWorker(import_model),
            self._on_model_import_succeeded,
            lambda error: self._model_status(
                f"Drive import failed: {_last_error_line(error)}"
            ),
            None,
            task_title="Import Drive Model",
            task_detail="Shared RVC model",
        )

    def shutdown(self) -> None:
        self._cancel_account()
        self._cancel_shares("Google Drive operation cancelled.")

    @staticmethod
    def _export_target(path: Path) -> _DriveShareTarget:
        return _DriveShareTarget(
            target_id=drive_share_target_id(path),
            source=path,
            title=path.name,
            category="exports",
        )

    @staticmethod
    def _model_target(record: RvcModelRecord) -> _DriveShareTarget:
        return _DriveShareTarget(
            target_id=record.model_id,
            source=record.inference_model or record.source_folder,
            title=record.title,
            category="models",
            model=record,
        )

    def _target_is_shared(self, target: _DriveShareTarget) -> bool:
        service = self._get_service()
        if service is None:
            return False
        try:
            return self._existing_share(service, target) is not None
        except OSError:
            return False

    def _request_share(self, target: _DriveShareTarget) -> None:
        if (
            target.target_id in self._pending_shares
            or target.target_id in self._pending_deletes
            or target.target_id in self._active_shares
        ):
            return
        service = self._get_service()
        if service is None:
            self.account_unavailable.emit(self._unavailable_reason())
            return
        existing = self._existing_share(service, target)
        if existing is not None:
            QApplication.clipboard().setText(existing.share_link)
            self.share_succeeded.emit(target.target_id, existing.share_link)
            return
        self.share_started.emit(target.target_id)
        if service.account is None:
            self._pending_shares[target.target_id] = target
            self._connect_account()
            return
        self._start_share(target)

    def _request_delete(self, target: _DriveShareTarget) -> None:
        if (
            target.target_id in self._pending_shares
            or target.target_id in self._pending_deletes
            or target.target_id in self._active_shares
        ):
            return
        service = self._get_service()
        if service is None:
            self.account_unavailable.emit(self._unavailable_reason())
            return
        if self._existing_share(service, target) is None:
            self.share_deleted.emit(target.target_id)
            return
        self.share_started.emit(target.target_id)
        if service.account is None:
            self._pending_deletes[target.target_id] = target
            self._connect_account()
            return
        self._start_delete(target)

    def _existing_share(
        self,
        service: GoogleDriveShareService,
        target: _DriveShareTarget,
    ) -> GoogleDriveShareResult | None:
        source = self._resolved_share_source(target)
        if source is None:
            return None
        return service.existing_share(source, target.category)

    def _resolved_share_source(self, target: _DriveShareTarget) -> Path | None:
        if target.model is None:
            return target.source
        package = find_current_model_share_package(
            target.model,
            self._paths.cache_dir / "model_shares" / target.model.model_id,
        )
        return package.path if package is not None else None

    def _get_service(self) -> GoogleDriveShareService | None:
        if self._unavailable_reason():
            return None
        if self._service is not None:
            return self._service
        if self._service_error:
            return None
        try:
            self._service = create_google_drive_share_service(
                self._paths,
                self._oauth_asset,
            )
        except Exception as exc:
            self._service_error = _last_error_line(str(exc))
            if isinstance(exc, GoogleOAuthConfigurationError) or (
                "OAuth client is not configured" in self._service_error
            ):
                self._runtime_error = self._service_error
            self._logger.info(
                "Google Drive sharing is unavailable: %s",
                self._service_error,
            )
        return self._service

    def _connect_account(self, *, switch_account: bool = False) -> None:
        service = self._get_service()
        if service is None or self._account_running:
            if service is None:
                self.account_unavailable.emit(self._unavailable_reason())
            return
        self._account_running = True
        self.account_busy_changed.emit(True)
        cancellation = Event()
        self._account_cancellation = cancellation

        def connect(progress: Callable[[int], None]) -> object:
            if switch_account:
                service.disconnect()
            progress(5)
            account = service.connect(cancelled=cancellation.is_set)
            progress(75)
            quota = service.quota()
            progress(100)
            return account, quota

        self._run_worker(
            TaskWorker(connect),
            self._on_connected,
            self._on_account_connection_failed,
            None,
            task_title="Connect Google Drive",
            task_detail="Account authorization",
            cancelled_error=_is_cancelled_error,
        )

    def _on_connected(self, result: object) -> None:
        self._account_running = False
        self._account_cancellation = None
        self.account_busy_changed.emit(False)
        if not isinstance(result, tuple) or len(result) != 2:
            self._fail_pending_operations("Google account authorization returned no account.")
            return
        account, _quota = result
        self.account_changed.emit(account)
        pending = tuple(self._pending_shares.values())
        self._pending_shares.clear()
        for target in pending:
            self._start_share(target)
        pending_deletes = tuple(self._pending_deletes.values())
        self._pending_deletes.clear()
        for target in pending_deletes:
            self._start_delete(target)

    def _on_account_connection_failed(self, error: str) -> None:
        self._account_running = False
        self._account_cancellation = None
        self.account_busy_changed.emit(False)
        detail = _last_error_line(error)
        account = self._service.account if self._service is not None else None
        self.account_changed.emit(account)
        if self._disable_for_error(error):
            return
        self.account_error.emit(detail)
        self._fail_pending_operations(detail)

    def _on_disconnected(self) -> None:
        self._account_running = False
        self.account_busy_changed.emit(False)
        self.account_changed.emit(None)

    def _on_account_action_failed(self, error: str) -> None:
        self._account_running = False
        self.account_busy_changed.emit(False)
        if self._disable_for_error(error):
            return
        self.account_error.emit(_last_error_line(error))

    def _start_share(self, target: _DriveShareTarget) -> None:
        service = self._get_service()
        if service is None:
            self.share_failed.emit(target.target_id, self._unavailable_reason())
            return
        cancellation = Event()
        self._active_shares[target.target_id] = cancellation

        def share(progress: Callable[[int], None]) -> GoogleDriveShareResult:
            source = target.source
            upload_start = 0
            if target.model is not None:
                package = create_model_share_package(
                    target.model,
                    self._paths.cache_dir / "model_shares" / target.model.model_id,
                    progress=lambda value: progress(value * 30 // 100),
                    cancelled=cancellation.is_set,
                )
                source = package.path
                upload_start = 30
            return service.share_file(
                source,
                target.category,
                progress=lambda value: progress(
                    upload_start + value * (100 - upload_start) // 100
                ),
                cancelled=cancellation.is_set,
            )

        worker = TaskWorker(share)
        worker.progress_changed.connect(
            lambda progress, target_id=target.target_id: self.share_progress.emit(
                target_id, progress
            )
        )
        self._run_worker(
            worker,
            lambda result: self._on_share_succeeded(target, result),
            lambda error: self._on_share_failed(target, error),
            None,
            task_title="Share with Google Drive",
            task_detail=target.title,
            cancelled_error=_is_cancelled_error,
        )

    def _start_delete(self, target: _DriveShareTarget) -> None:
        service = self._get_service()
        source = self._resolved_share_source(target)
        if service is None or source is None:
            self.share_deleted.emit(target.target_id)
            return
        cancellation = Event()
        self._active_shares[target.target_id] = cancellation

        def delete(progress: Callable[[int], None]) -> bool:
            if cancellation.is_set():
                raise GoogleDriveCancelled("Google Drive operation was cancelled.")
            return service.delete_share(
                source,
                target.category,
                progress=progress,
            )

        worker = TaskWorker(delete)
        worker.progress_changed.connect(
            lambda progress, target_id=target.target_id: self.share_progress.emit(
                target_id, progress
            )
        )
        self._run_worker(
            worker,
            lambda _result: self._on_delete_succeeded(target),
            lambda error: self._on_share_failed(target, error),
            None,
            task_title="Delete Google Drive Share",
            task_detail=target.title,
            cancelled_error=_is_cancelled_error,
        )

    def _on_share_succeeded(self, target: _DriveShareTarget, result: object) -> None:
        if self._active_shares.pop(target.target_id, None) is None:
            return
        if not isinstance(result, GoogleDriveShareResult):
            self.share_failed.emit(target.target_id, "Google Drive returned no share link.")
            return
        QApplication.clipboard().setText(result.share_link)
        self.share_progress.emit(target.target_id, 100)
        self.share_succeeded.emit(target.target_id, result.share_link)

    def _on_share_failed(self, target: _DriveShareTarget, error: str) -> None:
        if self._active_shares.pop(target.target_id, None) is None:
            return
        detail = _last_error_line(error)
        self._disable_for_error(error)
        self.share_failed.emit(target.target_id, detail)

    def _on_delete_succeeded(self, target: _DriveShareTarget) -> None:
        if self._active_shares.pop(target.target_id, None) is None:
            return
        self.share_deleted.emit(target.target_id)

    def _disable_for_error(self, error: str) -> bool:
        if not _is_unavailable_error(error):
            return False
        self._runtime_error = _last_error_line(error)
        self._cancel_account()
        self._cancel_shares(self._runtime_error)
        self.feature_availability_changed.emit(False)
        self.account_unavailable.emit(self._runtime_error)
        return True

    def _unavailable_reason(self) -> str:
        return self._policy_error or self._runtime_error or self._service_error

    def _reject_unavailable_action(self, *, notify_model: bool = False) -> bool:
        reason = self._unavailable_reason()
        if not reason:
            return False
        self.account_unavailable.emit(reason)
        if notify_model:
            self._model_status(reason)
        return True

    def _on_model_import_succeeded(self, result: object) -> None:
        if isinstance(result, ImportedSharedModel):
            self._models_imported(result.records)

    def _cancel_account(self) -> None:
        if self._account_cancellation is not None:
            self._account_cancellation.set()

    def _cancel_shares(self, reason: str) -> None:
        target_ids = tuple(
            {*self._pending_shares, *self._pending_deletes, *self._active_shares}
        )
        for cancellation in self._active_shares.values():
            cancellation.set()
        self._pending_shares.clear()
        self._pending_deletes.clear()
        self._active_shares.clear()
        for target_id in target_ids:
            self.share_failed.emit(target_id, reason)

    def _fail_pending_operations(self, reason: str) -> None:
        target_ids = tuple({*self._pending_shares, *self._pending_deletes})
        self._pending_shares.clear()
        self._pending_deletes.clear()
        for target_id in target_ids:
            self.share_failed.emit(target_id, reason)


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"


def _is_cancelled_error(error: str) -> bool:
    return (
        GoogleDriveCancelled.__name__ in error
        or ModelShareCancelled.__name__ in error
        or "operation was cancelled" in error.casefold()
        or "connection was cancelled" in error.casefold()
    )


def _is_unavailable_error(error: str) -> bool:
    return (
        GoogleDriveUnavailableError.__name__ in error
        or GoogleOAuthConfigurationError.__name__ in error
        or "OAuth client is not configured" in error
    )
