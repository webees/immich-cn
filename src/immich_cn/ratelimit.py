"""轻量限速器，避免为单一能力引入第三方依赖。"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """滑动窗口限速：在 ``period`` 秒内最多允许 ``calls`` 次调用。

    该实现是线程安全的，并且会在超限时阻塞当前线程，直到窗口滑动。
    """

    def __init__(self, calls: int, period: float = 1.0) -> None:
        if calls < 1:
            raise ValueError("calls 必须大于 0")
        if period <= 0:
            raise ValueError("period 必须大于 0")
        self._calls = calls
        self._period = period
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        horizon = now - self._period
        while self._timestamps and self._timestamps[0] <= horizon:
            self._timestamps.popleft()

    def acquire(self) -> None:
        """阻塞直到可以发起下一次调用。"""
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now)
                if len(self._timestamps) < self._calls:
                    self._timestamps.append(now)
                    return
                wait = self._period - (now - self._timestamps[0])
            if wait > 0:
                time.sleep(min(wait, self._period))

    def __enter__(self) -> RateLimiter:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        return None
