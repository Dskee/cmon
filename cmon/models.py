"""贯穿全链路的数据结构。字段名对齐方案第五节的快照 schema。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Coupon:
    coupon_id: str
    kind: str            # platform / shop / group
    amount: float
    threshold: float = 0.0
    allocation: float | None = None   # 跨店满减的分摊额；None 表示未知，误差要放大


@dataclass
class RawItem:
    """数据源返回的原始字段，不做任何推算。"""
    item_id: str
    scope: str           # self / competitor
    source_layer: str    # L1 / L2 / L3
    title: str
    list_price: float | None
    promo_price: float | None = None
    coupons: list[Coupon] = field(default_factory=list)
    full_reduction: list[Coupon] = field(default_factory=list)
    group_buy: Coupon | None = None
    stock_tier: str = "in_stock"      # in_stock / low / out
    stock_raw: int = 0
    desc_hash: str = ""
    image_hashes: list[str] = field(default_factory=list)
    reviews: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    ok: bool
    raw: RawItem | None = None
    error: str = ""              # timeout / http_429 / http_403 / captcha / parse
    retryable: bool = False
    empty: bool = False          # 200 但字段全空——最危险的一类
    latency_ms: int = 0


@dataclass
class Snapshot:
    item_id: str
    scope: str
    captured_at: datetime
    source_layer: str
    list_price: float | None
    final_price: float | None
    error_band: float
    rule_ids: list[str]
    intermediate: list[dict[str, Any]]
    stock_tier: str
    title: str
    title_tokens: list[str]
    desc_hash: str
    image_hashes: list[str]
    reviews: dict[str, Any]
    quality_ok: bool
    quality_note: str
    fingerprint: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "scope": self.scope,
            "captured_at": self.captured_at.isoformat(),
            "source_layer": self.source_layer,
            "raw": {"list_price": self.list_price},
            "derived": {
                "final_price": self.final_price,
                "error_band": self.error_band,
                "rule_ids": self.rule_ids,
                "intermediate": self.intermediate,
            },
            "stock": {"tier": self.stock_tier},
            "title": self.title,
            "desc_hash": self.desc_hash,
            "image_hashes": self.image_hashes,
            "reviews": self.reviews,
            "quality": {"ok": self.quality_ok, "note": self.quality_note},
        }


@dataclass
class Event:
    item_id: str
    event_type: str
    detected_at: datetime
    evidence: dict[str, Any]
    interpretation: str = ""
    confidence: float = 0.0
    action: str = ""
    avoid: str = ""
    material_request: str = ""
    alert_path: str = ""

    def summary(self) -> str:
        return f"{self.event_type} item={self.item_id}"