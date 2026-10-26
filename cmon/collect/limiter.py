"""三层限流。

令牌桶 + 商品级最小间隔。不 sleep，而是返回"最早可以出发的时刻"，由调用方推进时钟——
这样真实运行时是 sleep，模拟运行时时钟直接跳过去，同一段代码两种用法。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Bucket:
    rate: float          # 每秒补充的令牌数
    capacity: float      # 桶容量
    tokens: float = 0.0
    _last: datetime | None = None

    def _refill(self, now: datetime) -> None:
        if self._last is None:
            self._last = now
            self.tokens = self.capacity
            return
        elapsed = (now - self._last).total_seconds()
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self._last = now

    def ready_at(self, now: datetime) -> datetime:
        if self._last is None:
            self._last = now
            self.tokens = self.capacity
        # 上一次已经排到未来时，下一次要接着那个时刻往后排，不能从"现在"重新算，
        # 否则同一秒里所有请求都会被安排到同一个未来时刻，限流等于没做。
        effective = max(now, self._last)
        if effective > self._last:
            elapsed = (effective - self._last).total_seconds()
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self._last = effective
        if self.tokens >= 1.0:
            return effective
        need = 1.0 - self.tokens
        return effective + timedelta(seconds=need / self.rate)

    def consume(self, now: datetime) -> None:
        self._refill(now)
        self.tokens = max(0.0, self.tokens - 1.0)


class Limiter:
    def __init__(self, global_qps: float, source_qps: float, item_interval_min: int) -> None:
        self.global_bucket = Bucket(rate=global_qps, capacity=max(1.0, global_qps))
        self.source_buckets: dict[str, Bucket] = {}
        self.source_qps = source_qps
        self.item_interval = timedelta(minutes=item_interval_min)
        self.item_next_ok: dict[str, datetime] = {}
        self.issued: list[datetime] = []

    def _source(self, source: str) -> Bucket:
        if source not in self.source_buckets:
            self.source_buckets[source] = Bucket(rate=self.source_qps, capacity=1.0)
        return self.source_buckets[source]

    def earliest(self, now: datetime, source: str, item_id: str) -> datetime:
        candidates = [
            now,
            self.global_bucket.ready_at(now),
            self._source(source).ready_at(now),
            self.item_next_ok.get(item_id, now),
        ]
        return max(candidates)

    def reserve(self, now: datetime, source: str, item_id: str) -> datetime:
        """占用一个额度，返回实际可出发时刻。"""
        at = self.earliest(now, source, item_id)
        self.global_bucket.consume(at)
        self._source(source).consume(at)
        self.item_next_ok[item_id] = at + self.item_interval
        self.issued.append(at)
        return at

    def peak_qps(self, window_sec: float = 1.0) -> float:
        """实测峰值：任意 window_sec 秒滑窗里最多发出过几个请求。

        令牌桶只保证平均速率，峰值要靠事后统计才知道有没有抖出去——
        实验报告里那个"实测峰值 QPS"就是这个数。
        """
        if not self.issued:
            return 0.0
        times = sorted(self.issued)
        best = 0
        left = 0
        for right, t in enumerate(times):
            while (t - times[left]).total_seconds() > window_sec:
                left += 1
            best = max(best, right - left + 1)
        return best / window_sec