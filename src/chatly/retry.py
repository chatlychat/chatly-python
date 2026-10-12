"""The retry policy. Contract §4.

Retry only what is safe — a connection failure, a 429, a 5xx — with
exponential backoff plus jitter, three attempts by default, honouring
``Retry-After`` when the server sent one. A retried write reuses the
``Idempotency-Key`` of the attempt that failed; that is the entire reason the
header exists, and it is enforced in :mod:`chatly._transport` by minting the
key once per *call* rather than once per *attempt*.

Never retry a 4xx that is not 429. A 400, 404 or 422 will fail identically on
every attempt, so retrying one only delays the error the caller is waiting
for — and a 409 from an idempotency mismatch is a *statement* that the retry
must stop.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .errors import APIError, RateLimitError, ServerError, TransportError

#: Statuses that are safe to retry. Nothing else is.
RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 507, 509, 598, 599})


@dataclass(frozen=True)
class RetryPolicy:
    """How many times, and how long to wait.

    Args:
        max_attempts: total attempts including the first. ``3`` means one
            call and up to two retries. ``1`` disables retrying.
        initial_backoff: seconds before the second attempt.
        max_backoff: ceiling for a single wait, after the exponential growth
            and before jitter.
        multiplier: growth factor per attempt.
        jitter: when true, the wait is a random value in ``[0, computed]``
            ("full jitter"). Tests set this false for determinism.
        respect_retry_after: when true, a ``Retry-After`` the server sent
            overrides the computed backoff, clamped to ``max_retry_after``.
        max_retry_after: refuse to sleep longer than this on a server's say-so.
            A misconfigured proxy answering ``Retry-After: 86400`` must not
            park a request handler for a day.
    """

    max_attempts: int = 3
    initial_backoff: float = 0.5
    max_backoff: float = 8.0
    multiplier: float = 2.0
    jitter: bool = True
    respect_retry_after: bool = True
    max_retry_after: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be >= 1")
        if self.initial_backoff < 0 or self.max_backoff < 0:
            raise ValueError("RetryPolicy backoff values must be >= 0")

    def should_retry(self, error: BaseException, attempt: int) -> bool:
        """Should ``attempt`` (1-based, the one that just failed) be retried?"""
        if attempt >= self.max_attempts:
            return False
        if isinstance(error, TransportError):
            return True
        if isinstance(error, (RateLimitError, ServerError)):
            return True
        if isinstance(error, APIError):
            return error.status in RETRYABLE_STATUSES
        return False

    def backoff(self, attempt: int, *, retry_after: Optional[float] = None) -> float:
        """Seconds to wait after ``attempt`` (1-based) failed."""
        if retry_after is not None and self.respect_retry_after:
            return min(float(retry_after), self.max_retry_after)
        computed = min(self.initial_backoff * (self.multiplier ** (attempt - 1)), self.max_backoff)
        if self.jitter:
            return random.uniform(0.0, computed)
        return computed


#: No retries at all. Pass as ``retry=NO_RETRIES`` when the caller has its own
#: outer retry loop and does not want two of them multiplying.
NO_RETRIES = RetryPolicy(max_attempts=1)
