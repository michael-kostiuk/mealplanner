"""Global, in-memory login limiter. Rationale: see app/auth/__init__.py."""

import asyncio
import time
from collections.abc import Callable

WINDOW_SECONDS = 3600
MAX_FAILURES = 3
BASE_LOCK_SECONDS = 3600


class LoginLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._failures: list[float] = []
        self._level = 0
        self._locked_until = 0.0
        # Callers hold this for the whole attempt so concurrent guesses can't slip past the check.
        self.lock = asyncio.Lock()

    def locked_for(self) -> float:
        return max(0.0, self._locked_until - self._clock())

    def record_failure(self) -> None:
        now = self._clock()
        self._failures = [t for t in self._failures if now - t < WINDOW_SECONDS]
        self._failures.append(now)
        if self._level > 0:
            self._level += 1
            self._locked_until = now + BASE_LOCK_SECONDS * 2 ** (self._level - 1)
        elif len(self._failures) >= MAX_FAILURES:
            self._level = 1
            self._locked_until = now + BASE_LOCK_SECONDS

    def record_success(self) -> None:
        self._failures = []
        self._level = 0
        self._locked_until = 0.0


login_limiter = LoginLimiter()
