"""Gradio 前端：把一次运行摊开给人看。

界面上没有一个新的数字——指标、卡片、日报全部来自 `python -m cmon run` 的同一次运行。
这一层唯一的职责是把结果摆好，任何"为了界面好看"的加工都不做。

启动：python -m cmon.ui
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path

import gradio as gr

from .runs import (
    RunResult,
    run_scenario,
    scenario_choices,
    summary_markdown,
)

RESULTS: dict[str, RunResult] = {}

HEADER = """# 竞品监控 Agent

盯着竞品商品的四个面：价格、标题、描述、评价，外加分尺码库存。
每次抓到变化先过判定层，够格的才花模型调用去解释，解释成一张运营能照着做的卡片。

下面每个按钮跑的都是一次完整流水线，和 `python -m cmon run` 走同一个 `Pipeline`。
"""

FOOTER = """---
`离线替身` 用写死的文案顶替模型，默认选它——讲清链路不需要花钱。
`真实模型` 走硅基流动，一次运行 3～4 次调用、约 30～40 秒；金额从 `.env` 里的 key 扣。
"""


def _view(result: RunResult) -> tuple:
    """把一次运行整理成界面要的六件东西。"""
    names = result.card_names()
    return (
        summary_markdown(result),
        result.metric_rows(),
        f"```text\n{result.trace}\n```",
        gr.update(choices=names, value=names[0] if names else None),
        result.card(names[0]) if names else "_这次没有触发出卡片的事件。_",
        result.daily or "_这次没有生成日报。_",
    )


def _empty_view(message: str) -> tuple:
    return (message, [], "", gr.update(choices=[], value=None), "", "")


def do_run(scenario: str, mode: str) -> tuple:
    offline = mode != "online"
    try:
        result = run_scenario(scenario, offline=offline)
    except Exception as exc:  # 界面上要看到原因，不能只抛到控制台
        detail = traceback.format_exc(limit=3)
        return _empty_view(f"### 运行失败\n\n`{type(exc).__name__}: {exc}`\n\n```text\n{detail}\n```")
    RESULTS[result.run_id] = result
    return _view(result)


def show_card(name: str, run_id: str) -> str:
    result = RESULTS.get(run_id or "") or RESULTS.get(_last_run_id())
    if result is None:
        return "_先点上面的运行按钮。_"
    if not name:
        return "_这次没有触发出卡片的事件。_"
    return result.card(name)


def first_screen() -> tuple:
    """开屏就摆一次真实结果，比空表格有用。"""
    return do_run("size-clearance", "offline")


def experiments_markdown() -> str:
    path = Path("var/out/experiments.md")
    if not path.exists():
        return ("_还没跑过实验。先执行 `python experiments/fault_injection.py`，"
                "六个场景会各跑一遍并生成这张表。_")
    return path.read_text(encoding="utf-8")


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="竞品监控 Agent") as demo:
        gr.Markdown(HEADER)
        run_id = gr.State("")

        with gr.Row():
            with gr.Column(scale=1, min_width=280):
                scenario = gr.Dropdown(
                    choices=scenario_choices(),
                    value="size-clearance",
                    label="场景",
                )
                mode = gr.Radio(
                    choices=[("离线替身（不花钱）", "offline"),
                             ("真实模型（约 30～40 秒）", "online")],
                    value="offline",
                    label="模型",
                )
                button = gr.Button("跑一次", variant="primary")
                gr.Markdown(FOOTER)

            with gr.Column(scale=4):
                summary = gr.Markdown("_正在跑第一次……_")
                with gr.Tabs():
                    with gr.Tab("运行指标"):
                        metrics = gr.Dataframe(
                            headers=["指标", "值"],
                            datatype=["str", "str"],
                            value=[],
                            interactive=False,
                            wrap=True,
                        )
                        with gr.Accordion("采集日志", open=False):
                            trace_box = gr.Markdown("")
                    with gr.Tab("告警卡片"):
                        card_pick = gr.Dropdown(choices=[], label="卡片", value=None)
                        card_body = gr.Markdown("")
                    with gr.Tab("日报"):
                        daily_box = gr.Markdown("")
                    with gr.Tab("实验数据"):
                        gr.Markdown(
                            "六个场景各跑一遍的结果，含 12 条断言。"
                            "这张表是故障注入脚本生成的，不是界面上现算的。"
                        )
                        gr.Markdown(experiments_markdown())

        outputs = [summary, metrics, trace_box, card_pick, card_body, daily_box]
        button.click(do_run, inputs=[scenario, mode], outputs=outputs)
        card_pick.change(show_card, inputs=[card_pick, run_id], outputs=card_body)

        def _load() -> tuple:
            view = first_screen()
            # State 里要记下这次 run_id，卡片切换才知道去查哪一次
            return (*view, _last_run_id())

        demo.load(_load, outputs=[*outputs, run_id])
    return demo


def _last_run_id() -> str:
    """do_run 刚写进 RESULTS 的那次运行。"""
    try:
        return next(reversed(RESULTS))
    except StopIteration:
        return ""


def main() -> None:
    port = int(os.environ.get("CMON_UI_PORT", "7861"))
    build_ui().queue().launch(
        server_name=os.environ.get("CMON_UI_HOST", "127.0.0.1"),
        server_port=port,
        inbrowser=False,
    )


if __name__ == "__main__":
    main()