"""自建的"假淘宝"数据源。

接口契约照开放平台的字段口径写：真实源接进来只换 adapter，判定、输出、实验都不用动。
之所以自己造，是因为真实链路在应届个人手上不可得（开放平台要企业资质和店铺授权，
联盟要备案推广位），而可控的源才能做可复现的故障注入。
"""
from __future__ import annotations

import copy
import hashlib
import random
from typing import Any

from ..models import Coupon, FetchResult, RawItem

# 两个商家，故意让 C8848 同时被两家监控——跨租户去重要靠它验证
TENANTS: dict[str, list[str]] = {
    "shop_a": ["A1001", "A1002", "C8848", "C1001"],
    "shop_b": ["B1001", "B1002", "C8848", "C2002"],
}

BASELINE: dict[str, dict[str, Any]] = {
    "A1001": {
        "scope": "self", "title": "纯棉短袖T恤男 夏季宽松 白色 XL",
        "list_price": 79.0, "promo_price": None,
        "coupons": [], "stock_tier": "in_stock", "stock_raw": 320,
        "size_stock": {"M": "in_stock", "L": "in_stock", "XL": "in_stock", "XXL": "low"},
        "reviews": {"window_days": 7, "total": 210, "negative": 12,
                    "topics": {"物流": 0.40, "尺码": 0.25, "色差": 0.20, "质量": 0.15}},
    },
    "A1002": {
        "scope": "self", "title": "加厚保暖卫衣女 韩版宽松 连帽 米白 M",
        "list_price": 128.0, "promo_price": 118.0,
        "coupons": [{"id": "SA2", "kind": "shop", "amount": 8.0, "threshold": 99.0}],
        "stock_tier": "low", "stock_raw": 18,
        "size_stock": {"S": "in_stock", "M": "low", "L": "out"},
        "reviews": {"window_days": 7, "total": 96, "negative": 5,
                    "topics": {"物流": 0.30, "包装": 0.30, "质量": 0.40}},
    },
    "B1001": {
        "scope": "self", "title": "简约帆布双肩包 大容量 通勤 黑色",
        "list_price": 159.0, "promo_price": None,
        "coupons": [], "stock_tier": "in_stock", "stock_raw": 240,
        "reviews": {"window_days": 7, "total": 130, "negative": 9,
                    "topics": {"物流": 0.50, "质量": 0.30, "客服": 0.20}},
    },
    "B1002": {
        "scope": "self", "title": "陶瓷马克杯 大容量 带盖勺 办公 400ml",
        "list_price": 45.0, "promo_price": None,
        "coupons": [], "stock_tier": "in_stock", "stock_raw": 88,
        "reviews": {"window_days": 7, "total": 64, "negative": 3,
                    "topics": {"物流": 0.60, "包装": 0.40}},
    },
    "C8848": {
        "scope": "competitor", "title": "纯棉短袖T恤男 夏季宽松 白色 XL 爆款",
        "list_price": 109.0, "promo_price": None,
        "coupons": [], "stock_tier": "in_stock", "stock_raw": 460,
        "size_stock": {"M": "in_stock", "L": "in_stock", "XL": "in_stock", "XXL": "in_stock"},
        "reviews": {"window_days": 7, "total": 320, "negative": 45,
                    "topics": {"物流": 0.55, "尺码": 0.10, "色差": 0.20, "质量": 0.15}},
    },
    "C1001": {
        "scope": "competitor", "title": "工装裤男 直筒宽松 多口袋 卡其 L",
        "list_price": 189.0, "promo_price": 169.0,
        "coupons": [{"id": "CP1", "kind": "platform", "amount": 15.0,
                     "threshold": 150.0, "allocation": 15.0}],
        "stock_tier": "in_stock", "stock_raw": 260,
        "size_stock": {"30": "in_stock", "32": "in_stock", "34": "low", "36": "in_stock"},
        "reviews": {"window_days": 7, "total": 188, "negative": 22,
                    "topics": {"物流": 0.35, "尺码": 0.30, "质量": 0.35}},
    },
    "C2002": {
        "scope": "competitor", "title": "陶瓷马克杯 大容量 带盖勺 办公 350ml",
        "list_price": 52.0, "promo_price": None,
        "coupons": [], "stock_tier": "in_stock", "stock_raw": 150,
        "reviews": {"window_days": 7, "total": 71, "negative": 4,
                    "topics": {"包装": 0.50, "物流": 0.50}},
    },
}


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


