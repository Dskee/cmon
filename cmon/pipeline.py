"""八步编排，一条命令跑完一整天。

采集 → 归一 → 判定 → 解释 → 汇总 → 输出。中间没有 agent 路由：哪一步做什么由规则决定，
模型只在"解释"这一步被调用，且输入是归一化快照，不是原始页面。
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .analyze import llm as llm_mod
from .analyze import prompt
from .clock import SimClock
from .collect import statemachine as sm
from .collect.dedup import Deduplicator
from .collect.limiter import Limiter
from .collect.planner import PRICE, Planner, in_active_hours
from .config import Config
from .db import Store
from .judge.rules import Judge
from .mock.scenarios import get as get_scenario
from .mock.source import TENANTS, MockWorld
from .models import Event, Snapshot
from .normalize import snapshot as snap_mod
from .output import card as card_mod


def _evidence_key(ev: Event) -> str:
    blob = ev.event_type + json.dumps(ev.evidence, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


class Pipeline:
    def __init__(self, cfg: Config, scenario: str, offline: bool = False,
                 verbose: bool = True) -> None:
        self.cfg = cfg
        self.scenario = get_scenario(scenario)
        self.verbose = verbose
        self.store = Store(cfg.db_path)
        self.world = MockWorld(self.scenario)
        self.limiter = Limiter(
            cfg.collect.global_qps, cfg.collect.source_qps, cfg.collect.item_min_interval_min
        )
        self.planner = Planner(cfg.collect.freq_min)
        self.dedup = Deduplicator(ttl_min=cfg.collect.ttl_min)
        self.judge = Judge(cfg.judge, self.store)
        self.client = llm_mod.build(cfg.llm, offline=offline)
        self.offline = offline

        self.items = sorted({i for ids in TENANTS.values() for i in ids})
        self.machines = {i: self._machine(i) for i in self.items}
        self.source_machine = self._machine("source:mock-taobao")
        self._item_events: dict[str, list[Event]] = {}
        self._agg_index: dict[str, int] = {}
        self._analysis_cache: dict[str, dict[str, Any]] = {}
        self.failures: dict[str, int] = {}
        self.on_event: Callable[[Event], None] | None = None

    def _machine(self, name: str) -> sm.Machine:
        p = self.cfg.collect.pause
        return sm.Machine(
            name=name,
            fail_streak_limit=p["item_fail_streak"],
            pause_minutes=p["item_pause_min"],
            captcha_pause_minutes=p["captcha_pause_min"],
            error_rate_limit=p["source_error_rate"],
            window=p["source_window"],
            min_samples=p["source_window"] // 5,
            probe_steps=p["probe_steps"],
            probe_ok_needed=p["probe_ok_needed"],
        )

    # ---------- 主循环 ----------

    def run(self) -> dict[str, Any]:
        hours = self.scenario.get("hours", 12)
        start = datetime.now().replace(hour=self.cfg.day_start_hour, minute=0,
                                       second=0, microsecond=0)
        clock = SimClock(start)
        end = start + timedelta(hours=hours)
        tick = timedelta(minutes=self.cfg.collect.tick_min)

        self._say(f"场景 {self.scenario['title']}")
        self._say(f"窗口 {start:%Y-%m-%d %H:%M} → {end:%m-%d %H:%M}，{len(self.items)} 个监控对象")

        while clock.now() < end:
            now = clock.now()
            elapsed = (now - start).total_seconds() / 3600
            for note in self.world.apply_timeline(elapsed):
                self._say(f"  ⟳ 世界变化：{note}", indent=0)

            for item_id in self.items:
                if clock.now() >= end:
                    break
                self._maybe_collect(item_id, clock, start, end)

            target = now + tick
            if clock.now() < target:
                clock.advance(seconds=(target - clock.now()).total_seconds())

        return self._finish(start, end)

    # ---------- 单个对象 ----------

    def _maybe_collect(self, item_id: str, clock: SimClock, start: datetime,
                       end: datetime) -> None:
        now = clock.now()
        machine = self.machines[item_id]
        fields = self.planner.due_fields(item_id, now)

        if PRICE in fields and not in_active_hours(now, self.cfg.day_start_hour, 24):
            fields = [f for f in fields if f != PRICE]
        if not fields:
            return
        if not self.source_machine.can_request(now) or not machine.can_request(now):
            return

        at = self.limiter.reserve(now, self.world.source_name, item_id)
        if at >= end:
            return
        if at > clock.now():
            clock.advance(seconds=(at - clock.now()).total_seconds())
            now = clock.now()

        elapsed = (now - start).total_seconds() / 3600

        # L1：一个周期内同一商品只采一次，结果广播给所有租户
        cached = self.dedup.l1_get(item_id, now)
        if cached is not None:
            return

        result = self.world.fetch(item_id, elapsed)
        self.dedup.l1_put(item_id, now, result)
        self.store.incr("requests")
        self.dedup.stats.requests += 1

        tenants = snap_mod.tenants_for(item_id)
        if len(tenants) > 1:
            self.store.incr("requests_saved_cross_tenant", len(tenants) - 1)
            self.dedup.stats.l1_hits += len(tenants) - 1

        self._handle_machine(machine, result, now)
        self._handle_machine(self.source_machine, result, now)

        if not result.ok:
            self.failures[result.error] = self.failures.get(result.error, 0) + 1
            self.store.incr(f"fail_{result.error}")
            return

        if result.empty:
            self.store.incr("empty_responses")
            self._say(f"[{now:%H:%M}] 采集  {item_id}  空响应 → 打缺失标记，不参与判定")
            return

        assert result.raw is not None
        snap = snap_mod.build(result.raw, now)
        self._consume(item_id, snap, now, fields)

    def _handle_machine(self, machine: sm.Machine, result: Any, now: datetime) -> None:
        before = machine.state
        if result.ok:
            machine.on_success(now)
        else:
            machine.on_failure(now, result.error)
        if machine.state != before:
            self.store.incr(f"state_{machine.state}")
            if self.verbose:
                why = machine.log[-1][3] if machine.log else ""
                self._say(f"[{now:%H:%M}] 状态  {machine.name} → {machine.state}"
                          f"（{why}）")

    # ---------- 消费一份快照 ----------

    def _consume(self, item_id: str, snap: Snapshot, now: datetime, fields: list[str]) -> None:
        previous_fp = self.store.last_fingerprint(item_id)
        self.store.add_snapshot(snap)

        for f in fields:
            self.planner.mark(item_id, f, now)

        if not snap.quality_ok:
            return

        # 内容没变只是不重复花钱解释，判定照跑：
        # "连续两次都低于基线"这件事本身就是靠"价格没变"数出来的。
        if self.dedup.l3_same(snap, previous_fp):
            self.store.incr("unchanged_snapshots")

        price_txt = f"{snap.final_price:.2f}" if snap.final_price is not None else "-"
        self._say(f"[{now:%H:%M}] 采集  {item_id}  到手价 {price_txt}"
                  f"  券 {'+'.join(snap.rule_ids) or '无'}")

        events = self.judge.evaluate(snap, now)
        for ev in events:
            self._emit(ev, snap)
        # 汇总放在同一份快照的所有事件都落盘之后：同一时刻出的三个事件要一起看，
        # 不能谁先到就先汇总，那样第三个事件永远进不了这次汇总。
        if events:
            self._maybe_aggregate(item_id)

    # ---------- 事件 → 解释 → 卡片 ----------

    def _emit(self, ev: Event, snap: Snapshot) -> None:
        self.store.incr("events")
        self._say(f"[{ev.detected_at:%H:%M}] 判定  {ev.item_id}  {ev.event_type}")

        self._interpret(ev, snap)

        path = card_mod.write_card(self.cfg.out_dir, ev)
        ev.alert_path = path
        self.store.add_event(ev)
        if self.on_event:
            self.on_event(ev)
        self._say(f"[{ev.detected_at:%H:%M}] 输出  {Path(path).name}"
                  f"  action={ev.action[:28]}")

        bucket = self._item_events.setdefault(ev.item_id, [])
        bucket.append(ev)

    def _maybe_aggregate(self, item_id: str) -> None:
        """同一商品累计出现两个还没汇总过的事件，就升级一次。

        汇总层不是路由，是"同一件事的两种解释互相印证"：
        降价 12% 和差评转向尺码放在一起看，结论会从"对手在促销"变成"对手在清某个尺码"。
        """
        bucket = self._item_events.get(item_id, [])
        done = self._agg_index.get(item_id, 0)
        fresh = bucket[done:]
        if len(fresh) < 2:
            return
        self._agg_index[item_id] = len(bucket)
        self._aggregate(item_id, fresh)

    def _interpret(self, ev: Event, snap: Snapshot) -> None:
        context = {
            "scope": snap.scope,
            "final_price": snap.final_price,
            "error_band": snap.error_band,
            "stock_tier": snap.stock_tier,
            "reviews": snap.reviews,
        }
        user = prompt.build_user(ev.event_type, ev.item_id, snap.scope, ev.evidence, context)

        key = _evidence_key(ev)
        data = self._analysis_cache.get(key)
        if data is not None:
            self.store.incr("llm_cache_hits")
        else:
            data = self._ask(prompt.SYSTEM, user)
            if data is not None:
                self._analysis_cache[key] = data
        if data is None:
            return
        ev.interpretation = data.get("interpretation", "")
        ev.confidence = float(data.get("confidence", 0.0))
        ev.action = data.get("action", "")
        ev.avoid = data.get("avoid", "")
        ev.material_request = data.get("material_request", "") or ""

    def _aggregate(self, item_id: str, events: list[Event]) -> None:
        self._say(f"[{events[-1].detected_at:%H:%M}] 汇总  {item_id}  "
                  f"{len(events)} 个事件同窗，触发汇总层")
        payload = [
            {"event_type": e.event_type, "evidence": e.evidence,
             "interpretation": e.interpretation, "action": e.action}
            for e in events
        ]
        user = prompt.build_aggregate(item_id, payload)
        data = self._ask(prompt.AGGREGATE_SYSTEM, user)
        if data is None:
            return
        merged = Event(
            item_id=item_id,
            event_type="AGGREGATED",
            detected_at=events[-1].detected_at,
            evidence={"merged_types": [e.event_type for e in events]},
            interpretation=data.get("interpretation", ""),
            confidence=float(data.get("confidence", 0.0)),
            action=data.get("action", ""),
            avoid=data.get("avoid", ""),
            material_request=data.get("material_request", "") or "",
        )
        self.store.incr("aggregations")
        path = card_mod.write_card(self.cfg.out_dir, merged)
        merged.alert_path = path
        self.store.add_event(merged)
        if self.on_event:
            self.on_event(merged)
        self._say(f"[{merged.detected_at:%H:%M}] 汇总  建议：{merged.action[:40]}")
        self._say(f"[{merged.detected_at:%H:%M}] 输出  {Path(path).name}")

    def _ask(self, system: str, user: str) -> dict[str, Any] | None:
        attempts = self.cfg.llm.max_retries + 1
        last_err = ""
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                raw = self.client.chat(system, user)
                self.store.incr("llm_calls")
                if started:
                    self.store.incr("llm_ms", int((time.monotonic() - started) * 1000))
                usage = getattr(self.client, "last_usage", None)
                if usage:
                    self.store.incr("llm_prompt_tokens", usage.get("prompt_tokens", 0))
                    self.store.incr("llm_completion_tokens", usage.get("completion_tokens", 0))
                return llm_mod.parse(raw)
            except llm_mod.LlmError as exc:
                last_err = f"第 {attempt} 次：{exc}"
                self.store.incr("llm_retry")
                continue
            except ValueError as exc:
                last_err = f"第 {attempt} 次 JSON 解析失败：{exc}"
                self.store.incr("llm_retry")
                continue
        self._say(f"  ! 模型调用失败：{last_err}（降级为仅规则事件）")
        return None

    # ---------- 收尾 ----------

    def _finish(self, start: datetime, end: datetime) -> dict[str, Any]:
        metrics = self.store.metrics()
        metrics["peak_qps"] = round(self.limiter.peak_qps(), 2)
        metrics.update({k: float(v) for k, v in self.dedup.stats.as_dict().items() if k != "requests"})

        date = start.strftime("%Y-%m-%d")
        daily_path = card_mod.write_daily(self.cfg.out_dir, date,
                                          self.store.recent_events(200), metrics)

        self._say("")
        self._say(f"完成：{int(metrics.get('requests', 0))} 次请求，"
                  f"{int(metrics.get('events', 0))} 个事件，"
                  f"{int(metrics.get('llm_calls', 0))} 次模型调用")
        for name in ("requests_saved_cross_tenant", "unchanged_snapshots",
                     "empty_responses", "aggregations", "llm_retry"):
            if name in metrics:
                self._say(f"  {name}: {int(metrics[name])}")
        if self.failures:
            self._say("  失败分布：" + "，".join(f"{k}×{v}" for k, v in sorted(self.failures.items())))
        transitions = [t for m in list(self.machines.values()) + [self.source_machine] for t in m.log]
        if transitions:
            self._say("  状态转换：")
            for name, move, at, why in transitions:
                self._say(f"    {at:%H:%M} {name}: {move}  {why}")
        self._say(f"  日报：{daily_path}")

        return {"metrics": metrics, "failures": self.failures,
                "transitions": [(n, m, t.isoformat(), w) for n, m, t, w in transitions],
                "daily": daily_path}

    def _say(self, text: str, indent: int = 0) -> None:
        if self.verbose:
            print(" " * indent + text)

    def close(self) -> None:
        self.store.close()