"""把原始响应归一化成快照。

快照是判定层和分析层共用的唯一输入契约。原始值、推算值、质量标记三块分开存：
raw 用来复盘重算，derived 供判定，quality 决定这份快照能不能进判定。
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from ..mock.source import TENANTS
from ..models import RawItem, Snapshot
from . import price as price_mod
from . import text as text_mod


def build(raw: RawItem, captured_at: datetime, empty: bool = False) -> Snapshot:
    if empty or raw.list_price is None:
        # 200 但字段全空：打缺失标记，绝不允许进入"无变化"判定
        return Snapshot(
            item_id=raw.item_id if raw else "unknown",
            scope=raw.scope if raw else "competitor",
            captured_at=captured_at,
            source_layer=raw.source_layer if raw else "L2",
            list_price=None,
            final_price=None,
            error_band=0.0,
            rule_ids=[],
            intermediate=[],
            stock_tier="unknown",
            size_stock={},
            title="",
            title_tokens=[],
            desc_hash="",
            image_hashes=[],
            reviews={},
            quality_ok=False,
            quality_note="空快照：响应成功但没有有效字段，转缺失处理",
            fingerprint="",
        )

    final, intermediate, rule_ids, band = price_mod.restore(raw)
    title_tokens = sorted(text_mod.terms(raw.title))
    fingerprint = content_fingerprint(raw, final)

    return Snapshot(
        item_id=raw.item_id,
        scope=raw.scope,
        captured_at=captured_at,
        source_layer=raw.source_layer,
        list_price=raw.list_price,
        final_price=final,
        error_band=band,
        rule_ids=rule_ids,
        intermediate=intermediate,
        stock_tier=raw.stock_tier,
        size_stock=dict(raw.size_stock),
        title=raw.title,
        title_tokens=title_tokens,
        desc_hash=raw.desc_hash,
        image_hashes=list(raw.image_hashes),
        reviews=dict(raw.reviews),
        quality_ok=True,
        quality_note="",
        fingerprint=fingerprint,
    )


def content_fingerprint(raw: RawItem, final: float | None) -> str:
    """L3 内容指纹：标题 + 到手价 + 券 id 集合 + 库存档位。

    库存取档位不取精确值——精确值每轮都在动，取进去等于指纹永不重复。
    """
    parts = [
        text_mod.normalize(raw.title),
        f"{final:.2f}" if final is not None else "-",
        ",".join(sorted(c.coupon_id for c in raw.coupons)),
        raw.stock_tier,
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


def tenants_for(item_id: str) -> list[str]:
    return [t for t, ids in TENANTS.items() if item_id in ids]