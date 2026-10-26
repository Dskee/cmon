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
4. material_request 是给美工的素材单，写"要做什么素材"，例如"主图尺码对照表""与竞品的价格对比图"。
   不是"需要哪些数据"——缺的数据写进 uncertainty。不需要素材就留空字符串。
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


AGGREGATE_SYSTEM = """同一个商品在一个时间窗里出现了多个事件。你的任务是给出一条因果假设：
这些变化是不是同一个原因造成的。

第一句必须表态，只能二选一：
A. 同一件事的不同侧面（写出那个共同原因，例如"对手在清某个尺码的库存"）；
B. 确实无关（写出你凭什么排除共同原因：时间对不上、同类商品也在动、或字段之间没有逻辑关系）。
第一句直接写结论，不要带"A.""B."这类编号，也不要复述选项。
不许写"两者独立但需并行应对"这种不表态的句子——那等于没做汇总。

因果链要站得住：每推进一环，都要能对上前面的证据。中间某步没有证据支撑时，
明确写"这一步是推测"。不要把互斥的状态并列（既"滞销"又"卖光"），
挑一种能自圆其说的写法。

要求：输出 JSON，字段为 interpretation、confidence、action、avoid、material_request、topics、uncertainty。
material_request 是给美工的素材单（如"主图尺码对照表"），不是需要的数据。
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