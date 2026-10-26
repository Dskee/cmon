"""一次运行的封装层：跑得对、收得全，卡片的读取路径通。

不测界面像素——接口这一层错了，界面再对也没用；界面那一层真错了，
下面是 `test_ui.py` 里的构造测试。
"""
from __future__ import annotations

from pathlib import Path

from cmon.runs import (
    describe_failures,
    run_scenario,
    scenario_choices,
    summary_markdown,
)


def test_run_collects_metrics_cards_and_trace(tmp_path: Path) -> None:
    result = run_scenario("price-drop", offline=True, workdir=tmp_path)

    assert result.metrics["requests"] > 0
    assert result.metrics["events"] == 2
    assert result.elapsed > 0
    # 两次判定 + 一次汇总
    assert len(result.cards) == 3
    assert "完成" in result.trace
    assert "竞品监控日报" in result.daily


def test_metric_rows_follow_the_display_order(tmp_path: Path) -> None:
    rows = run_scenario("price-drop", offline=True, workdir=tmp_path).metric_rows()

    labels = [r[0] for r in rows]
    assert labels[0] == "请求数"
    assert labels[1] == "判定事件"
    assert labels.index("请求数") < labels.index("模型调用")
    assert all(isinstance(value, str) for _label, value in rows)


def test_card_lookup_returns_content_and_blank_for_unknown(tmp_path: Path) -> None:
    result = run_scenario("price-drop", offline=True, workdir=tmp_path)
    name = result.card_names()[0]

    assert "PRICE_DROP" in result.card(name) or "价格" in result.card(name)
    assert result.card("不存在的卡片.md") == ""


def test_cards_live_under_the_run_directory(tmp_path: Path) -> None:
    result = run_scenario("title-change", offline=True, workdir=tmp_path)

    assert result.out_dir is not None
    assert result.out_dir.is_relative_to(tmp_path)
    assert all(c.path.is_file() for c in result.cards)
    assert all(c.path.is_relative_to(result.out_dir) for c in result.cards)


def test_scenario_choices_cover_all_six(tmp_path: Path) -> None:
    choices = scenario_choices()

    assert len(choices) == 6
    labels = [label for label, _value in choices]
    assert any("size-clearance" in label for label in labels)
    assert all("h ·" in label for label in labels)


def test_summary_states_what_happened(tmp_path: Path) -> None:
    result = run_scenario("fault-storm", offline=True, workdir=tmp_path)
    text = summary_markdown(result)

    assert "fault-storm" in text
    assert "离线替身" in text
    assert "用时" in text
    assert describe_failures(result)  # 故障场景一定有失败请求
    assert "无失败请求" not in text