"""端到端：一条命令跑完一个场景，结果和数字要对得上。

这些测试跑在 SimClock 上，28 小时的窗口几秒就跑完——所以"持续 2 小时才告警"
这种时间语义也可以进回归测试。
"""
from dataclasses import replace
from pathlib import Path

from cmon.config import load
from cmon.pipeline import Pipeline


def make_cfg(tmp_path: Path):
    base = load()
    return replace(base, db_path=tmp_path / "cmon.db", out_dir=tmp_path / "out")


def run(scenario: str, tmp_path: Path) -> dict:
    pipeline = Pipeline(make_cfg(tmp_path), scenario, offline=True, verbose=False)
    try:
        return pipeline.run()
    finally:
        pipeline.close()


def test_price_drop_scenario_produces_two_events_and_one_aggregation(tmp_path):
    result = run("price-drop", tmp_path)
    metrics = result["metrics"]

    assert metrics["requests"] > 0
    assert metrics["events"] == 2
    assert metrics["llm_calls"] == 3          # 两条解释 + 一次汇总
    assert metrics["aggregations"] == 1

    alerts = list((tmp_path / "out" / "alerts").rglob("*.md"))
    assert len(alerts) == 3
    assert any("AGGREGATED" in p.name for p in alerts)


def test_daily_report_is_written(tmp_path):
    result = run("price-drop", tmp_path)
    daily = Path(result["daily"])
    assert daily.exists()
    body = daily.read_text(encoding="utf-8")
    assert "竞品监控日报" in body
    assert "PRICE_DROP" in body


def test_empty_responses_never_become_events(tmp_path):
    result = run("empty-silent", tmp_path)
    metrics = result["metrics"]
    assert metrics.get("empty_responses", 0) >= 1
    assert metrics.get("events", 0) == 0


def test_fault_storm_pauses_the_item_then_probes(tmp_path):
    result = run("fault-storm", tmp_path)
    moves = [move for name, move, _, _ in result["transitions"] if name == "C1001"]
    assert any("PAUSED" in move for move in moves)
    assert metrics_paused(result) >= 1


def metrics_paused(result: dict) -> float:
    return result["metrics"].get("state_PAUSED", 0.0)


def test_title_change_scenario_emits_a_title_event(tmp_path):
    result = run("title-change", tmp_path)
    assert result["metrics"]["events"] >= 1
    alerts = list((tmp_path / "out" / "alerts").rglob("*.md"))
    assert any("TITLE_CHANGE" in p.name for p in alerts)


def test_size_clearance_scenario_aggregates_three_events(tmp_path):
    """降价 + 某尺码卖光 + 差评转向尺码：三条证据同窗，汇总层一次吃下。"""
    result = run("size-clearance", tmp_path)
    metrics = result["metrics"]

    assert metrics["events"] == 3
    assert metrics["llm_calls"] == 4          # 三条解释 + 一次汇总
    assert metrics["aggregations"] == 1

    alerts = list((tmp_path / "out" / "alerts").rglob("*.md"))
    assert any("SIZE_STOCK_OUT" in p.name for p in alerts)
    agg = next(p for p in alerts if "AGGREGATED" in p.name)
    body = agg.read_text(encoding="utf-8")
    for kind in ("PRICE_DROP", "SIZE_STOCK_OUT", "REVIEW_TOPIC_SHIFT"):
        assert kind in body


def test_two_runs_of_the_same_scenario_agree(tmp_path):
    a = run("price-drop", tmp_path / "a")
    b = run("price-drop", tmp_path / "b")
    assert a["metrics"]["requests"] == b["metrics"]["requests"]
    assert a["metrics"]["events"] == b["metrics"]["events"]
    assert a["metrics"]["llm_calls"] == b["metrics"]["llm_calls"]


def test_run_does_not_touch_the_network(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("离线模式不应该发出网络请求")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    result = run("price-drop", tmp_path)
    assert result["metrics"]["events"] == 2