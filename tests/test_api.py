"""HTTP 层：只测四个端点做了什么，不测框架。

关键的一条是 POST /runs 必须立刻返回——它是"触发一次采集"的接口，
如果它把整轮跑完再返回，调用方就会超时，整个设计也就退化成 CLI 套壳。
"""
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from cmon import api  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from dataclasses import replace

    from cmon.config import load

    def cfg_for(run_id: str):
        root = tmp_path / run_id
        return replace(load(), db_path=root / "cmon.db", out_dir=root / "out")

    monkeypatch.setattr(api, "_cfg_for", cfg_for)
    api.RUNS.clear()
    with TestClient(api.app) as c:
        yield c


def wait_done(client, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("运行没有在超时前结束")


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_scenarios_are_listed(client):
    names = {s["name"] for s in client.get("/scenarios").json()}
    assert {"price-drop", "fault-storm", "empty-silent"} <= names


def test_start_run_returns_immediately(client):
    started = time.perf_counter()
    body = client.post("/runs", json={"scenario": "price-drop"}).json()
    elapsed = time.perf_counter() - started
    assert body["status"] == "running"
    assert elapsed < 1.0        # 不能等整轮跑完


def test_run_finishes_and_reports_metrics(client):
    run_id = client.post("/runs", json={"scenario": "price-drop"}).json()["run_id"]
    body = wait_done(client, run_id)
    assert body["status"] == "done"
    assert body["metrics"]["events"] == 2
    assert len(body["events"]) == 3      # 两条判定 + 一条汇总


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404


def test_alerts_are_queryable_by_item(client):
    run_id = client.post("/runs", json={"scenario": "price-drop"}).json()["run_id"]
    wait_done(client, run_id)

    all_rows = client.get("/alerts", params={"run_id": run_id}).json()
    assert len(all_rows) == 3
    one = client.get("/alerts", params={"run_id": run_id, "item_id": "C8848"}).json()
    assert one and all(r["item_id"] == "C8848" for r in one)
    assert client.get("/alerts", params={"run_id": run_id, "item_id": "不存在"}).json() == []


def test_unknown_scenario_fails_loudly(client):
    run_id = client.post("/runs", json={"scenario": "no-such"}).json()["run_id"]
    body = wait_done(client, run_id)
    assert body["status"] == "failed"
    assert "error" in body