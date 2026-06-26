"""Auto-retry for transient model errors.

A failed turn surfaces as a terminal ``error`` :class:`StreamEvent` (the
final :class:`AssistantMessage` carries ``stopReason == "error"``). That makes retry a clean
wrapper around the per-turn stream: if a turn ends in ``error`` (not a user ``aborted``),
wait a backed-off delay and stream the same turn again, up to ``max_retries`` times.

The policy is a plain dataclass so it's easy to read, construct, and test; the loop owns the
actual stream-and-retry loop (see :func:`agent.loop.run_agent`).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RetryPolicy"]


@dataclass(frozen=True)
class RetryPolicy:
    """How to retry a turn that ends in a transient model error.

    Args:
        max_retries: how many *additional* attempts after the first (0 disables retry).
        base_delay: seconds before the first retry.
        backoff: multiplier applied to the delay each subsequent attempt (exponential).
        max_delay: cap on the per-attempt delay.
    """

    max_retries: int = 2
    base_delay: float = 1.0
    backoff: float = 2.0
    max_delay: float = 30.0

    def delay_for(self, attempt: int) -> float:
        """Delay (seconds) before retry ``attempt`` (1-indexed)."""
        delay = self.base_delay * (self.backoff ** (attempt - 1))
        return min(delay, self.max_delay)
