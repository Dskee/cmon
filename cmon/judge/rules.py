"""事件判定。纯规则，不调模型。

模型判定会导致口径漂移、数据不可比、无法向运营解释——所以这一层只有比较、阈值和时间差。
模型只负责"这个降价像什么"这类解释性工作，在下一层。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any

from ..config import JudgeConfig
from ..db import Store
from ..models import Event, Snapshot
from ..normalize import text as text_mod


class Judge:
    def __init__(self, cfg: JudgeConfig, store: Store) -> None:
        self.cfg = cfg
        self.store = store

    # ---------- 基线 ----------

    def baseline(self, item_id: str, before: datetime, now: datetime) -> float | None:
        since = now - timedelta(days=self.cfg.baseline_days)
        # 只取 before 之前的样本：这轮下跌开始后进来的价不能参与基线，
        # 否则跌得越久基线被拉得越低，跌幅会越算越小，最后自己把自己抹平。
        prices = self.store.prices_since(item_id, since, before)
        prices = [p for p in prices if p is not None]
        if len(prices) < 1:
            return None
        return round(statistics.median(prices), 2)

    # ---------- 主入口 ----------

    def evaluate(self, snap: Snapshot, now: datetime) -> list[Event]:
        state = self.store.get_item_state(snap.item_id)
        events: list[Event] = []

        if not snap.quality_ok:
            # 空快照不参与任何"无变化"判断，也不产生事件，只记一笔
            self.store.save_item_state(snap.item_id, last_final=None)
            return events

        prev_final = state.get("last_final")
        prev_title = state.get("last_title") or ""
        prev_stock = state.get("last_stock") or "in_stock"
        prev_images = state.get("last_images")
        prev_reviews = state.get("last_reviews")
        prev_desc = state.get("last_desc_hash") or ""

        events += self._price_events(snap, state, now)
        events += self._title_events(snap, prev_title, now)
        if snap.desc_hash and prev_desc and snap.desc_hash != prev_desc:
            events.append(
                Event(
                    item_id=snap.item_id,
                    event_type="DESC_CHANGE",
                    detected_at=now,
                    evidence={"old_desc_hash": prev_desc, "new_desc_hash": snap.desc_hash},
                )
            )
        events += self._image_events(snap, prev_images, now)
        events += self._stock_events(snap, prev_stock, now)
        events += self._review_events(snap, prev_reviews, now)

        self.store.save_item_state(
            snap.item_id,
            last_final=snap.final_price,
            last_title=snap.title,
            last_stock=snap.stock_tier,
            last_images=str(snap.image_hashes),
            last_reviews=str(snap.reviews),
            last_desc_hash=snap.desc_hash,
        )
        _ = prev_final
        return events

    # ---------- 价格 ----------

    def _price_events(self, snap: Snapshot, state: dict[str, Any], now: datetime) -> list[Event]:
        if snap.final_price is None:
            return []

        below_since_raw = state.get("below_since")
        below_since = datetime.fromisoformat(below_since_raw) if below_since_raw else None

        # 基线取"这轮下跌开始之前"的价格中位数，避免拿跌后的价当基线，把跌幅算小
        base = self.baseline(snap.item_id, below_since or now, now)
        if base is None or base <= 0:
            return []

        delta = (snap.final_price - base) / base
        threshold = self.cfg.price_drop_pct

        if delta > -threshold:
            if below_since is not None:
                self.store.save_item_state(snap.item_id, below_since=None)
            return []

        if below_since is None:
            self.store.save_item_state(snap.item_id, below_since=now.isoformat())
            return []

        sustained = now - below_since
        if sustained < timedelta(hours=self.cfg.sustain_hours):
            return []

        last_event = state.get("last_event_at")
        if last_event:
            if now - datetime.fromisoformat(last_event) < timedelta(hours=self.cfg.cooldown_hours):
                return []

        self.store.save_item_state(snap.item_id, below_since=None, last_event_at=now.isoformat())
        return [
            Event(
                item_id=snap.item_id,
                event_type="PRICE_DROP",
                detected_at=now,
                evidence={
                    "baseline": base,
                    "current": snap.final_price,
                    "delta_pct": round(delta * 100, 2),
                    "threshold_pct": round(threshold * 100, 2),
                    "sustained_hours": round(sustained.total_seconds() / 3600, 1),
                    "error_band": snap.error_band,
                    "rule_ids": snap.rule_ids,
                    "intermediate": snap.intermediate,
                },
            )
        ]

    # ---------- 标题 / 图片 / 库存 / 评价 ----------

    def _title_events(self, snap: Snapshot, prev_title: str, now: datetime) -> list[Event]:
        if not prev_title:
            return []
        change = text_mod.diff(prev_title, snap.title)
        if len(change["added"]) < self.cfg.title_token_new_min:
            return []
        war = sorted(set(change["added"]) & text_mod.PRICE_WAR_TERMS)
        return [
            Event(
                item_id=snap.item_id,
                event_type="TITLE_CHANGE",
                detected_at=now,
                evidence={
                    "added_terms": change["added"],
                    "removed_terms": change["removed"],
                    "price_war_terms": war,
                    "old_title": prev_title,
                    "new_title": snap.title,
                },
            )
        ]

    def _image_events(self, snap: Snapshot, prev_images: str | None, now: datetime) -> list[Event]:
        if not prev_images:
            return []
        before = set(x for x in prev_images.strip("[]").replace("'", "").split(", ") if x)
        after = set(snap.image_hashes)
        if before and after and before != after:
            return [
                Event(
                    item_id=snap.item_id,
                    event_type="IMAGE_CHANGE",
                    detected_at=now,
                    evidence={"old": sorted(before), "new": sorted(after)},
                )
            ]
        return []

    def _stock_events(self, snap: Snapshot, prev_stock: str, now: datetime) -> list[Event]:
        if prev_stock == snap.stock_tier:
            return []
        if snap.stock_tier == "out":
            return [
                Event(
                    item_id=snap.item_id,
                    event_type="STOCK_OUT",
                    detected_at=now,
                    evidence={"from": prev_stock, "to": snap.stock_tier},
                )
            ]
        return []

    def _review_events(self, snap: Snapshot, prev_reviews: str | None, now: datetime) -> list[Event]:
        if not prev_reviews or not snap.reviews:
            return []
        negative = int(snap.reviews.get("negative", 0))
        if negative < self.cfg.review_min_samples:
            return []
        try:
            import ast

            before = ast.literal_eval(prev_reviews)
        except (ValueError, SyntaxError):
            return []
        old_topics = before.get("topics", {}) if isinstance(before, dict) else {}
        new_topics = snap.reviews.get("topics", {})
        shifted = []
        for topic, ratio in new_topics.items():
            old = float(old_topics.get(topic, 0.0))
            jump = float(ratio) - old
            if jump >= self.cfg.review_topic_jump_pp:
                shifted.append({"topic": topic, "before": round(old, 2), "after": round(float(ratio), 2)})
        if not shifted:
            return []
        return [
            Event(
                item_id=snap.item_id,
                event_type="REVIEW_TOPIC_SHIFT",
                detected_at=now,
                evidence={
                    "shifted": shifted,
                    "negative": negative,
                    "total": snap.reviews.get("total"),
                    "window_days": snap.reviews.get("window_days"),
                },
            )
        ]