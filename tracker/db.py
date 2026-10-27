"""價格快照資料庫（SQLite）。"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_snapshots (
    captured_on TEXT NOT NULL,      -- 抓價日 YYYY-MM-DD
    hotel_id    TEXT NOT NULL,
    room_type   TEXT NOT NULL,
    checkin     TEXT NOT NULL,      -- 入住日 YYYY-MM-DD，住一晚
    price       INTEGER,            -- 含稅總價；無房時為 NULL
    available   INTEGER NOT NULL,   -- 1 有房、0 無房
    currency    TEXT NOT NULL DEFAULT 'TWD',
    source      TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (captured_on, hotel_id, room_type, checkin, source)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_hotel
    ON price_snapshots (hotel_id, room_type, checkin);
"""


@dataclass
class Snapshot:
    captured_on: str
    hotel_id: str
    room_type: str
    checkin: str
    price: Optional[int]
    available: bool
    source: str
    currency: str = "TWD"
    note: str = ""

    def __post_init__(self):
        if self.available and (self.price is None or self.price <= 0):
            raise ValueError(
                f"{self.hotel_id} {self.checkin}：有房的話價格必須是正整數"
            )
        if not self.available:
            self.price = None


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_snapshots(conn: sqlite3.Connection, snapshots: Iterable[Snapshot]) -> int:
    """寫入快照；同一天重複抓同一筆會覆蓋。回傳寫入筆數。"""
    rows = [
        (s.captured_on, s.hotel_id, s.room_type, s.checkin, s.price,
         int(s.available), s.currency, s.source, s.note)
        for s in snapshots
    ]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO price_snapshots "
            "(captured_on, hotel_id, room_type, checkin, price, available, "
            " currency, source, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def coverage(conn: sqlite3.Connection):
    """每間住宿／房型的資料累積狀況。"""
    return conn.execute(
        """
        SELECT hotel_id, room_type,
               COUNT(DISTINCT captured_on) AS days_captured,
               MIN(captured_on) AS first_captured,
               MAX(captured_on) AS last_captured,
               SUM(available) AS priced,
               SUM(1 - available) AS sold_out
        FROM price_snapshots
        GROUP BY hotel_id, room_type
        ORDER BY hotel_id, room_type
        """
    ).fetchall()


EXPORT_COLUMNS = [
    "captured_on", "hotel_id", "room_type", "checkin", "price",
    "available", "currency", "source", "note",
]


def export_csv(conn: sqlite3.Connection, path: Path) -> int:
    rows = conn.execute(
        f"SELECT {', '.join(EXPORT_COLUMNS)} FROM price_snapshots "
        "ORDER BY captured_on, hotel_id, room_type, checkin"
    ).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig 讓 Excel 直接打開不會亂碼
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(EXPORT_COLUMNS)
        writer.writerows(tuple(r) for r in rows)
    return len(rows)
