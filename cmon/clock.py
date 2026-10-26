"""可注入时钟。

方案里"持续 2 小时"按时间戳之差判定，如果时钟是真实的，验证一条规则要等两小时。
把时钟抽象出来，模拟时钟可以让 8:00 到 20:00 在毫秒内跑完，判定逻辑一行都不用改。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta


class Clock:
    def now(self) -> datetime:  # pragma: no cover - 接口
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:  # pragma: no cover - 接口
        raise NotImplementedError


class RealClock(Clock):
    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime.now().replace(microsecond=0)

    def now(self) -> datetime:
        return self._t

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
        self._t = self._t + timedelta(seconds=seconds)


class SimClock(Clock):
    """模拟时钟：sleep 只推进内部时间，不真的等待。"""

    def __init__(self, start: datetime) -> None:
        self._t = start.replace(microsecond=0)

    def now(self) -> datetime:
        return self._t

    def sleep(self, seconds: float) -> None:
        self._t = self._t + timedelta(seconds=seconds)

    def advance(self, **kwargs) -> None:
        self._t = self._t + timedelta(**kwargs)