from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.drive_share_catalog import DriveShareCatalog, DriveShareRecord
from jang_app.services.google_drive import GoogleDriveClient, GoogleDriveQuota
from jang_app.services.google_oauth import (
    GoogleAccount,
    GoogleAccountStateStore,
    GoogleOAuthSession,
    load_google_oauth_config,
)
from jang_app.services.windows_credentials import CredentialStore, WindowsCredentialStore


_LOGGER = logging.getLogger("jang_app")


@dataclass(frozen=True)
class GoogleDriveShareResult:
    record: DriveShareRecord
    reused: bool

    @property
    def share_link(self) -> str:
        return self.record.share_link


def drive_share_target_id(source: Path) -> str:
    return os.path.normcase(str(source.expanduser().resolve()))


class GoogleDriveShareService:
    def __init__(
        self,
        oauth: GoogleOAuthSession,
        catalog: DriveShareCatalog,
    ) -> None:
        self._oauth = oauth
        self._catalog = catalog

    @property
    def account(self) -> GoogleAccount | None:
        return self._oauth.account

    @property
    def is_connected(self) -> bool:
        return self._oauth.is_connected

    def connect(
        self,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> GoogleAccount:
        return self._oauth.connect(cancelled=cancelled)

    def disconnect(self) -> None:
        self._oauth.disconnect()

    def quota(self) -> GoogleDriveQuota:
        return self._client().storage_quota()

    def existing_share(
        self,
        source: Path,
        category: str,
    ) -> GoogleDriveShareResult | None:
        record = self._catalog.find(source, category)
        return GoogleDriveShareResult(record, reused=True) if record is not None else None

    def share_file(
        self,
        source: Path,
        category: str,
        *,
        progress: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        force_upload: bool = False,
    ) -> GoogleDriveShareResult:
        source = source.expanduser().resolve()
        client = self._client()
        self._retry_pending_remote_deletes(client)
        if not force_upload:
            existing = self.existing_share(source, category)
            if existing is not None:
                if progress is not None:
                    progress(100)
                return existing
        uploaded = client.upload_file(
            source,
            category,
            progress=progress,
            cancelled=cancelled,
            uploaded=lambda remote: self._catalog.remember_pending_remote(
                remote,
                "uncommitted upload",
            ),
        )
        try:
            remote = client.publish_file(uploaded.file_id)
            record = self._catalog.record(source, category, remote)
        except BaseException:
            self._rollback_uploaded_file(client, uploaded.file_id)
            raise
        self._retry_pending_remote_deletes(client)
        return GoogleDriveShareResult(record, reused=False)

    def delete_share(
        self,
        source: Path,
        category: str,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> bool:
        client = self._client()
        self._retry_pending_remote_deletes(client)
        record = self._catalog.find_target(source, category)
        if record is None:
            return False
        if progress is not None:
            progress(20)
        client.delete_file(record.file_id)
        if progress is not None:
            progress(85)
        removed = self._catalog.remove(source, category)
        if progress is not None:
            progress(100)
        return removed

    def move_shared_source(self, source: Path, target: Path, category: str) -> bool:
        return self._catalog.move_source(source, target, category)

    def _rollback_uploaded_file(
        self,
        client: GoogleDriveClient,
        file_id: str,
    ) -> None:
        try:
            client.delete_file(file_id)
        except Exception as exc:
            _LOGGER.warning(
                "Google Drive upload rollback deferred | file_id=%s | error=%s",
                file_id,
                exc,
            )
            return
        try:
            self._catalog.forget_pending_remote(file_id)
        except OSError as exc:
            _LOGGER.warning(
                "Google Drive cleanup journal update deferred | file_id=%s | error=%s",
                file_id,
                exc,
            )

    def _retry_pending_remote_deletes(self, client: GoogleDriveClient) -> None:
        try:
            pending = self._catalog.pending_remote_deletes()
        except OSError as exc:
            _LOGGER.warning("Google Drive cleanup journal unavailable: %s", exc)
            return
        for item in pending:
            try:
                if self._catalog.has_file_id(item.file_id):
                    self._catalog.forget_pending_remote(item.file_id)
                    continue
                client.delete_file(item.file_id)
                self._catalog.forget_pending_remote(item.file_id)
            except Exception as exc:
                _LOGGER.warning(
                    "Google Drive remote cleanup deferred | file_id=%s | error=%s",
                    item.file_id,
                    exc,
                )

    def _client(self) -> GoogleDriveClient:
        return GoogleDriveClient(
            lambda force_refresh: self._oauth.access_token(
                force_refresh=force_refresh
            )
        )


def create_google_drive_share_service(
    paths: AppPaths,
    oauth_asset: Path,
    *,
    credentials: CredentialStore | None = None,
) -> GoogleDriveShareService:
    config = load_google_oauth_config(oauth_asset)
    oauth = GoogleOAuthSession(
        config,
        credentials or WindowsCredentialStore(),
        GoogleAccountStateStore(paths.settings_dir / "google_drive_account.json"),
    )
    return GoogleDriveShareService(
        oauth,
        DriveShareCatalog(paths.settings_dir / "google_drive_shares.json"),
    )
