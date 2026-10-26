"""到手价还原。

方案第二节的那张规则表落成代码：四类规则，按套用顺序逐层算，每层落一个中间值。
误差不从"大约"来，从三处具体地方来——规则不全、分摊未知、时间边界——按最坏情况取包络。
"""
from __future__ import annotations

from typing import Any

from ..models import Coupon, RawItem

# 误差来源权重：每一处不确定把区间撑大一点，最后取上界，不求和
BAND_CLEAN = 0.01        # 规则齐全、分摊明确
BAND_UNKNOWN_ALLOC = 0.02  # 有跨店满减但分摊未知
BAND_MISSING_RULE = 0.03   # 只拿到标价、拿不到券


def restore(raw: RawItem) -> tuple[float | None, list[dict[str, Any]], list[str], float]:
    """返回 (到手价, 中间值, 命中的规则 id, 误差带)。"""
    if raw.list_price is None:
        return None, [], [], BAND_MISSING_RULE

    intermediate: list[dict[str, Any]] = []
    rule_ids: list[str] = []
    band = BAND_CLEAN

    # 第 1 步：标价 / 限时价，二者取低
    base = raw.list_price
    if raw.promo_price is not None and raw.promo_price < base:
        rule_ids.append("promo")
        base = raw.promo_price
    intermediate.append({"step": "base", "rule": "标价与限时价取低", "value": round(base, 2)})

    # 第 2 步：平台券与跨店满减，按门槛判断是否生效
    for cp in _all(raw.coupons, raw.full_reduction):
        if cp.kind not in ("platform", "full_reduction"):
            continue
        if base < cp.threshold:
            intermediate.append(
                {"step": "skip", "rule": f"{cp.coupon_id} 未达门槛 {cp.threshold}", "value": round(base, 2)}
            )
            continue
        amount = cp.allocation if cp.allocation is not None else cp.amount
        if cp.allocation is None:
            band = max(band, BAND_UNKNOWN_ALLOC)
        base -= amount
        rule_ids.append(cp.coupon_id)
        intermediate.append(
            {"step": "platform", "rule": f"{cp.coupon_id} -{amount:g}", "value": round(base, 2)}
        )

    # 第 3 步：店铺券
    for cp in raw.coupons:
        if cp.kind != "shop":
            continue
        if base < cp.threshold:
            continue
        base -= cp.amount
        rule_ids.append(cp.coupon_id)
        intermediate.append(
            {"step": "shop", "rule": f"{cp.coupon_id} -{cp.amount:g}", "value": round(base, 2)}
        )

    # 第 4 步：拼团 / 预售，独立计算
    if raw.group_buy is not None:
        base -= raw.group_buy.amount
        rule_ids.append(raw.group_buy.coupon_id)
        intermediate.append(
            {"step": "group", "rule": f"{raw.group_buy.coupon_id} -{raw.group_buy.amount:g}",
             "value": round(base, 2)}
        )

    if base < 0:
        base = 0.0
        intermediate.append({"step": "clamp", "rule": "负数截零，说明券数据有问题", "value": 0.0})

    return round(base, 2), intermediate, rule_ids, band


def _all(a: list[Coupon], b: list[Coupon]) -> list[Coupon]:
    return list(a) + list(b)


def within_band(a: float, b: float, band: float) -> bool:
    """两个到手价之差是否落在误差带内——带内视为没变化，避免把误差当事件。"""
    if a == 0:
        return abs(b) <= band
    return abs(a - b) / abs(a) <= band