"""人工輸入：產生空白填價表，填好後匯入資料庫。"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Iterable, List

from .db import Snapshot
from .dates import weekday_label
from .hotels import Hotel
from .sources import MANUAL

COL_CAPTURED = "抓價日期"
COL_ID = "住宿ID"
COL_NAME = "名稱"
COL_ROOM = "房型"
COL_CHECKIN = "入住日"
COL_WEEKDAY = "星期"
COL_PRICE = "價格"
COL_SOLD_OUT = "無房"
COL_NOTE = "備註"
COL_URL = "網址"
TEMPLATE_COLUMNS = [
    COL_CAPTURED, COL_ID, COL_NAME, COL_ROOM, COL_CHECKIN, COL_WEEKDAY,
    COL_PRICE, COL_SOLD_OUT, COL_NOTE, COL_URL,
]


def write_template(
    path: Path, hotels: Iterable[Hotel], checkins: List[date], captured_on: date
) -> int:
    rows = [
        {
            COL_CAPTURED: captured_on.isoformat(),
            COL_ID: h.hotel_id,
            COL_NAME: h.name,
            COL_ROOM: h.room_type,
            COL_CHECKIN: d.isoformat(),
            COL_WEEKDAY: weekday_label(d),
            COL_URL: h.url,
        }
        for h in hotels if h.source == MANUAL
        for d in checkins
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _parse_price(text: str) -> int:
    cleaned = re.sub(r"(?i)nt\$|twd|\$|元|,|\s", "", text)
    if not cleaned.isdigit() or int(cleaned) <= 0:
        raise ValueError(f"價格「{text}」不是正整數")
    return int(cleaned)


def _parse_date(text: str, column: str) -> str:
    try:
        return date.fromisoformat(text.replace("/", "-")).isoformat()
    except ValueError:
        raise ValueError(f"{column}「{text}」格式要是 YYYY-MM-DD") from None


def read_filled(path: Path, hotels: Iterable[Hotel]) -> List[Snapshot]:
    """讀取填好的表。價格和無房都空白的列視為沒填，略過。

    任何一列有錯就整份不匯入，避免錯的價格混進資料庫。
    """
    known = {h.key for h in hotels}
    snapshots, errors = [], []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        needed = [COL_CAPTURED, COL_ID, COL_ROOM, COL_CHECKIN, COL_PRICE, COL_SOLD_OUT]
        missing = [c for c in needed if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} 缺少欄位：{', '.join(missing)}")

        for line_no, row in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in row.items() if k}
            price_text, sold_out = row.get(COL_PRICE, ""), row.get(COL_SOLD_OUT, "")
            if not price_text and not sold_out:
                continue
            where = f"第 {line_no} 行"
            try:
                key = (row[COL_ID], row[COL_ROOM])
                if key not in known:
                    raise ValueError(f"{key[0]} / {key[1]} 不在 hotels.csv 裡")
                if price_text and sold_out:
                    raise ValueError("「價格」和「無房」只能擇一填寫")
                snapshots.append(Snapshot(
                    captured_on=_parse_date(row[COL_CAPTURED], COL_CAPTURED),
                    hotel_id=key[0],
                    room_type=key[1],
                    checkin=_parse_date(row[COL_CHECKIN], COL_CHECKIN),
                    price=_parse_price(price_text) if price_text else None,
                    available=not sold_out,
                    source=MANUAL,
                    note=row.get(COL_NOTE, ""),
                ))
            except ValueError as e:
                errors.append(f"{where}：{e}")

    if errors:
        raise ValueError(
            f"{path.name} 有 {len(errors)} 個錯誤，整份沒有匯入：\n  "
            + "\n  ".join(errors)
        )
    return snapshots
