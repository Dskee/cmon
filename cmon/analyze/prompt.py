"""提示词。

模型只做解释：这个变化像什么、该建议什么、该避免什么，以及要不要出素材需求。
判断已经在前一层用规则做完了，事故事实以 evidence 为准，模型不许改数字。
"""
from __future__ import annotations

import json
from typing import Any

SYSTEM = """你在电商竞品监控系统里负责一件事：把一个已经被规则判定出来的事件，解释成运营能直接行动的建议。

硬性要求：
1. 事实只能来自输入里的 evidence，不许编造数字、日期、商品名。证据不足就直说不确定。
2. 输出必须是 JSON 对象，字段固定为 interpretation、confidence、action、avoid、material_request、topics、uncertainty。
3. action 必须是可执行动作（改什么、发给谁、多久内做），不要写"关注一下""持续观察"这类没有落点的词。
4. 不是每次都需要素材。只有当"换主图/补尺码表/做对比图"确实能解决问题时才填 material_request，否则留空字符串。
5. confidence 是 0 到 1 的实数，表示你对这条解释的把握，不是对事件的把握。
6. 中文回答，不写客套话，不超过 120 字。"""

SCHEMA_HINT = {
    "interpretation": "这个变化像什么，一到两句",
    "confidence": 0.0,
    "action": "运营接下来该做什么",
    "avoid": "不建议做什么，以及原因",
    "material_request": "需要的素材，没有就空字符串",
    "topics": ["领域标签"],
    "uncertainty": "还缺什么信息",
}


def build_user(event_type: str, item_id: str, scope: str, evidence: dict[str, Any],
               context: dict[str, Any] | None = None) -> str:
    payload = {
        "event_type": event_type,
        "item_id": item_id,
        "scope": scope,
        "evidence": evidence,
        "context": context or {},
        "output_schema": SCHEMA_HINT,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


AGGREGATE_SYSTEM = """同一个商品在一个时间窗里出现了多个事件，你要判断它们是同一件事的不同侧面，
还是互相矛盾。如果矛盾，指出来该听哪一个，并给出一个综合建议。

要求：输出 JSON，字段为 interpretation、confidence、action、avoid、material_request、topics、uncertainty。
中文，不超过 150 字。事实只来自输入。"""


def build_aggregate(item_id: str, events: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "event_type": "AGGREGATE",
            "item_id": item_id,
            "events": events,
            "output_schema": SCHEMA_HINT,
        },
        ensure_ascii=False,
        indent=2,
    )