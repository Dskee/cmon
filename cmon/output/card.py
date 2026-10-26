"""告警卡片与日报。

卡片是这套系统的最终产出，也是输出契约所在：字段固定，AI 美工那条线按 material_request
接走就能出图，不需要再理解业务语义。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Event


def render_card(ev: Event) -> str:
    ev_type = ev.event_type
    lines = [
        f"# 竞品变化告警 · {ev.item_id}",
        "",
        f"- 事件：`{ev_type}`",
        f"- 时间：{ev.detected_at:%Y-%m-%d %H:%M}",
        f"- 置信度：{ev.confidence:.2f}",
        "",
        "## 证据",
        "",
    ]
    for key, value in ev.evidence.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(f"- **{key}**")
            for row in value:
                lines.append("  - " + "，".join(f"{k}={v}" for k, v in row.items()))
        elif isinstance(value, list):
            lines.append(f"- **{key}**：{'、'.join(map(str, value)) or '无'}")
        else:
            lines.append(f"- **{key}**：{value}")

    lines += [
        "",
        "## 判断",
        "",
        ev.interpretation or "（无）",
        "",
        "## 建议动作",
        "",
        ev.action or "（无）",
        "",
        "## 不建议",
        "",
        ev.avoid or "（无）",
        "",
    ]
    if ev.material_request:
        lines += [
            "## 素材需求",
            "",
            ev.material_request,
            "",
            "> 这条会直接进美工队列，字段固定，不需要二次解释。",
            "",
        ]
    lines += [
        "---",
        "",
        f"生成于 {datetime.now():%Y-%m-%d %H:%M:%S} · cmon 0.1.0",
    ]
    return "\n".join(lines)


def render_daily(date: str, events: list[dict[str, Any]], metrics: dict[str, float]) -> str:
    lines = [
        f"# 竞品监控日报 · {date}",
        "",
        "## 今日事件",
        "",
        "| 时间 | 商品 | 类型 | 置信度 | 建议 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for ev in events:
        payload = ev.get("payload") or {}
        if isinstance(payload, str):
            import json

            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        action = (payload.get("action") or "").replace("|", "/")[:40]
        lines.append(
            f"| {ev['detected_at'][11:16]} | {ev['item_id']} | {ev['event_type']} "
            f"| {payload.get('confidence', '-')} | {action} |"
        )
    if not events:
        lines.append("| - | - | 无事件 | - | - |")

    lines += ["", "## 运行指标", "", "| 指标 | 值 |", "| --- | --- |"]
    for name, value in sorted(metrics.items()):
        lines.append(f"| {name} | {value:g} |")
    return "\n".join(lines)


def write_card(out_dir: Path, ev: Event) -> str:
    day = ev.detected_at.strftime("%Y-%m-%d")
    folder = out_dir / "alerts" / day
    folder.mkdir(parents=True, exist_ok=True)
    # 文件名带时间戳：同一商品同一天出两次同类事件时不能互相覆盖
    path = folder / f"{ev.item_id}-{ev.event_type}-{ev.detected_at:%H%M}.md"
    path.write_text(render_card(ev), encoding="utf-8")
    return str(path)


def write_daily(out_dir: Path, date: str, events: list[dict[str, Any]],
                metrics: dict[str, float]) -> str:
    folder = out_dir / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{date}.md"
    path.write_text(render_daily(date, events, metrics), encoding="utf-8")
    return str(path)