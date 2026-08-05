from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.app_update import UpdatePlan


ACTIVE_POLL_SECONDS = 120.0
INACTIVE_POLL_SECONDS = 600.0
ACTIVATION_CHECK_SECONDS = 30.0
MAX_BACKOFF_SECONDS = 1800.0


@dataclass(frozen=True)
class UpdateCheckOutcome:
    plan: UpdatePlan | None
    etag: str = ""
    last_modified: str = ""
    not_modified: bool = False


@dataclass
class UpdatePollingPolicy:
    last_checked_at: float | None = None
    consecutive_failures: int = 0

    def record_success(self, now: float) -> None:
        self.last_checked_at = now
        self.consecutive_failures = 0

    def record_failure(self, now: float) -> None:
        self.last_checked_at = now
        self.consecutive_failures += 1

    def interval_seconds(self, is_active: bool) -> float:
        base = ACTIVE_POLL_SECONDS if is_active else INACTIVE_POLL_SECONDS
        backoff = 2 ** min(self.consecutive_failures, 4)
        return min(MAX_BACKOFF_SECONDS, base * backoff)

    def next_delay_ms(self, now: float, is_active: bool) -> int:
        if self.last_checked_at is None:
            return 0
        due_at = self.last_checked_at + self.interval_seconds(is_active)
        return max(0, int((due_at - now) * 1000))

    def should_check_on_activation(self, now: float) -> bool:
        return (
            self.last_checked_at is not None
            and now - self.last_checked_at >= ACTIVATION_CHECK_SECONDS
        )
