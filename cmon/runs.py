"""一次运行的封装：跑、收集、整理成能直接摆到界面上的形状。

这里不含任何 UI 代码，也不 import gradio——前端换掉、改成 API 或 CLI，这一层都不用动。
测试因此也不需要浏览器环境。
"""
from __future__ import annotations

import contextlib
import io
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from .config import load
from .pipeline import Pipeline

# 界面上的指标按这个顺序展示：先看"花了多少"，再看"买到了什么"，最后看"省了多少"
METRIC_LABELS: list[tuple[str, str]] = [
    ("requests", "请求数"),
    ("events", "判定事件"),
    ("aggregations", "汇总次数"),
    ("llm_calls", "模型调用"),
    ("peak_qps", "实测峰值 QPS"),
    ("requests_saved_cross_tenant", "跨租户去重省下"),
    ("unchanged_snapshots", "指纹未变（仍判定）"),
    ("empty_responses", "空响应（不判定）"),
    ("llm_retry", "模型重试"),
    ("llm_prompt_tokens", "输入 token"),
    ("llm_completion_tokens", "输出 token"),
    ("llm_ms", "模型耗时 ms"),
]


@dataclass
class Card:
    name: str
    path: Path
    content: str


@dataclass
class RunResult:
    run_id: str
    scenario: str
    offline: bool
    metrics: dict[str, float]
    trace: str
    cards: list[Card] = field(default_factory=list)
    daily: str = ""
    failures: dict[str, int] = field(default_factory=dict)
    transitions: list[tuple[str, str, str, str]] = field(default_factory=list)
    out_dir: Path | None = None
    elapsed: float = 0.0

    def metric_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for key, label in METRIC_LABELS:
            if key not in self.metrics:
                continue
            value = self.metrics[key]
            shown = f"{value:,.0f}" if key != "peak_qps" else f"{value:.2f}"
            rows.append([label, shown])
        for key, value in sorted(self.metrics.items()):
            if key.startswith("state_"):
                rows.append([f"状态停留 · {key.removeprefix('state_')}", f"{value:,.0f}"])
        return rows

    def card_names(self) -> list[str]:
        return [c.name for c in self.cards]

    def card(self, name: str) -> str:
        for c in self.cards:
            if c.name == name:
                return c.content
        return ""


def _collect_cards(out_dir: Path) -> list[Card]:
    alerts = out_dir / "alerts"
    if not alerts.exists():
        return []
    cards = []
    for path in sorted(alerts.rglob("*.md"), key=_card_order):
        cards.append(Card(name=path.name, path=path,
                          content=path.read_text(encoding="utf-8")))
    return cards


def _card_order(path: Path) -> tuple[int, str]:
    """单条事件在前，汇总在后——汇总要读完前几条才看得懂。"""
    return (1 if "AGGREGATED" in path.name else 0, path.name)


def run_scenario(scenario: str, offline: bool = True,
                 workdir: Path | None = None) -> RunResult:
    """跑一个场景，把 trace 和卡片一起收好。

    trace 走的是 Pipeline 自己的 verbose 输出——界面显示的就是命令行会打印的东西，
    不另做一份摘要，免得两边不一致。
    """
    run_id = uuid.uuid4().hex[:12]
    # 默认落在项目里，跑完的卡片和日报还找得到；临时目录只给测试用
    root = Path(workdir) if workdir else Path("var") / "runs"
    root = root / run_id
    cfg = replace(load(), db_path=root / "cmon.db", out_dir=root / "out")

    buffer = io.StringIO()
    pipeline = Pipeline(cfg, scenario, offline=offline, verbose=True)
    started = time.monotonic()
    try:
        with contextlib.redirect_stdout(buffer):
            result = pipeline.run()
    finally:
        pipeline.close()
    elapsed = time.monotonic() - started

    return RunResult(
        run_id=run_id,
        scenario=scenario,
        offline=offline,
        metrics=result["metrics"],
        trace=buffer.getvalue(),
        cards=_collect_cards(cfg.out_dir),
        daily=(Path(result["daily"]).read_text(encoding="utf-8")
               if result.get("daily") and Path(result["daily"]).exists() else ""),
        failures=result.get("failures", {}),
        transitions=result.get("transitions", []),
        out_dir=cfg.out_dir,
        elapsed=elapsed,
    )


def scenario_choices() -> list[tuple[str, str]]:
    """给下拉框用：(显示文本, 值)。显示文本里带上窗口长度和一句话说明。"""
    from .mock.scenarios import SCENARIOS

    return [(f"{name} · {sc['hours']}h · {sc['title']}", name)
            for name, sc in SCENARIOS.items()]


def ensure_default_run() -> RunResult:
    return run_scenario("size-clearance", offline=True)


def describe_failures(result: RunResult) -> str:
    if not result.failures:
        return "无失败请求"
    return "，".join(f"{k}×{v}" for k, v in sorted(result.failures.items()))


def summary_markdown(result: RunResult) -> str:
    """运行结束后顶上那段话：一句话说清楚这次跑出了什么。"""
    m = result.metrics
    model = "离线替身" if result.offline else "真实模型"
    lines = [
        f"**{result.scenario}** · {model} · run `{result.run_id}`",
        "",
        f"- 请求 **{int(m.get('requests', 0))}** 次，"
        f"判定出 **{int(m.get('events', 0))}** 个事件，"
        f"汇总 **{int(m.get('aggregations', 0))}** 次，"
        f"模型调用 **{int(m.get('llm_calls', 0))}** 次",
        f"- 失败请求：{describe_failures(result)}",
        f"- 用时 {result.elapsed:.1f} 秒，卡片 {len(result.cards)} 张"
        + (f"，生成在 `{result.out_dir}`" if result.out_dir else ""),
    ]
    if result.transitions:
        lines.append("- 状态转换：" + "；".join(
            f"{name} {move}（{why}）" for name, move, _at, why in result.transitions))
    return "\n".join(x for x in lines if x)