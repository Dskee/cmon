"""真实模型冒烟：证明"离线替身"和"真实模型"走的是同一套契约。

跑法：
    python experiments/llm_smoke.py

它只做一件事：把一条真实事件的 evidence 发给硅基流动，用和线上一样的
parse() 校验返回值，打印延迟、token 用量和解析结果。没有 key 就跳过并说明原因——
这条链路必须能在没有 key 的机器上原样跑通，否则它就不是可交付的东西。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cmon.analyze import (
    llm,  # noqa: E402
    prompt,  # noqa: E402
)
from cmon.config import load  # noqa: E402


def main() -> int:
    cfg = load()
    if not cfg.llm.api_key:
        print("没有 CMON_LLM_API_KEY，跳过真实调用（离线替身覆盖同一套契约）。")
        return 0

    evidence = {
        "baseline": 109.0, "current": 95.9, "delta_pct": -12.0,
        "sustained_hours": 2.0, "samples": 4,
    }
    context = {"scope": "competitor", "final_price": 95.9, "error_band": 0.03,
               "stock_tier": "in_stock", "reviews": {"total": 344, "negative": 68,
                                                    "topics": {"尺码": 0.6}}}
    user = prompt.build_user("PRICE_DROP", "C8848", "competitor", evidence, context)

    client = llm.build(cfg.llm)
    print(f"模型：{cfg.llm.model}")
    print(f"端点：{cfg.llm.base_url}")
    print(f"提示词：system {len(prompt.SYSTEM)} 字，user {len(user)} 字")

    started = time.perf_counter()
    try:
        raw = client.chat(prompt.SYSTEM, user)
    except llm.LlmError as exc:
        msg = str(exc)
        print(f"调用失败：{msg}")
        if "402" in msg or "insufficient" in msg:
            print("这是账户余额问题，不是代码问题：请求已经打到端点并被受理。")
        elif "401" in msg:
            print("这是 key 无效或过期：检查 .env 里的 CMON_LLM_API_KEY。")
        return 1
    cost_ms = int((time.perf_counter() - started) * 1000)

    data = llm.parse(raw)
    print(f"延迟：{cost_ms} ms")
    print(f"原始返回：{len(raw)} 字")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("契约校验：通过（字段齐全，confidence 在 0—1 之间）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())