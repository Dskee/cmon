"""三层去重。

L1 跨租户：按商品维度建采集计划，一个周期内只采一次，结果广播给所有租户。
L2 TTL：同一来源同一参数 90 分钟内不重复请求。
L3 内容指纹：标题 + 到手价 + 券集合 + 库存档位 完全一致就跳过下游分析。

去重键是「商品 ID + 采集周期」，不含租户维度——含了跨租户就永远命中不了。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import FetchResult, Snapshot


@dataclass
class DedupStats:
    l1_hits: int = 0
    l2_hits: int = 0
    l3_hits: int = 0
    requests: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "l1_cross_tenant_hits": self.l1_hits,
            "l2_ttl_hits": self.l2_hits,
            "l3_fingerprint_hits": self.l3_hits,
        }


@dataclass
class Deduplicator:
    ttl_min: int = 90
    stats: DedupStats = field(default_factory=DedupStats)
    _l1: dict[tuple[str, str], FetchResult] = field(default_factory=dict)
    _l2: dict[str, tuple[datetime, FetchResult]] = field(default_factory=dict)

    @staticmethod
    def cycle_key(item_id: str, now: datetime, period_hours: int = 2) -> tuple[str, str]:
        bucket = int(now.timestamp() // (period_hours * 3600))
        return item_id, str(bucket)

    def l1_get(self, item_id: str, now: datetime, period_hours: int = 2) -> FetchResult | None:
        key = self.cycle_key(item_id, now, period_hours)
        hit = self._l1.get(key)
        if hit is not None:
            self.stats.l1_hits += 1
        return hit

    def l1_put(self, item_id: str, now: datetime, result: FetchResult, period_hours: int = 2) -> None:
        self._l1[self.cycle_key(item_id, now, period_hours)] = result

    def l2_get(self, key: str, now: datetime) -> FetchResult | None:
        hit = self._l2.get(key)
        if hit is None:
            return None
        at, result = hit
        if now - at > timedelta(minutes=self.ttl_min):
            del self._l2[key]
            return None
        self.stats.l2_hits += 1
        return result

    def l2_put(self, key: str, now: datetime, result: FetchResult) -> None:
        self._l2[key] = (now, result)

    def l3_same(self, snapshot: Snapshot, previous_fingerprint: str | None) -> bool:
        if not previous_fingerprint or not snapshot.fingerprint:
            return False
        if snapshot.fingerprint == previous_fingerprint:
            self.stats.l3_hits += 1
            return True
        return False