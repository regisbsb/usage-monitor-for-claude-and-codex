"""Timing policy for explicit refreshes of a provider's cached usage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

__all__ = ['ManualRefreshPolicy', 'RESET_BUFFER', 'reset_offsets']

# Allow the provider time to publish the next window after a reset.
RESET_BUFFER = 5
_MINIMUM_INTERVAL = 15


def reset_offsets(usage: dict[str, Any], now: datetime) -> list[float]:
    """Return seconds until each known reset, including recently elapsed resets."""
    offsets = []
    for entry in usage.values():
        if not isinstance(entry, dict) or not entry.get('resets_at'):
            continue
        try:
            reset = datetime.fromisoformat(entry['resets_at'])
            offsets.append((reset - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            continue
    return offsets


@dataclass
class ManualRefreshPolicy:
    """Per-cache refresh timing, read and written under that cache's state lock."""

    last_completion: float | None = None
    last_manual_attempt: float | None = None

    def wait(
        self, usage: dict[str, Any], *, now: float, monotonic_now: float, poll_fast: int, backoff_until: float,
    ) -> tuple[str | None, float | None]:
        """Return the current wait reason and its wall-clock deadline.

        The two cooldowns use monotonic time. The reset check uses actual
        reset timestamps: a manual request just before reset could consume
        the normal cooldown and delay the confirming poll.
        """
        if now < backoff_until:
            return 'backoff', backoff_until

        offsets = reset_offsets(usage, datetime.fromtimestamp(now, timezone.utc))
        protected = [offset for offset in offsets if -RESET_BUFFER < offset < poll_fast]
        if protected:
            return 'reset', now + max(protected) + RESET_BUFFER

        remaining = 0.0
        if self.last_completion is not None:
            remaining = _MINIMUM_INTERVAL - (monotonic_now - self.last_completion)
        if self.last_manual_attempt is not None:
            remaining = max(remaining, poll_fast - (monotonic_now - self.last_manual_attempt))
        return ('cooldown', now + remaining) if remaining > 0 else (None, None)
