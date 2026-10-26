"""五态状态机。

RUNNING → DEGRADED → PAUSED → PROBING → RUNNING，另有一个 STOPPED 只由人工进入。
区分两种失败：暂时性（超时 / 429 / 5xx）可以重试，确定性（403 / 401 / 404 / 验证码）
一次都不重试——重试等于加速被封。恢复不直接全速，10% 流量探活，连续成功再阶梯放量。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

RUNNING = "RUNNING"
DEGRADED = "DEGRADED"
PAUSED = "PAUSED"
PROBING = "PROBING"
STOPPED = "STOPPED"

RETRYABLE = {"timeout", "http_429", "http_5xx", "connection"}
DETERMINISTIC = {"http_403", "http_401", "http_404", "captcha", "parse"}


@dataclass
class Machine:
    name: str
    fail_streak_limit: int = 3
    pause_minutes: int = 360
    captcha_pause_minutes: int = 120
    error_rate_limit: float = 0.20
    window: int = 100
    min_samples: int = 20      # 样本不足时不算错误率，否则刚启动两连败就降级
    probe_steps: list[float] = field(default_factory=lambda: [0.1, 0.5, 1.0])
    probe_ok_needed: int = 3

    state: str = RUNNING
    fail_streak: int = 0
    errors: list[int] = field(default_factory=list)   # 1 失败 0 成功，滑窗
    pause_until: datetime | None = None
    probe_ratio: float = 1.0
    probe_ok: int = 0
    probe_idx: int = 0
    log: list[tuple[str, str, datetime, str]] = field(default_factory=list)

    # ---------- 变更 ----------

    def _to(self, new: str, now: datetime, why: str) -> None:
        if new == self.state:
            return
        self.log.append((self.name, self.state + "→" + new, now, why))
        self.state = new

    # ---------- 判定入口 ----------

    def can_request(self, now: datetime) -> bool:
        if self.state == STOPPED:
            return False
        if self.state == PAUSED:
            if self.pause_until and now >= self.pause_until:
                self._to(PROBING, now, "暂停到期，进入探活")
                self.probe_idx = 0
                self.probe_ratio = self.probe_steps[0]
                self.probe_ok = 0
                return True
            return False
        return True

    def traffic_ratio(self) -> float:
        if self.state == PROBING:
            return self.probe_ratio
        if self.state == DEGRADED:
            return 0.5
        return 1.0

    # ---------- 结果回填 ----------

    def on_success(self, now: datetime) -> None:
        self.fail_streak = 0
        self._push_window(0)
        if self.state == PROBING:
            self.probe_ok += 1
            if self.probe_ok >= self.probe_ok_needed:
                if self.probe_idx + 1 < len(self.probe_steps):
                    self.probe_idx += 1
                    self.probe_ratio = self.probe_steps[self.probe_idx]
                    self.probe_ok = 0
                    self.log.append((self.name, "PROBING", now,
                                     f"探活通过，放量到 {int(self.probe_ratio * 100)}%"))
                else:
                    self.probe_ratio = 1.0
                    self._to(RUNNING, now, "探活全部通过，恢复全速")
        elif self.state == DEGRADED and self.error_rate() <= self.error_rate_limit / 2:
            self._to(RUNNING, now, "错误率回落到阈值一半以下")
        if self.state == PAUSED and self.pause_until and now >= self.pause_until:
            self._to(PROBING, now, "暂停到期")
        self._maybe_degrade(now)

    def _maybe_degrade(self, now: datetime) -> None:
        if self.state != RUNNING:
            return
        if len(self.errors) >= self.min_samples and self.error_rate() > self.error_rate_limit:
            self._to(DEGRADED, now, f"滑窗错误率 {self.error_rate():.0%} 超阈值")

    def on_failure(self, now: datetime, kind: str) -> None:
        self.fail_streak += 1
        self._push_window(1)

        if kind == "captcha":
            # 验证码是全局信号，不重试，直接停到全局暂停
            self.pause_until = now + timedelta(minutes=self.captcha_pause_minutes)
            self._to(PAUSED, now, "命中验证码，全局暂停")
            return

        if kind in DETERMINISTIC:
            self.pause_until = now + timedelta(minutes=self.pause_minutes)
            self._to(PAUSED, now, f"确定性失败 {kind}，不重试，直接暂停")
            return

        if self.state == PROBING:
            self.pause_until = now + timedelta(minutes=self.pause_minutes)
            self._to(PAUSED, now, "探活期再次失败，退回暂停")
            return

        if self.fail_streak >= self.fail_streak_limit:
            self.pause_until = now + timedelta(minutes=self.pause_minutes)
            self._to(PAUSED, now, f"连续失败 {self.fail_streak} 次")
            return

        self._maybe_degrade(now)

    def _push_window(self, flag: int) -> None:
        self.errors.append(flag)
        if len(self.errors) > self.window:
            self.errors = self.errors[-self.window:]

    def error_rate(self) -> float:
        if not self.errors:
            return 0.0
        return sum(self.errors) / len(self.errors)

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "fail_streak": self.fail_streak,
            "error_rate": round(self.error_rate(), 3),
            "probe_ratio": self.probe_ratio,
            "pause_until": self.pause_until.isoformat() if self.pause_until else None,
        }