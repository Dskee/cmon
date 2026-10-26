"""五态状态机：暂时性失败可重试，确定性失败一次都不重试，恢复要阶梯放量。"""
from datetime import datetime, timedelta

from cmon.collect import statemachine as sm

T0 = datetime(2026, 10, 27, 8, 0, 0)


def test_retryable_failures_pause_after_three_strikes():
    machine = sm.Machine("item:c1", fail_streak_limit=3, pause_minutes=360)
    machine.on_failure(T0, "timeout")
    machine.on_failure(T0, "timeout")
    assert machine.state == sm.RUNNING
    machine.on_failure(T0, "timeout")
    assert machine.state == sm.PAUSED
    assert machine.pause_until == T0 + timedelta(minutes=360)


def test_deterministic_failure_pauses_on_the_first_hit():
    machine = sm.Machine("item:c1", pause_minutes=360)
    machine.on_failure(T0, "http_403")
    assert machine.state == sm.PAUSED
    assert machine.fail_streak == 1


def test_captcha_uses_the_global_pause_window():
    machine = sm.Machine("source:mock", captcha_pause_minutes=120)
    machine.on_failure(T0, "captcha")
    assert machine.state == sm.PAUSED
    assert machine.pause_until == T0 + timedelta(minutes=120)


def test_paused_blocks_until_deadline_then_probes_at_ten_percent():
    machine = sm.Machine("item:c1")
    machine.on_failure(T0, "http_403")
    assert machine.can_request(T0 + timedelta(minutes=359)) is False
    assert machine.can_request(T0 + timedelta(minutes=360)) is True
    assert machine.state == sm.PROBING
    assert machine.traffic_ratio() == 0.1


def test_probing_ramps_through_steps_before_full_speed():
    machine = sm.Machine("item:c1", probe_steps=[0.1, 0.5, 1.0], probe_ok_needed=3)
    machine.on_failure(T0, "http_403")
    t = T0 + timedelta(minutes=360)
    assert machine.can_request(t)

    for _ in range(3):
        machine.on_success(t)
    assert machine.probe_ratio == 0.5

    for _ in range(3):
        machine.on_success(t)
    assert machine.probe_ratio == 1.0
    assert machine.state == sm.PROBING

    for _ in range(3):
        machine.on_success(t)
    assert machine.state == sm.RUNNING


def test_failure_during_probing_falls_back_to_paused():
    machine = sm.Machine("item:c1")
    machine.on_failure(T0, "http_403")
    t = T0 + timedelta(minutes=360)
    machine.can_request(t)
    machine.on_failure(t, "timeout")
    assert machine.state == sm.PAUSED
    assert machine.pause_until == t + timedelta(minutes=360)


def test_few_samples_do_not_degrade():
    """启动阶段的抖动不算来源故障：样本不足时只看连续失败，不看错误率。"""
    machine = sm.Machine("source:mock", min_samples=20, error_rate_limit=0.20)
    for _ in range(2):
        machine.on_failure(T0, "timeout")
        machine.on_success(T0)
    assert machine.state == sm.RUNNING


def test_high_error_rate_degrades_after_min_samples():
    machine = sm.Machine("source:mock", min_samples=20, error_rate_limit=0.20)
    for _ in range(10):
        machine.on_failure(T0, "timeout")
        machine.on_success(T0)
    assert machine.state == sm.DEGRADED
    assert machine.traffic_ratio() == 0.5


def test_degraded_recovers_after_error_rate_halves():
    machine = sm.Machine("source:mock", min_samples=20, window=100, error_rate_limit=0.20)
    for _ in range(10):
        machine.on_failure(T0, "timeout")
        machine.on_success(T0)
    assert machine.state == sm.DEGRADED
    for _ in range(100):
        machine.on_success(T0)
    assert machine.state == sm.RUNNING


def test_stopped_never_issues_a_request():
    machine = sm.Machine("item:c1", state=sm.STOPPED)
    assert machine.can_request(T0) is False


def test_window_keeps_only_the_last_n_samples():
    machine = sm.Machine("source:mock", window=10)
    for _ in range(5):
        machine.on_success(T0)
    for _ in range(5):
        machine.on_failure(T0, "timeout")
    assert len(machine.errors) == 10
    assert machine.error_rate() == 0.5