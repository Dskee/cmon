"""HTTP 层：把批处理包成可以被调用的服务。

设计上只做四件事，别的一律不做：
    POST /runs          触发一次运行，立刻返回 run_id，不阻塞
    GET  /runs/{id}     查这次运行的指标与状态
    GET  /alerts        按商品查告警，跨运行
    GET  /stream        SSE，边跑边推卡片

没有数据库连接池、没有任务队列、没有认证——这个项目要证明的是调度与判定的正确性，
不是 web 框架的用法。真要上线，认证和鉴权应该在网关注入，而不是长在这里。
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import load
from .db import Store
from .pipeline import Pipeline

app = FastAPI(
    title="cmon",
    version="0.1.0",
    description="可复现的商品监控调度器：三层限流、三层去重、五态状态机。",
)

RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


class RunRequest(BaseModel):
    scenario: str = Field(default="price-drop", description="场景名，见 /scenarios")
    offline: bool = Field(default=True, description="离线替身模型，不产生 API 费用")


class RunAccepted(BaseModel):
    run_id: str
    status: str
    stream: str


def _cfg_for(run_id: str):
    root = Path("var") / "runs" / run_id
    return replace(load(), db_path=root / "cmon.db", out_dir=root / "out")


def _execute(run_id: str, scenario: str, offline: bool) -> None:
    record = RUNS[run_id]
    try:
        cfg = _cfg_for(run_id)
        events: list[dict[str, Any]] = []
        pipeline = Pipeline(cfg, scenario, offline=offline, verbose=False)
        pipeline.on_event = lambda ev: events.append(  # type: ignore[attr-defined]
            {"item_id": ev.item_id, "event_type": ev.event_type,
             "detected_at": ev.detected_at.isoformat(), "action": ev.action}
        )
        result = pipeline.run()
        pipeline.close()
        with _LOCK:
            record.update(
                status="done",
                metrics=result["metrics"],
                transitions=len(result["transitions"]),
                events=events,
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
    except Exception as exc:                     # noqa: BLE001 - 失败也要能查到原因
        with _LOCK:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/scenarios")
def scenarios() -> list[dict[str, str]]:
    from .mock.scenarios import SCENARIOS

    return [{"name": name, "title": sc["title"]} for name, sc in SCENARIOS.items()]


@app.post("/runs", response_model=RunAccepted, status_code=202)
def start_run(body: RunRequest) -> RunAccepted:
    run_id = uuid.uuid4().hex[:12]
    with _LOCK:
        RUNS[run_id] = {
            "run_id": run_id,
            "scenario": body.scenario,
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
    threading.Thread(target=_execute, args=(run_id, body.scenario, body.offline),
                     daemon=True).start()
    return RunAccepted(run_id=run_id, status="running", stream=f"/stream?run_id={run_id}")


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有这个 run")
    return record


@app.get("/alerts")
def list_alerts(item_id: str | None = Query(default=None, description="按商品过滤"),
                run_id: str | None = Query(default=None),
                limit: int = Query(default=50, le=500)) -> list[dict[str, Any]]:
    if run_id:
        cfg = _cfg_for(run_id)
    else:
        cfg = load()
    if not Path(cfg.db_path).exists():
        return []
    store = Store(cfg.db_path)
    try:
        rows = store.recent_events(limit)
    finally:
        store.close()
    out = []
    for row in rows:
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        if item_id and row["item_id"] != item_id:
            continue
        out.append({**{k: row[k] for k in ("item_id", "event_type", "detected_at")},
                    "confidence": payload.get("confidence"),
                    "action": payload.get("action")})
    return out


@app.get("/stream")
async def stream(run_id: str) -> StreamingResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="没有这个 run")

    async def gen():
        sent = 0
        for _ in range(600):
            record = RUNS[run_id]
            events = record.get("events") or []
            while sent < len(events):
                yield f"data: {json.dumps(events[sent], ensure_ascii=False)}\n\n"
                sent += 1
            if record["status"] != "running":
                yield f"data: {json.dumps({'status': record['status']}, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()