"""数据源接口。

Pipeline 只跟这里定义的三个成员打交道，所以接真实源是换一个对象，不是改一条链路：

    world.source_name                  来源名，用于来源级限流和状态机分组
    world.apply_timeline(elapsed)      推进到第几小时，返回本次生效的变更说明（真实源返回空列表）
    world.fetch(item_id, elapsed)      -> FetchResult

真实源要做的只有两件事：把平台响应映射成 RawItem，把失败映射成 FetchResult 的
error / retryable / empty。字段口径见 cmon/models.py，方案第五节的快照 schema 是它的文档版。

注意 empty 这个字段：HTTP 200 但解析不出字段时必须置 True，不能返回 ok=False 也不算成功。
把"拿到了空数据"当成"没变化"，是这类系统最贵的一种错。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import FetchResult


@runtime_checkable
class DataSource(Protocol):
    source_name: str

    def apply_timeline(self, elapsed_hours: float) -> list[str]: ...

    def fetch(self, item_id: str, elapsed_hours: float) -> FetchResult: ...