class MockWorld:
    """持有当前世界状态：基线 + 已生效的补丁 + 未消耗的故障。"""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        self.items = copy.deepcopy(BASELINE)
        self._applied: set[int] = set()
        self._fault_used: dict[int, int] = {}
        self.source_name = "mock-taobao"

    # ---------- 时间推进 ----------

    def apply_timeline(self, elapsed_hours: float) -> list[str]:
        """把到点的事件补丁打进当前状态，返回本次新生效的补丁说明。"""
        fired: list[str] = []
        for idx, step in enumerate(self.scenario.get("timeline", [])):
            if idx in self._applied or elapsed_hours < step["at"]:
                continue
            self._applied.add(idx)
            item = self.items.get(step["item"])
            if item is None:
                continue
            item.update(copy.deepcopy(step["patch"]))
            fired.append(step.get("note", f"{step['item']}:{step['kind']}"))
        return fired

    # ---------- 故障注入 ----------

    def _consume_fault(self, item_id: str, elapsed_hours: float) -> dict[str, Any] | None:
        for idx, flt in enumerate(self.scenario.get("faults", [])):
            if flt["item"] != item_id:
                continue
            if elapsed_hours < flt["at"]:
                continue
            used = self._fault_used.get(idx, 0)
            if used >= flt.get("times", 1):
                continue
            self._fault_used[idx] = used + 1
            return flt
        return None

    # ---------- 取数 ----------

    def fetch(self, item_id: str, elapsed_hours: float) -> FetchResult:
        fault = self._consume_fault(item_id, elapsed_hours)
        if fault is not None:
            kind = fault["kind"]
            if kind == "timeout":
                return FetchResult(ok=False, error="timeout", retryable=True, latency_ms=5000)
            if kind == "http_429":
                return FetchResult(ok=False, error="http_429", retryable=True, latency_ms=180)
            if kind == "http_403":
                return FetchResult(ok=False, error="http_403", retryable=False, latency_ms=120)
            if kind == "captcha":
                return FetchResult(ok=False, error="captcha", retryable=False, latency_ms=200)
            if kind == "empty":
                # 200 但字段全空：最危险的一类，静默变成"没变化"
                return FetchResult(ok=True, raw=None, empty=True, latency_ms=95)

        item = self.items.get(item_id)
        if item is None:
            return FetchResult(ok=False, error="http_404", retryable=False, latency_ms=90)

        coupons = [Coupon(**{("coupon_id" if k == "id" else k): v for k, v in c.items()})
                   for c in item.get("coupons", [])]
        fr = [Coupon(**{("coupon_id" if k == "id" else k): v for k, v in c.items()})
              for c in item.get("full_reduction", [])]
        gb = None
        if item.get("group_buy"):
            gb = Coupon(**{("coupon_id" if k == "id" else k): v
                           for k, v in item["group_buy"].items()})
        raw = RawItem(
            item_id=item_id,
            scope=item["scope"],
            source_layer="L2",
            title=item["title"],
            list_price=item.get("list_price"),
            promo_price=item.get("promo_price"),
            coupons=coupons,
            full_reduction=fr,
            group_buy=gb,
            stock_tier=item.get("stock_tier", "in_stock"),
            stock_raw=item.get("stock_raw", 0),
            size_stock=copy.deepcopy(item.get("size_stock", {})),
            desc_hash=_hash(item["title"] + str(item.get("list_price"))),
            image_hashes=[_hash(item["title"] + "img1")],
            reviews=copy.deepcopy(item.get("reviews", {})),
        )
        # 真实接口的延迟分布不是常数，加点抖动，免得限流实验失真
        jitter = 80 + int(random.random() * 120)
        return FetchResult(ok=True, raw=raw, latency_ms=jitter)