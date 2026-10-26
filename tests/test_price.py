"""到手价还原：四类规则按顺序套用，误差带按最坏情况取包络。"""
from cmon.models import Coupon, RawItem
from cmon.normalize import price


def raw(**kw) -> RawItem:
    base = dict(item_id="i1", scope="competitor", source_layer="L3",
                title="测试商品", list_price=100.0)
    base.update(kw)
    return RawItem(**base)


def test_promo_price_wins_when_it_is_lower():
    final, steps, rules, band = price.restore(raw(promo_price=90.0))
    assert final == 90.0
    assert rules == ["promo"]
    assert steps[0]["value"] == 90.0
    assert band == price.BAND_CLEAN


def test_promo_price_is_ignored_when_higher():
    final, _, rules, _ = price.restore(raw(promo_price=120.0))
    assert final == 100.0
    assert rules == []


def test_platform_coupon_below_threshold_is_skipped():
    _, steps, rules, _ = price.restore(
        raw(coupons=[Coupon("CP1", "platform", 20.0, threshold=200.0)])
    )
    assert rules == []
    assert any(s["step"] == "skip" for s in steps)


def test_platform_coupon_above_threshold_applies():
    final, _, rules, _ = price.restore(
        raw(coupons=[Coupon("CP1", "platform", 20.0, threshold=80.0, allocation=20.0)])
    )
    assert final == 80.0
    assert rules == ["CP1"]


def test_unknown_allocation_widens_the_error_band():
    _, _, _, band = price.restore(
        raw(coupons=[Coupon("CP1", "platform", 20.0, threshold=0.0, allocation=None)])
    )
    assert band == price.BAND_UNKNOWN_ALLOC


def test_shop_coupon_applies_after_the_platform_layer():
    final, steps, rules, _ = price.restore(
        raw(coupons=[Coupon("SH1", "shop", 5.0, threshold=50.0),
                     Coupon("CP1", "platform", 10.0)])
    )
    assert final == 85.0
    assert rules == ["CP1", "SH1"]
    kinds = [s["step"] for s in steps]
    assert kinds.index("platform") < kinds.index("shop")


def test_full_reduction_shares_the_platform_layer():
    final, _, rules, _ = price.restore(
        raw(full_reduction=[Coupon("FR1", "full_reduction", 15.0, threshold=99.0, allocation=15.0)])
    )
    assert final == 85.0
    assert rules == ["FR1"]


def test_group_buy_is_subtracted_last():
    final, steps, rules, _ = price.restore(raw(group_buy=Coupon("GB1", "group", 12.0)))
    assert final == 88.0
    assert rules == ["GB1"]
    assert steps[-1]["step"] == "group"


def test_nothing_goes_below_zero():
    final, steps, _, _ = price.restore(raw(coupons=[Coupon("CP1", "platform", 500.0)]))
    assert final == 0.0
    assert steps[-1]["step"] == "clamp"


def test_missing_list_price_returns_none_with_widest_band():
    final, steps, rules, band = price.restore(raw(list_price=None))
    assert final is None
    assert steps == [] and rules == []
    assert band == price.BAND_MISSING_RULE


def test_within_band_absorbs_the_error_margin():
    assert price.within_band(100.0, 103.0, 0.03) is True
    assert price.within_band(100.0, 104.0, 0.03) is False
    assert price.within_band(0.0, 0.0, 0.03) is True