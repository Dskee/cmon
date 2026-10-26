"""配置加载：settings.toml + .env，环境变量优先。"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "settings.toml"


def _load_dotenv(path: Path) -> None:
    """把 .env 读进 os.environ，已存在的变量不覆盖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT / ".env")


@dataclass
class CollectConfig:
    global_qps: float
    source_qps: float
    item_min_interval_min: int
    jitter_max_sec: int
    tick_min: int
    freq_min: dict[str, int]
    ttl_min: int
    pause: dict[str, Any]


@dataclass
class JudgeConfig:
    price_drop_pct: float
    sustain_hours: int
    baseline_days: int
    title_token_new_min: int
    review_topic_jump_pp: float
    review_min_samples: int
    cooldown_hours: int


@dataclass
class LlmConfig:
    base_url: str
    model: str
    timeout_sec: int
    max_retries: int
    temperature: float
    api_key: str = field(default="", repr=False)


@dataclass
class Config:
    db_path: Path
    out_dir: Path
    day_start_hour: int
    collect: CollectConfig
    judge: JudgeConfig
    llm: LlmConfig


def load(path: Path | None = None) -> Config:
    raw = tomllib.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))
    app, col, jud, llm = raw["app"], raw["collect"], raw["judge"], raw["llm"]

    collect = CollectConfig(
        global_qps=col["global_qps"],
        source_qps=col["source_qps"],
        item_min_interval_min=col["item_min_interval_min"],
        jitter_max_sec=col["jitter_max_sec"],
        tick_min=col["tick_min"],
        freq_min=dict(col["freq_min"]),
        ttl_min=col["dedup"]["ttl_min"],
        pause=dict(col["pause"]),
    )
    judge = JudgeConfig(
        price_drop_pct=jud["price_drop_pct"],
        sustain_hours=jud["sustain_hours"],
        baseline_days=jud["baseline_days"],
        title_token_new_min=jud["title_token_new_min"],
        review_topic_jump_pp=jud["review_topic_jump_pp"],
        review_min_samples=jud["review_min_samples"],
        cooldown_hours=jud["cooldown_hours"],
    )
    llm_cfg = LlmConfig(
        base_url=os.environ.get("CMON_LLM_BASE_URL", llm["base_url"]),
        model=os.environ.get("CMON_LLM_MODEL", llm["model"]),
        timeout_sec=llm["timeout_sec"],
        max_retries=llm["max_retries"],
        temperature=llm["temperature"],
        api_key=os.environ.get("CMON_LLM_API_KEY", ""),
    )
    return Config(
        db_path=ROOT / app["db_path"],
        out_dir=ROOT / app["out_dir"],
        day_start_hour=app["day_start_hour"],
        collect=collect,
        judge=judge,
        llm=llm_cfg,
    )