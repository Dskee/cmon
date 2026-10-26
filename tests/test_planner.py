"""采集计划：价格 2 小时一档，标题 / 描述 / 评价合并成天级一档。"""
from datetime import datetime, timedelta

from cmon.collect.planner import DAILY, PRICE, Planner, in_active_hours

T0 = datetime(2026, 10, 27, 8, 0, 0)


def test_daily_fields_merge_to_the_shortest_period():
    planner = Planner({"price": 120, "title": 1440, "desc": 720, "review": 1440})
    assert planner.freq_min == {"price": 120, "daily": 720}


def test_daily_fields_default_to_one_day():
    planner = Planner({"price": 120})
    assert planner.freq_min == {"price": 120, "daily": 1440}


def test_due_and_mark():
    planner = Planner({"price": 120, "title": 1440, "desc": 1440, "review": 1440})
    assert planner.due("i1", PRICE, T0) is True
    planner.mark("i1", PRICE, T0)
    assert planner.due("i1", PRICE, T0 + timedelta(minutes=119)) is False
    assert planner.due("i1", PRICE, T0 + timedelta(minutes=120)) is True


def test_due_fields_only_returns_what_is_due():
    planner = Planner({"price": 120, "title": 1440, "desc": 1440, "review": 1440})
    planner.mark("i1", PRICE, T0)
    planner.mark("i1", DAILY, T0)
    assert planner.due_fields("i1", T0 + timedelta(minutes=121)) == [PRICE]
    assert set(planner.due_fields("i1", T0 + timedelta(minutes=1441))) == {PRICE, DAILY}


def test_marking_one_item_does_not_affect_another():
    planner = Planner({"price": 120, "title": 1440, "desc": 1440, "review": 1440})
    planner.mark("i1", PRICE, T0)
    assert planner.due("i2", PRICE, T0) is True


def test_active_hours_window():
    assert in_active_hours(datetime(2026, 10, 27, 8, 0)) is True
    assert in_active_hours(datetime(2026, 10, 27, 7, 59)) is False
    assert in_active_hours(datetime(2026, 10, 27, 23, 30)) is True
    assert in_active_hours(datetime(2026, 10, 27, 0, 30)) is False
    assert in_active_hours(datetime(2026, 10, 27, 20, 0), 8, 20) is False
    assert in_active_hours(datetime(2026, 10, 27, 19, 59), 8, 20) is True