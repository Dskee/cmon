"""标题归一化。

中文商品标题不需要分词器。真正要做的是两件事：单位归一（128G = 128GB），
和卖点词表匹配。判定只用集合差集，只有"新增的词是不是在打价格战"才值得交给模型。
"""
from __future__ import annotations

import re

# 价格战信号词：这几类词出现或消失，说明对手在换打法
PRICE_WAR_TERMS = {"限时", "直降", "清仓", "秒杀", "买一送一", "低价", "特价", "甩卖", "第二件半价"}
SELLING_TERMS = {"包邮", "现货", "正品", "爆款", "新品", "加绒", "加厚", "大码", "显瘦",
                 "纯棉", "透气", "防滑", "便携", "可拆洗", "加大", "送礼"}

LEXICON = PRICE_WAR_TERMS | SELLING_TERMS

_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(gb|g|ml|l|cm|mm|kg|寸|件|支|片)\b", re.IGNORECASE)
_CAPACITY_RE = re.compile(r"(\d+)\s*[+＋]\s*(\d+)\s*(?:gb|g)", re.IGNORECASE)
# 数码商品里的大写 G 就是 GB（128G 内存卡），小写 g 才是克（350g 杯子）
_UPPER_G_RE = re.compile(r"(\d+(?:\.\d+)?)\s*G\b")


def normalize(title: str) -> str:
    text = _UPPER_G_RE.sub(lambda m: f"{m.group(1)}gb", title)
    text = text.lower()
    text = text.replace("＋", "+")
    # 容量/规格统一成小写紧凑写法：128 G → 128gb
    text = _UNIT_RE.sub(lambda m: f"{m.group(1)}{m.group(2).lower()}", text)
    text = _CAPACITY_RE.sub(lambda m: f"{m.group(1)}+{m.group(2)}gb", text)
    text = re.sub(r"[\s\u3000]+", " ", text).strip()
    return text


def terms(title: str) -> set[str]:
    """返回标题里命中的卖点词集合（含归一化后的规格串）。"""
    text = normalize(title)
    found = {w for w in LEXICON if w in text}
    found |= {m.group(0) for m in _UNIT_RE.finditer(text)}
    found |= {m.group(0) for m in _CAPACITY_RE.finditer(text)}
    return found


def price_war_terms(title: str) -> set[str]:
    text = normalize(title)
    return {w for w in PRICE_WAR_TERMS if w in text}


def diff(old: str, new: str) -> dict[str, list[str]]:
    a, b = terms(old), terms(new)
    return {"added": sorted(b - a), "removed": sorted(a - b)}