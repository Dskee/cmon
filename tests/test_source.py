"""数据源契约：MockWorld 满足它，真实源也应该满足它。

真正的价值不在这个 Protocol 本身，而在它把"换源要动哪里"固定成三行：
source_name / apply_timeline / fetch。多变一个方法，就说明耦合漏进来了。
"""
from cmon.mock.scenarios import get
from cmon.mock.source import MockWorld
from cmon.models import FetchResult, RawItem
from cmon.source import DataSource


class FakeSource:
    """最小真实源的样子：没有时间线，只有取数。"""

    source_name = "fake-openapi"

    def apply_timeline(self, elapsed_hours: float) -> list[str]:
        return []

    def fetch(self, item_id: str, elapsed_hours: float) -> FetchResult:
        return FetchResult(
            ok=True,
            raw=RawItem(item_id=item_id, scope="competitor", source_layer="L1",
                        title="测试商品", list_price=99.0),
            latency_ms=42,
        )


def test_mock_world_satisfies_the_data_source_protocol():
    assert isinstance(MockWorld(get("price-drop")), DataSource)


def test_a_minimal_source_needs_only_three_members():
    src = FakeSource()
    assert isinstance(src, DataSource)
    assert src.apply_timeline(3.0) == []

    result = src.fetch("X1", 3.0)
    assert result.ok and not result.empty
    assert result.raw is not None and result.raw.item_id == "X1"