from __future__ import annotations

from jang_app.services.command import CommandCancellation


class RvcTrainingCancelled(RuntimeError):
    """Raised when a user stops an RVC preparation or training operation."""


def raise_if_training_cancelled(cancellation: CommandCancellation | None) -> None:
    if cancellation is not None and cancellation.is_requested:
        raise RvcTrainingCancelled("RVC training was stopped.")
