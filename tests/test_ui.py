"""界面层：能构造出来、能跑一次、卡片切换有内容。

只测"能不能用"，不测像素。gradio 装不上就跳过——前端不是这个项目的核心依赖。
"""
from __future__ import annotations

import pytest

pytest.importorskip("gradio")

from cmon import ui  # noqa: E402


def test_build_ui_returns_blocks() -> None:
    demo = ui.build_ui()

    assert demo is not None
    assert hasattr(demo, "launch")


def test_do_run_returns_six_outputs() -> None:
    summary, rows, trace, picker, card, daily = ui.do_run("price-drop", "offline")

    assert "price-drop" in summary
    assert rows and rows[0][0] == "请求数"
    assert "```text" in trace
    assert picker["choices"]  # gr.update(dict) 里的候选卡片
    assert card
    assert "竞品监控日报" in daily


def test_do_run_on_unknown_scenario_reports_instead_of_raising() -> None:
    summary, _rows, _trace, _picker, _card, _daily = ui.do_run("no-such-scenario", "offline")

    assert "运行失败" in summary


def test_show_card_returns_blank_without_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui, "RESULTS", {})

    assert ui.show_card("whatever.md", "no-such-run") == "_先点上面的运行按钮。_"