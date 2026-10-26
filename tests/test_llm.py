"""模型输出契约：解析要严，替身要稳。

这一层的价值不在"能调通 API"，在于"外部服务挂了整条链路还能跑"。
"""
import json

import pytest

from cmon.analyze import llm
from cmon.config import LlmConfig


def cfg(**kw) -> LlmConfig:
    base = dict(base_url="https://api.siliconflow.cn/v1", model="test-model",
                timeout_sec=45, max_retries=1, temperature=0.2, api_key="")
    base.update(kw)
    return LlmConfig(**base)


def test_parse_accepts_a_complete_payload():
    raw = json.dumps({"interpretation": "对手在让价", "confidence": 0.7,
                      "action": "观望", "avoid": "跟价"}, ensure_ascii=False)
    data = llm.parse(raw)
    assert data["confidence"] == 0.7
    assert data["action"] == "观望"


def test_parse_strips_code_fences():
    raw = '```json\n{"interpretation": "x", "confidence": 0.5, "action": "y", "avoid": "z"}\n```'
    assert llm.parse(raw)["interpretation"] == "x"


def test_parse_rejects_missing_fields():
    raw = json.dumps({"interpretation": "x", "confidence": 0.5})
    with pytest.raises(llm.LlmError, match="缺少字段"):
        llm.parse(raw)


def test_parse_rejects_out_of_range_confidence():
    raw = json.dumps({"interpretation": "x", "confidence": 1.4, "action": "y", "avoid": "z"})
    with pytest.raises(llm.LlmError, match="越界"):
        llm.parse(raw)


def test_parse_rejects_non_json():
    with pytest.raises(ValueError):
        llm.parse("这是一段解释，不是 JSON")


def test_offline_build_returns_the_stub():
    assert isinstance(llm.build(cfg(api_key="sk-test"), offline=True), llm.StubClient)


def test_missing_key_falls_back_to_the_stub():
    assert isinstance(llm.build(cfg(api_key="")), llm.StubClient)


def test_client_requires_a_key():
    with pytest.raises(llm.LlmError, match="缺少 CMON_LLM_API_KEY"):
        llm.SiliconFlowClient(cfg(api_key=""))


def test_stub_follows_the_event_type():
    stub = llm.StubClient()
    agg = json.loads(stub.chat("system", json.dumps({"event_type": "AGGREGATE"})))
    assert "尺码" in agg["material_request"]
    price = json.loads(stub.chat("system", json.dumps({"event_type": "PRICE_DROP"})))
    assert price.get("material_request", "") == ""


def test_stub_output_passes_our_own_parser():
    stub = llm.StubClient()
    for event_type in ("PRICE_DROP", "REVIEW_TOPIC_SHIFT", "TITLE_CHANGE",
                       "STOCK_OUT", "IMAGE_CHANGE", "DESC_CHANGE", "AGGREGATE"):
        data = llm.parse(stub.chat("system", json.dumps({"event_type": event_type})))
        assert 0.0 <= data["confidence"] <= 1.0