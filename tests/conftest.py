"""测试夹具与构造器。

所有测试都跑在 SimClock / 临时 SQLite 上，不碰网络、不碰真实时钟——
"持续 2 小时"这种判断必须能在毫秒内验证完，否则没人愿意写这类测试。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmon.config import JudgeConfig  # noqa: E402
from cmon.db import Store  # noqa: E402
from cmon.models import RawItem, Snapshot  # noqa: E402
from cmon.normalize import snapshot as snap_mod  # noqa: E402

T0 = datetime(2026, 10, 27, 8, 0, 0)


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def judge_cfg():
    return JudgeConfig(
        price_drop_pct=0.05,
        sustain_hours=2,
        baseline_days=7,
        title_token_new_min=2,
        review_topic_jump_pp=0.20,
        review_min_samples=20,
        cooldown_hours=24,
    )


def make_raw(item_id: str = "C1", title: str = "陶瓷马克杯 350ml",
             list_price: float | None = 100.0, **kw) -> RawItem:
    base = dict(
        item_id=item_id,
        scope="competitor",
        source_layer="L3",
        title=title,
        list_price=list_price,
        promo_price=None,
        coupons=[],
        full_reduction=[],
        group_buy=None,
        stock_tier="in_stock",
        stock_raw=100,
        desc_hash="d1",
        image_hashes=["i1"],
        reviews={},
    )
    base.update(kw)
    return RawItem(**base)


def make_snap(at: datetime = T0, **kw) -> Snapshot:
    return snap_mod.build(make_raw(**kw), at)