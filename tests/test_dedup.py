"""三层去重：跨租户、TTL、内容指纹。

关键性质是"去重键不含租户"——一旦含了，跨租户永远命中不了，省下的 30% 请求就没了。
"""
from datetime import datetime, timedelta

from cmon.collect.dedup import Deduplicator
from cmon.models import FetchResult
from tests.conftest import make_snap

T0 = datetime(2026, 10, 27, 8, 0, 0)


def test_l1_hits_within_the_same_cycle_and_misses_the_next():
    dedup = Deduplicator()
    result = FetchResult(ok=True)
    dedup.l1_put("i1", T0, result)
    assert dedup.l1_get("i1", T0 + timedelta(minutes=90)) is result
    assert dedup.l1_get("i1", T0 + timedelta(hours=2)) is None
    assert dedup.stats.l1_hits == 1


def test_cycle_key_has_no_tenant_dimension():
    key = Deduplicator.cycle_key("i1", T0)
    assert key == ("i1", str(int(T0.timestamp() // 7200)))


def test_l2_expires_after_ttl():
    dedup = Deduplicator(ttl_min=90)
    result = FetchResult(ok=True)
    dedup.l2_put("k", T0, result)
    assert dedup.l2_get("k", T0 + timedelta(minutes=89)) is result
    assert dedup.l2_get("k", T0 + timedelta(minutes=91)) is None


def test_l3_matches_only_on_identical_fingerprint():
    dedup = Deduplicator()
    snap = make_snap(item_id="i1", list_price=100.0)
    assert dedup.l3_same(snap, None) is False
    assert dedup.l3_same(snap, snap.fingerprint) is True
    assert dedup.stats.l3_hits == 1


def test_fingerprint_ignores_exact_stock_value():
    # 库存取档位不取精确值，否则每轮都在变，指纹永不重复
    a = make_snap(item_id="i1", stock_tier="low", stock_raw=7)
    b = make_snap(item_id="i1", stock_tier="low", stock_raw=3)
    assert a.fingerprint == b.fingerprint


def test_fingerprint_changes_with_price():
    a = make_snap(item_id="i1", list_price=100.0)
    b = make_snap(item_id="i1", list_price=99.0)
    assert a.fingerprint != b.fingerprint