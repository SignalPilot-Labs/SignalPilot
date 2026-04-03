"""Simple in-memory sliding window rate limiter for key management endpoints."""

import time
from collections import deque

from fastapi import HTTPException


class RateLimiter:
    """Global sliding window rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60, time_func=None):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._time_func = time_func or time.time
        self._timestamps: deque[float] = deque()

    def _purge_expired(self) -> None:
        cutoff = self._time_func() - self.window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def check(self) -> float | None:
        """Check if request is allowed. Returns None if allowed, or Retry-After seconds if blocked."""
        self._purge_expired()
        if len(self._timestamps) >= self.max_requests:
            retry_after = self._timestamps[0] + self.window_seconds - self._time_func()
            return max(1, int(retry_after) + 1)
        self._timestamps.append(self._time_func())
        return None

    def reset(self) -> None:
        """Clear all tracked requests. Used in tests."""
        self._timestamps.clear()


# Singleton for /keys/* endpoints
keys_limiter = RateLimiter(max_requests=10, window_seconds=60)


async def check_keys_rate_limit():
    """FastAPI dependency that enforces rate limiting on key management endpoints."""
    retry_after = keys_limiter.check()
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded on key management endpoints",
            headers={"Retry-After": str(int(retry_after))},
        )
