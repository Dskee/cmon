"""标题归一化：不做分词，只做单位统一和词表匹配，判定用集合差集。"""
from cmon.normalize import text


def test_normalize_joins_capacity_units():
    assert text.normalize("128 G 内存") == "128gb 内存"
    assert text.normalize("12+256 G 存储") == "12+256gb 存储"


def test_normalize_collapses_whitespace():
    assert text.normalize("  陶瓷   马克杯 ") == "陶瓷 马克杯"


def test_terms_finds_selling_points_and_specs():
    found = text.terms("限时直降 128G 包邮")
    assert {"限时", "直降", "包邮", "128gb"} <= found


def test_diff_reports_added_and_removed():
    change = text.diff("陶瓷马克杯 350ml", "陶瓷马克杯 350ml 限时 直降 包邮")
    assert {"限时", "直降", "包邮"} <= set(change["added"])
    assert change["removed"] == []


def test_diff_sees_removed_terms():
    change = text.diff("陶瓷马克杯 350ml 限时 直降", "陶瓷马克杯 350ml")
    assert {"限时", "直降"} <= set(change["removed"])
    assert change["added"] == []


def test_price_war_terms_only_counts_war_signals():
    assert text.price_war_terms("限时直降 包邮 现货") == {"限时", "直降"}


def test_unit_spelling_differences_do_not_count_as_changes():
    assert text.diff("陶瓷马克杯 350ml", "陶瓷马克杯 350 ML") == {"added": [], "removed": []}