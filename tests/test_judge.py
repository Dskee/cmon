"""事件判定：纯规则，不调模型。重点是"持续"和"基线"这两处最容易算错的地方。"""
from datetime import datetime, timedelta

from cmon.judge.rules import Judge
from tests.conftest import make_snap

T0 = datetime(2026, 10, 27, 8, 0, 0)


def seed(store, price: float, at: datetime, item_id: str = "C1") -> None:
    store.add_snapshot(make_snap(at, item_id=item_id, list_price=price))


def test_price_drop_needs_two_hours_below_baseline(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    seed(store, 100.0, T0 - timedelta(hours=3))
    seed(store, 100.0, T0 - timedelta(hours=1))

    assert judge.evaluate(make_snap(T0, list_price=88.0), T0) == []
    assert judge.evaluate(make_snap(T0 + timedelta(hours=1), list_price=88.0),
                          T0 + timedelta(hours=1)) == []

    events = judge.evaluate(make_snap(T0 + timedelta(hours=2), list_price=88.0),
                            T0 + timedelta(hours=2))
    assert [e.event_type for e in events] == ["PRICE_DROP"]
    assert events[0].evidence["delta_pct"] == -12.0
    assert events[0].evidence["sustained_hours"] == 2.0


def test_baseline_ignores_prices_after_the_drop_began(store, judge_cfg):
    """回归测试：跌后的价不能参与基线，否则跌幅越算越小，最后自己把自己抹平。"""
    judge = Judge(judge_cfg, store)
    seed(store, 109.0, T0 - timedelta(hours=3))
    seed(store, 109.0, T0 - timedelta(hours=2))
    assert judge.evaluate(make_snap(T0, list_price=98.0), T0) == []

    seed(store, 98.0, T0 + timedelta(hours=1))
    seed(store, 98.0, T0 + timedelta(hours=1, minutes=30))

    at = T0 + timedelta(hours=2)
    events = judge.evaluate(make_snap(at, list_price=98.0), at)
    assert events[0].evidence["baseline"] == 109.0
    assert events[0].evidence["delta_pct"] == -10.09


def test_small_move_inside_threshold_produces_nothing(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    seed(store, 100.0, T0 - timedelta(hours=3))
    seed(store, 100.0, T0 - timedelta(hours=2))
    for h in (0, 1, 2, 3):
        at = T0 + timedelta(hours=h)
        assert judge.evaluate(make_snap(at, list_price=97.0), at) == []


def test_price_recovery_clears_the_timer(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    seed(store, 100.0, T0 - timedelta(hours=2))
    judge.evaluate(make_snap(T0, list_price=88.0), T0)
    judge.evaluate(make_snap(T0 + timedelta(hours=1), list_price=99.0), T0 + timedelta(hours=1))
    assert store.get_item_state("C1")["below_since"] is None


def test_cooldown_blocks_a_second_event_within_24h(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    seed(store, 100.0, T0 - timedelta(hours=3))
    seed(store, 100.0, T0 - timedelta(hours=2))
    judge.evaluate(make_snap(T0, list_price=88.0), T0)
    first = judge.evaluate(make_snap(T0 + timedelta(hours=2), list_price=88.0),
                           T0 + timedelta(hours=2))
    assert len(first) == 1

    second = judge.evaluate(make_snap(T0 + timedelta(hours=5), list_price=88.0),
                            T0 + timedelta(hours=5))
    assert second == []

    # 再持续 2 小时，跌幅、持续都满足，但离上一次事件不到 24 小时，仍然不出第二张卡
    third = judge.evaluate(make_snap(T0 + timedelta(hours=7), list_price=88.0),
                           T0 + timedelta(hours=7))
    assert third == []


def test_empty_snapshot_never_produces_events(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    seed(store, 100.0, T0 - timedelta(hours=2))
    empty = make_snap(T0, list_price=None)
    assert empty.quality_ok is False
    assert judge.evaluate(empty, T0) == []


def test_title_change_requires_two_new_terms(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    store.save_item_state("C1", last_title="陶瓷马克杯 350ml")
    one = judge.evaluate(make_snap(T0, item_id="C1", title="陶瓷马克杯 350ml 限时"), T0)
    assert one == []

    store.save_item_state("C2", last_title="陶瓷马克杯 350ml")
    two = judge.evaluate(make_snap(T0, item_id="C2", title="陶瓷马克杯 350ml 限时 直降"), T0)
    assert [e.event_type for e in two] == ["TITLE_CHANGE"]
    assert set(two[0].evidence["price_war_terms"]) == {"限时", "直降"}


def test_stock_out_event(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    store.save_item_state("C1", last_stock="in_stock")
    events = judge.evaluate(make_snap(T0, stock_tier="out", stock_raw=0), T0)
    assert [e.event_type for e in events] == ["STOCK_OUT"]


def test_review_topic_shift_needs_samples_and_a_twenty_point_jump(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    store.save_item_state("C1", last_reviews=str({"topics": {"尺码": 0.10, "物流": 0.30}}))
    good = judge.evaluate(
        make_snap(T0, reviews={"total": 344, "negative": 68,
                               "topics": {"尺码": 0.60, "物流": 0.15}}), T0)
    assert [e.event_type for e in good] == ["REVIEW_TOPIC_SHIFT"]

    store.save_item_state("C2", last_reviews=str({"topics": {"尺码": 0.10}}))
    few = judge.evaluate(
        make_snap(T0, item_id="C2", reviews={"total": 344, "negative": 5,
                                             "topics": {"尺码": 0.60}}), T0)
    assert few == []


def test_desc_change_event(store, judge_cfg):
    judge = Judge(judge_cfg, store)
    store.save_item_state("C1", last_desc_hash="old")
    events = judge.evaluate(make_snap(T0, desc_hash="new"), T0)
    assert [e.event_type for e in events] == ["DESC_CHANGE"]