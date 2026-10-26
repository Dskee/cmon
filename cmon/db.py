"""SQLite 存储。三张主表 + 两张运行态表。

不引 ORM：表少、查询固定，手写 SQL 更省事，也方便把执行计划贴到 README 里。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Event, Snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    final_price REAL,
    list_price  REAL,
    fingerprint TEXT,
    quality_ok  INTEGER NOT NULL DEFAULT 1,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshot_item_time ON snapshot(item_id, captured_at);

CREATE TABLE IF NOT EXISTS event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    payload     TEXT NOT NULL,
    alert_path  TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_time ON event(detected_at);

CREATE TABLE IF NOT EXISTS item_state (
    item_id        TEXT PRIMARY KEY,
    below_since    TEXT,
    last_event_at  TEXT,
    last_final     REAL,
    last_title     TEXT,
    last_stock     TEXT,
    last_images    TEXT,
    last_reviews   TEXT,
    last_desc_hash TEXT
);

CREATE TABLE IF NOT EXISTS source_state (
    source       TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    fail_streak  INTEGER NOT NULL DEFAULT 0,
    errors       TEXT NOT NULL DEFAULT '[]',
    pause_until  TEXT,
    probe_ratio  REAL NOT NULL DEFAULT 1.0,
    probe_ok     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metric (
    name  TEXT PRIMARY KEY,
    value REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- snapshot ----------

    def add_snapshot(self, snap: Snapshot) -> int:
        cur = self.conn.execute(
            "INSERT INTO snapshot(item_id,captured_at,final_price,list_price,fingerprint,"
            "quality_ok,payload) VALUES(?,?,?,?,?,?,?)",
            (
                snap.item_id,
                snap.captured_at.isoformat(),
                snap.final_price,
                snap.list_price,
                snap.fingerprint,
                1 if snap.quality_ok else 0,
                json.dumps(snap.to_payload(), ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def prices_since(self, item_id: str, since: datetime,
                     before: datetime | None = None) -> list[float]:
        sql = ("SELECT final_price FROM snapshot WHERE item_id=? AND captured_at>=? "
               "AND final_price IS NOT NULL AND quality_ok=1")
        args: list[Any] = [item_id, since.isoformat()]
        if before is not None:
            sql += " AND captured_at<?"
            args.append(before.isoformat())
        sql += " ORDER BY captured_at"
        rows = self.conn.execute(sql, tuple(args)).fetchall()
        return [r["final_price"] for r in rows]

    def last_fingerprint(self, item_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT fingerprint FROM snapshot WHERE item_id=? ORDER BY id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        return row["fingerprint"] if row else None

    def snapshot_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) c FROM snapshot").fetchone()["c"])

    # ---------- item state ----------

    def get_item_state(self, item_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM item_state WHERE item_id=?", (item_id,)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO item_state(item_id) VALUES(?)", (item_id,))
            self.conn.commit()
            return {"item_id": item_id}
        return dict(row)

    def save_item_state(self, item_id: str, **fields) -> None:
        if not fields:
            return
        self.get_item_state(item_id)   # 先确保这一行存在，否则 UPDATE 命中 0 行、静默丢状态
        cols = ",".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE item_state SET {cols} WHERE item_id=?", (*fields.values(), item_id)
        )
        self.conn.commit()

    # ---------- event ----------

    def add_event(self, ev: Event) -> int:
        cur = self.conn.execute(
            "INSERT INTO event(item_id,event_type,detected_at,payload,alert_path) VALUES(?,?,?,?,?)",
            (
                ev.item_id,
                ev.event_type,
                ev.detected_at.isoformat(),
                json.dumps(
                    {
                        "evidence": ev.evidence,
                        "interpretation": ev.interpretation,
                        "confidence": ev.confidence,
                        "action": ev.action,
                        "avoid": ev.avoid,
                        "material_request": ev.material_request,
                    },
                    ensure_ascii=False,
                ),
                ev.alert_path,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM event ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def event_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) c FROM event").fetchone()["c"])

    # ---------- metric ----------

    def incr(self, name: str, delta: float = 1.0) -> None:
        self.conn.execute(
            "INSERT INTO metric(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
            (name, delta),
        )
        self.conn.commit()

    def metrics(self) -> dict[str, float]:
        rows = self.conn.execute("SELECT name,value FROM metric").fetchall()
        return {r["name"]: r["value"] for r in rows}

    def reset(self) -> None:
        for table in ("snapshot", "event", "item_state", "source_state", "metric"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()