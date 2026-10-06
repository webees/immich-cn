from __future__ import annotations

import pytest

from immich_cn.rate_limit import RateLimiter


def test_rate_limiter_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="calls"):
        RateLimiter(0)
    with pytest.raises(ValueError, match="calls"):
        RateLimiter(-1)
    with pytest.raises(ValueError, match="period"):
        RateLimiter(1, period=0)
    with pytest.raises(ValueError, match="period"):
        RateLimiter(1, period=-0.1)


def test_rate_limiter_releases_slot_at_window_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        # 给零等待变异一个最小推进量，避免测试在无限循环中挂起。
        now += max(seconds, 0.001)

    monkeypatch.setattr("immich_cn.rate_limit.time.monotonic", monotonic)
    monkeypatch.setattr("immich_cn.rate_limit.time.sleep", sleep)

    limiter = RateLimiter(2, period=1.0)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    # 第三次调用必须等到 t=1，并且恰好到窗口边界时释放旧时间戳。
    assert now == pytest.approx(1.0)
