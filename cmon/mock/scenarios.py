"""事件脚本：世界在第几小时发生什么。

每个场景是一份可复现的实验脚本，跑完能拿到确定的结果。这是选择自建源的主要理由——
真实链路上你没法安排"第 2 小时竞品降价、第 6 小时返回连续 3 个 429"。
"""
from __future__ import annotations

from typing import Any

SCENARIOS: dict[str, dict[str, Any]] = {
    "price-drop": {
        "title": "竞品降价 + 差评转向尺码（方案里的示例场景）",
        "hours": 28,
        "timeline": [
            {
                "at": 2.0,
                "item": "C8848",
                "kind": "price_drop",
                "note": "C8848 标价 109→103，同时挂出 5 元平台券",
                "patch": {
                    "promo_price": 103.0,
                    "coupons": [
                        {"id": "CP5", "kind": "platform", "amount": 5.0,
                         "threshold": 99.0, "allocation": 5.0}
                    ],
                },
            },
            {
                "at": 3.0,
                "item": "C8848",
                "kind": "review_shift",
                "note": "C8848 差评主题从物流转向尺码",
                "patch": {
                    "reviews": {"window_days": 7, "total": 344, "negative": 68,
                                "topics": {"尺码": 0.60, "物流": 0.15,
                                           "色差": 0.12, "质量": 0.13}},
                },
            },
        ],
        "faults": [],
    },
    "fault-storm": {
        "title": "连续失败与验证码：验证五态状态机和探活阶梯",
        "hours": 14,
        "timeline": [],
        "faults": [
            {"at": 1.0, "item": "C1001", "kind": "http_429", "times": 3},
            {"at": 6.0, "item": "C1001", "kind": "captcha", "times": 1},
            {"at": 9.0, "item": "C1001", "kind": "timeout", "times": 1},
        ],
    },
    "empty-silent": {
        "title": "200 但字段全空：验证空数据不会被当成没变化",
        "hours": 8,
        "timeline": [],
        "faults": [
            {"at": 2.0, "item": "A1001", "kind": "empty", "times": 2},
        ],
    },
    "title-change": {
        "title": "竞品标题加入价格战信号词",
        "hours": 8,
        "timeline": [
            {
                "at": 2.0,
                "item": "C2002",
                "kind": "title_change",
                "note": "C2002 标题加入 限时 / 直降 / 包邮",
                "patch": {"title": "陶瓷马克杯 大容量 带盖勺 办公 350ml 限时直降 包邮"},
            },
        ],
        "faults": [],
    },
    "size-clearance": {
        "title": "降价 + 某一尺码卖光 + 差评转向尺码：三条证据指向同一个原因",
        "hours": 28,
        "timeline": [
            {
                "at": 2.0,
                "item": "C8848",
                "kind": "price_drop",
                "note": "C8848 标价 109→103，同时挂出 5 元平台券",
                "patch": {
                    "promo_price": 103.0,
                    "coupons": [
                        {"id": "CP5", "kind": "platform", "amount": 5.0,
                         "threshold": 99.0, "allocation": 5.0}
                    ],
                },
            },
            {
                "at": 3.0,
                "item": "C8848",
                "kind": "review_shift",
                "note": "C8848 差评主题从物流转向尺码",
                "patch": {
                    "reviews": {"window_days": 7, "total": 344, "negative": 68,
                                "topics": {"尺码": 0.60, "物流": 0.15,
                                           "色差": 0.12, "质量": 0.13}},
                },
            },
            {
                "at": 4.0,
                "item": "C8848",
                "kind": "size_out",
                "note": "C8848 XL 码卖光，其余尺码仍有货",
                "patch": {
                    "size_stock": {"M": "in_stock", "L": "in_stock",
                                   "XL": "out", "XXL": "in_stock"},
                },
            },
        ],
        "faults": [],
    },
    "mixed": {
        "title": "全部场景叠加：压力测试",
        "hours": 16,
        "timeline": [
            {
                "at": 2.0, "item": "C8848", "kind": "price_drop",
                "patch": {
                    "promo_price": 103.0,
                    "coupons": [{"id": "CP5", "kind": "platform", "amount": 5.0,
                                 "threshold": 99.0, "allocation": 5.0}],
                },
            },
            {
                "at": 3.0, "item": "C8848", "kind": "review_shift",
                "patch": {"reviews": {"window_days": 7, "total": 344, "negative": 68,
                                      "topics": {"尺码": 0.60, "物流": 0.15,
                                                 "色差": 0.12, "质量": 0.13}}},
            },
            {
                "at": 5.0, "item": "C2002", "kind": "title_change",
                "patch": {"title": "陶瓷马克杯 大容量 带盖勺 办公 350ml 限时直降 包邮"},
            },
            {
                "at": 8.0, "item": "A1001", "kind": "stock_out",
                "patch": {"stock_tier": "out", "stock_raw": 0},
            },
        ],
        "faults": [
            {"at": 4.0, "item": "C1001", "kind": "http_429", "times": 3},
            {"at": 10.0, "item": "C1001", "kind": "captcha", "times": 1},
        ],
    },
}


def get(name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(f"未知场景 {name}，可用：{', '.join(SCENARIOS)}")
    return SCENARIOS[name]