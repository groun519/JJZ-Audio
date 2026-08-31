from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from jang_app.services.managed_files import managed_path_lock, write_json_atomic


TRANSACTION_DIRECTORY_NAME = ".jjzero-transactions"
TRANSACTION_JOURNAL_NAME = "transaction.json"


class ManagedTransactionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedTransactionRecovery:
    transaction_folder: Path
    state: str
    action: str
    error: str = ""


@dataclass(frozen=True)
class ManagedTransactionMove:
    label: str
    source: Path
    staged: Path


@dataclass(frozen=True)
class ManagedTransactionCreated:
    label: str
    path: Path
    discarded: Path


class ManagedPathTransaction:
    """Quarantine managed paths before committing their metadata mutation."""

    def __init__(self, managed_root: Path, kind: str, resource_id: str) -> None:
        self.managed_root = managed_root.expanduser().resolve()
        safe_kind = _safe_component(kind, "transaction")
        safe_resource = _safe_component(resource_id, "resource")
        self.transaction_id = uuid4().hex
        self.folder = (
            self.managed_root
            / TRANSACTION_DIRECTORY_NAME
            / f"{safe_kind}-{safe_resource}-{self.transaction_id}"
        )
        self.journal = self.folder / TRANSACTION_JOURNAL_NAME
        self.kind = safe_kind
        self.resource_id = resource_id
        self._moves: list[ManagedTransactionMove] = []
        self._created: list[ManagedTransactionCreated] = []
        self._state = "prepared"

    @property
    def moves(self) -> tuple[ManagedTransactionMove, ...]:
        return tuple(self._moves)

    @property
    def created(self) -> tuple[ManagedTransactionCreated, ...]:
        return tuple(self._created)

    def prepare(self) -> None:
        """Persist an empty journal before staging payload inside the transaction."""
        self._write_journal(self._state)

    def expect_created(self, target: Path, label: str) -> ManagedTransactionCreated:
        """Journal a managed path that a later metadata write may create."""
        resolved = target.expanduser().resolve()
        if not _is_within(resolved, self.managed_root):
            raise ManagedTransactionError(
                f"Managed transaction path leaves its root: {resolved}"
            )
        if resolved.exists() or resolved.is_symlink():
            raise ManagedTransactionError(
                f"Managed transaction expected a new path: {resolved}"
            )
        safe_label = _safe_component(label, f"created-{len(self._created)}")
        discarded = self.folder / "discard" / safe_label
        if any(
            item.path == resolved or item.discarded == discarded
            for item in self._created
        ):
            raise ManagedTransactionError(
                "Managed transaction created paths must be unique."
            )
        created = ManagedTransactionCreated(safe_label, resolved, discarded)
        self._created.append(created)
        self._state = "staged"
        try:
            self._write_journal(self._state)
        except Exception:
            self._created.pop()
            raise
        return created

    def stage(self, source: Path, label: str) -> ManagedTransactionMove | None:
        resolved = source.expanduser().resolve()
        if not resolved.exists() and not resolved.is_symlink():
            return None
        if not _is_within(resolved, self.managed_root):
            raise ManagedTransactionError(
                f"Managed transaction path leaves its root: {resolved}"
            )
        safe_label = _safe_component(label, f"entry-{len(self._moves)}")
        staged = self.folder / "payload" / safe_label
        if any(move.source == resolved or move.staged == staged for move in self._moves):
            raise ManagedTransactionError("Managed transaction paths must be unique.")
        move = ManagedTransactionMove(safe_label, resolved, staged)
        self._moves.append(move)
        self._write_journal("preparing")
        try:
            staged.parent.mkdir(parents=True, exist_ok=True)
            os.replace(resolved, staged)
        except Exception:
            self._moves.pop()
            self._write_journal(self._state)
            raise
        self._state = "staged"
        self._write_journal(self._state)
        return move

    def promote(
        self,
        staged_source: Path,
        destination: Path,
        label: str,
    ) -> ManagedTransactionCreated:
        source = staged_source.expanduser().resolve()
        target = destination.expanduser().resolve()
        if not _is_within(source, self.managed_root):
            raise ManagedTransactionError(
                f"Managed transaction staging path leaves its root: {source}"
            )
        if not _is_within(target, self.managed_root):
            raise ManagedTransactionError(
                f"Managed transaction destination leaves its root: {target}"
            )
        if not source.exists() and not source.is_symlink():
            raise ManagedTransactionError(
                f"Managed transaction staging path is missing: {source}"
            )
        if target.exists() or target.is_symlink():
            raise ManagedTransactionError(
                f"Managed transaction destination already exists: {target}"
            )
        safe_label = _safe_component(label, f"created-{len(self._created)}")
        discarded = self.folder / "discard" / safe_label
        if any(item.path == target or item.discarded == discarded for item in self._created):
            raise ManagedTransactionError(
                "Managed transaction created paths must be unique."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        created = ManagedTransactionCreated(safe_label, target, discarded)
        self._created.append(created)
        self._state = "staged"
        try:
            self._write_journal(self._state)
        except Exception:
            self._created.pop()
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, source)
            raise
        return created

    def mark_committed(self) -> None:
        self._state = "committed"
        self._write_journal(self._state)

    def rollback(self) -> None:
        failures: list[str] = []
        for created in reversed(self._created):
            if not created.path.exists() and not created.path.is_symlink():
                continue
            try:
                if created.discarded.exists() or created.discarded.is_symlink():
                    raise FileExistsError(created.discarded)
                created.discarded.parent.mkdir(parents=True, exist_ok=True)
                os.replace(created.path, created.discarded)
            except OSError as exc:
                failures.append(f"{created.label}: {exc}")
        for move in reversed(self._moves):
            if not move.staged.exists() and not move.staged.is_symlink():
                continue
            try:
                if move.source.exists() or move.source.is_symlink():
                    raise FileExistsError(move.source)
                move.source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(move.staged, move.source)
            except OSError as exc:
                failures.append(f"{move.label}: {exc}")
        self._state = "rolled_back" if not failures else "rollback_failed"
        try:
            self._write_journal(self._state, failures=failures)
        except OSError as exc:
            failures.append(f"journal: {exc}")
        if failures:
            raise ManagedTransactionError(
                "Managed transaction rollback failed: " + "; ".join(failures)
            )
        self.purge()

    def purge(self) -> bool:
        if not self.folder.exists():
            return True
        try:
            shutil.rmtree(self.folder)
        except OSError:
            return False
        parent = self.folder.parent
        try:
            parent.rmdir()
        except OSError:
            pass
        return True

    def _write_journal(self, state: str, *, failures: list[str] | None = None) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            self.journal,
            {
                "version": 1,
                "id": self.transaction_id,
                "kind": self.kind,
                "resource_id": self.resource_id,
                "state": state,
                "updated_at": datetime.now(UTC).isoformat(),
                "moves": [
                    {
                        "label": move.label,
                        "source": str(move.source),
                        "staged": str(move.staged),
                    }
                    for move in self._moves
                ],
                "created": [
                    {
                        "label": created.label,
                        "path": str(created.path),
                        "discarded": str(created.discarded),
                    }
                    for created in self._created
                ],
                "failures": list(failures or ()),
            },
        )


