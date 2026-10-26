"""三层限流的边界：全局 QPS、来源 QPS、商品级最小间隔，任一先到就等它。"""
from datetime import datetime, timedelta

import pytest

from cmon.collect.limiter import Bucket, Limiter

T0 = datetime(2026, 10, 27, 8, 0, 0)


def test_bucket_starts_full_then_paces_one_token_per_second():
    bucket = Bucket(rate=1.0, capacity=1.0)
    assert bucket.ready_at(T0) == T0
    bucket.consume(T0)
    assert bucket.ready_at(T0 + timedelta(seconds=0.4)) == T0 + timedelta(seconds=1)


def test_token_never_exceeds_capacity():
    bucket = Bucket(rate=10.0, capacity=2.0)
    bucket.ready_at(T0)
    bucket.consume(T0)
    bucket.consume(T0)
    assert bucket.ready_at(T0 + timedelta(hours=1)) == T0 + timedelta(hours=1)
    assert bucket.ready_at(T0 + timedelta(hours=1, seconds=1)) == T0 + timedelta(hours=1, seconds=1)


def test_global_qps_paces_consecutive_items():
    # 来源级放宽到 50 QPS，让全局桶成为唯一约束
    limiter = Limiter(global_qps=2.0, source_qps=50.0, item_interval_min=0)
    times = [limiter.reserve(T0, "mock", f"i{n}") for n in range(5)]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    # 桶容量 2，前两个可以先走，之后稳定 2 QPS
    for gap in gaps[2:]:
        assert gap == pytest.approx(0.5, abs=0.02)


def test_same_item_respects_min_interval():
    limiter = Limiter(global_qps=100.0, source_qps=100.0, item_interval_min=30)
    first = limiter.reserve(T0, "mock", "i1")
    second = limiter.reserve(T0, "mock", "i1")
    assert second - first == timedelta(minutes=30)


def test_min_interval_is_per_item():
    limiter = Limiter(global_qps=1000.0, source_qps=1000.0, item_interval_min=30)
    limiter.reserve(T0, "mock", "i1")
    other = limiter.reserve(T0, "mock", "i2")
    assert (other - T0).total_seconds() < 0.01


def test_earliest_takes_the_latest_constraint():
    limiter = Limiter(global_qps=1.0, source_qps=1.0, item_interval_min=60)
    assert limiter.reserve(T0, "mock", "i1") == T0
    assert limiter.earliest(T0, "mock", "i1") == T0 + timedelta(minutes=60)


def test_reserved_time_is_monotonic():
    limiter = Limiter(global_qps=2.0, source_qps=1.0, item_interval_min=30)
    times = [limiter.reserve(T0, "mock", f"i{n}") for n in range(6)]
    assert times == sorted(times)
    # 来源级 1 QPS 是这组里最紧的约束，6 个请求至少摊到 5 秒
    assert (times[-1] - times[0]).total_seconds() >= 5