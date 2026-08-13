from __future__ import annotations

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
        if not force_upload:
            existing = self.existing_share(source, category)
            if existing is not None:
                if progress is not None:
                    progress(100)
                return existing
        remote = self._client().upload_shared_file(
            source,
            category,
            progress=progress,
            cancelled=cancelled,
        )
        record = self._catalog.record(source, category, remote)
        return GoogleDriveShareResult(record, reused=False)

    def delete_share(
        self,
        source: Path,
        category: str,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> bool:
        existing = self.existing_share(source, category)
        if existing is None:
            return False
        if progress is not None:
            progress(20)
        self._client().delete_file(existing.record.file_id)
        if progress is not None:
            progress(85)
        removed = self._catalog.remove(source, category)
        if progress is not None:
            progress(100)
        return removed

    def move_shared_source(self, source: Path, target: Path, category: str) -> bool:
        return self._catalog.move_source(source, target, category)

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