def _safe_component(value: str, fallback: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "-"
        for character in str(value).strip()
    ).strip("-.")
    return cleaned[:80] or fallback


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def recover_managed_transactions(
    managed_root: Path,
) -> tuple[ManagedTransactionRecovery, ...]:
    root = managed_root.expanduser().resolve()
    transactions_root = root / TRANSACTION_DIRECTORY_NAME
    if not transactions_root.is_dir():
        return ()
    reports: list[ManagedTransactionRecovery] = []
    with managed_path_lock(transactions_root / ".recovery"):
        for folder in sorted(transactions_root.iterdir()):
            if not folder.is_dir():
                continue
            reports.append(_recover_transaction_folder(root, folder))
        try:
            transactions_root.rmdir()
        except OSError:
            pass
    return tuple(reports)


def recover_workspace_transactions(
    workspace_root: Path,
) -> tuple[ManagedTransactionRecovery, ...]:
    workspace = workspace_root.expanduser().resolve()
    songs_root = workspace / "library" / "songs"
    roots = [workspace / "models", songs_root]
    if songs_root.is_dir():
        roots.extend(
            path
            for path in songs_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
    reports: list[ManagedTransactionRecovery] = []
    for root in roots:
        reports.extend(recover_managed_transactions(root))
    return tuple(reports)


def _recover_transaction_folder(
    managed_root: Path,
    folder: Path,
) -> ManagedTransactionRecovery:
    journal = folder / TRANSACTION_JOURNAL_NAME
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ManagedTransactionError("Unsupported transaction journal.")
        state = str(data.get("state", ""))
        moves = _journal_entries(
            data.get("moves"),
            managed_root,
            folder,
            path_key="source",
            staged_key="staged",
        )
        created = _journal_entries(
            data.get("created", []),
            managed_root,
            folder,
            path_key="path",
            staged_key="discarded",
        )
        if state in {"committed", "rolled_back"}:
            action = "purged" if _purge_folder(folder) else "cleanup_pending"
            return ManagedTransactionRecovery(folder, state, action)

        _rollback_journal(folder, moves, created)
        recovered_data = dict(data)
        recovered_data["state"] = "rolled_back"
        recovered_data["recovered_at"] = datetime.now(UTC).isoformat()
        write_json_atomic(journal, recovered_data)
        action = "rolled_back" if _purge_folder(folder) else "cleanup_pending"
        return ManagedTransactionRecovery(folder, state, action)
    except Exception as exc:
        return ManagedTransactionRecovery(
            folder,
            "unknown",
            "failed",
            str(exc),
        )


def _journal_entries(
    value: object,
    managed_root: Path,
    transaction_folder: Path,
    *,
    path_key: str,
    staged_key: str,
) -> tuple[tuple[str, Path, Path], ...]:
    if not isinstance(value, list):
        raise ManagedTransactionError("Transaction journal entries are invalid.")
    entries: list[tuple[str, Path, Path]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ManagedTransactionError("Transaction journal entry is invalid.")
        label = str(raw.get("label", "")).strip()
        path = Path(str(raw.get(path_key, ""))).expanduser().resolve()
        staged = Path(str(raw.get(staged_key, ""))).expanduser().resolve()
        if not label or not _is_within(path, managed_root):
            raise ManagedTransactionError(
                "Transaction journal path leaves its managed root."
            )
        if not _is_within(staged, transaction_folder):
            raise ManagedTransactionError(
                "Transaction journal staging path leaves its transaction folder."
            )
        entries.append((label, path, staged))
    return tuple(entries)


def _rollback_journal(
    folder: Path,
    moves: tuple[tuple[str, Path, Path], ...],
    created: tuple[tuple[str, Path, Path], ...],
) -> None:
    for label, path, discarded in reversed(created):
        if not path.exists() and not path.is_symlink():
            continue
        _move_for_recovery(path, discarded, label)

    for label, source, staged in reversed(moves):
        if not staged.exists() and not staged.is_symlink():
            continue
        if source.exists() or source.is_symlink():
            replacement = folder / "recovery-discard" / label
            _move_for_recovery(source, replacement, label)
        source.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, source)


def _move_for_recovery(source: Path, target: Path, label: str) -> None:
    if target.exists() or target.is_symlink():
        raise ManagedTransactionError(
            f"Recovery target already exists for {label}: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)


def _purge_folder(folder: Path) -> bool:
    try:
        shutil.rmtree(folder)
    except OSError:
        return False
    return True
