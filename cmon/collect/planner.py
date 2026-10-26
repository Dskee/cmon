"""采集计划：决定这一刻谁该被采。

价格 2 小时一轮，标题 / 描述 / 评价一天一次。夜间降频由调用方按营业窗口判断，
计划器只回答"这个字段到点没有"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

PRICE = "price"
DAILY = "daily"
FIELDS = (PRICE, DAILY)


@dataclass
class Planner:
    freq_min: dict[str, int]
    _last: dict[tuple[str, str], datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 标题 / 描述 / 评价同页同请求，按最短周期合并成一档，避免重复计数
        daily = min(self.freq_min.get(k, 1440) for k in ("title", "desc", "review"))
        self.freq_min = {"price": self.freq_min["price"], "daily": daily}

    def due(self, item_id: str, field_name: str, now: datetime) -> bool:
        last = self._last.get((item_id, field_name))
        if last is None:
            return True
        period = timedelta(minutes=self.freq_min[field_name])
        return now - last >= period

    def mark(self, item_id: str, field_name: str, now: datetime) -> None:
        self._last[(item_id, field_name)] = now

    def due_fields(self, item_id: str, now: datetime) -> list[str]:
        return [f for f in FIELDS if self.due(item_id, f, now)]


def in_active_hours(now: datetime, start_hour: int = 8, end_hour: int = 24) -> bool:
    """营业窗口。夜间只保留低频字段，价格类停采。"""
    h = now.hour
    if end_hour == 24:
        return h >= start_hour
    return start_hour <= h < end_hour