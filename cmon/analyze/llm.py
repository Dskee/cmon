"""模型接入。OpenAI 兼容协议，只依赖标准库。

关键约束：这一层必须可以被替换掉。没有 key、没有网络、额度用完，整条链路还要能跑通，
所以有 StubClient；它按事件类型给出确定性的解释，让测试和演示不受外部服务影响。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import LlmConfig

REQUIRED_KEYS = {"interpretation", "confidence", "action", "avoid"}


class LlmError(RuntimeError):
    pass


class LlmClient:
    def chat(self, system: str, user: str) -> str:  # pragma: no cover - 接口
        raise NotImplementedError


class SiliconFlowClient(LlmClient):
    def __init__(self, cfg: LlmConfig) -> None:
        self.cfg = cfg
        self.last_usage: dict[str, int] = {}
        if not cfg.api_key:
            raise LlmError("缺少 CMON_LLM_API_KEY，改用 --offline 或填写 .env")

    def chat(self, system: str, user: str) -> str:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(
            {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.cfg.temperature,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise LlmError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LlmError(f"网络异常: {exc}") from exc

        try:
            self.last_usage = payload.get("usage") or {}
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LlmError(f"响应结构不符: {payload}") from exc


class StubClient(LlmClient):
    """离线替身：按事件类型返回确定性解释，用于测试与断网演示。"""

    TEMPLATES = {
        "PRICE_DROP": {
            "interpretation": "对手在主动让价，幅度超出常规促销区间，先按引流款对待",
            "confidence": 0.72,
            "action": "不跟价，先把自家同款的主图与尺码说明补齐，观察两轮再决定",
            "avoid": "直接跟到同价，毛利会被打穿且对手可继续下探",
        },
        "REVIEW_TOPIC_SHIFT": {
            "interpretation": "差评从履约问题转向商品本身，说明货或描述有偏差",
            "confidence": 0.66,
            "action": "补尺码表并对齐模特身高体重，详情页加一条退换说明",
            "avoid": "只加客服话术，不解决尺码信息缺失",
        },
        "TITLE_CHANGE": {
            "interpretation": "标题加入价格战信号词，可能在为活动预热",
            "confidence": 0.58,
            "action": "观察两轮到手价，不要仅凭标题跟进",
            "avoid": "标题跟风改词，会打乱自己的搜索权重",
        },
        "STOCK_OUT": {
            "interpretation": "对手断货，流量可能外溢",
            "confidence": 0.70,
            "action": "同款加投推广，把承接页的尺码与现货信息写清楚",
            "avoid": "同时提价，会浪费这次流量窗口",
        },
        "IMAGE_CHANGE": {
            "interpretation": "对手换了主图，可能在测新卖点",
            "confidence": 0.55,
            "action": "记录下来，连续两次换图再考虑跟进",
            "avoid": "单次换图就跟着改，浪费素材产能",
        },
        "DESC_CHANGE": {
            "interpretation": "详情页文案调整，卖点结构可能变了",
            "confidence": 0.50,
            "action": "人工看一眼详情页首屏",
            "avoid": "全量重做详情页",
        },
        "AGGREGATE": {
            "interpretation": "降价和差评转向尺码指向同一件事：对手在清某个尺码的库存，不是常规让利",
            "confidence": 0.74,
            "action": "别跟价。补齐自家同款尺码表并对齐模特身高体重，把退换说明放到首屏",
            "avoid": "跟着降价，等于替对手接掉这批货的压力",
            "material_request": "主图一张：尺码对照表（身高/体重/建议码），附一句'不合适免费换'",
        },
    }

    def chat(self, system: str, user: str) -> str:
        event_type = "PRICE_DROP"
        try:
            payload = json.loads(user)
            event_type = payload.get("event_type", event_type)
        except (ValueError, AttributeError):
            pass
        tpl = dict(self.TEMPLATES.get(event_type, self.TEMPLATES["PRICE_DROP"]))
        low = dict(tpl)
        low["confidence"] = round(max(0.0, min(1.0, tpl["confidence"] - 0.15)), 2)
        return json.dumps(
            {
                **tpl,
                "topics": ["价格", "竞品"],
                "uncertainty": "离线替身输出，未读取真实上下文",
                "low_confidence_variant": low,
            },
            ensure_ascii=False,
        )


def build(cfg: LlmConfig, offline: bool = False) -> LlmClient:
    if offline or not cfg.api_key:
        return StubClient()
    return SiliconFlowClient(cfg)


def parse(raw: str) -> dict[str, Any]:
    """解析并校验模型输出。缺字段、越界一律判失败，由调用方重试一次。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    data = json.loads(text)
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise LlmError(f"缺少字段 {sorted(missing)}")
    conf = float(data["confidence"])
    if not 0.0 <= conf <= 1.0:
        raise LlmError(f"confidence 越界: {conf}")
    data["confidence"] = conf
    return data