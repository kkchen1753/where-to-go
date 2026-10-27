"""讀取住宿清單 hotels.csv。一列是一間住宿的一種房型。"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

FIELDS = [
    "hotel_id", "name", "region", "room_type", "source", "source_ref",
    "url", "rating", "review_count", "note",
]
REQUIRED = ["hotel_id", "name", "room_type", "source"]


@dataclass
class Hotel:
    hotel_id: str
    name: str
    room_type: str
    source: str
    region: str = ""
    source_ref: str = ""
    url: str = ""
    rating: Optional[float] = None
    review_count: Optional[int] = None
    note: str = ""

    @property
    def key(self):
        return (self.hotel_id, self.room_type)


def _optional_number(value: str, cast, where: str, column: str):
    value = value.strip().replace(",", "")
    if not value:
        return None
    try:
        return cast(value)
    except ValueError:
        raise ValueError(f"{where}：{column}「{value}」不是數字") from None


def load_hotels(path: Path) -> List[Hotel]:
    if not path.exists():
        raise FileNotFoundError(
            f"找不到住宿清單 {path}，請先把 hotels.example.csv 複製成 hotels.csv 再修改"
        )
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} 缺少欄位：{', '.join(missing)}")

        hotels, seen, errors = [], set(), []
        for line_no, row in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in row.items() if k}
            if not any(row.values()):
                continue
            where = f"{path.name} 第 {line_no} 行"
            empty = [c for c in REQUIRED if not row.get(c)]
            if empty:
                errors.append(f"{where}：{', '.join(empty)} 不能空白")
                continue
            try:
                hotel = Hotel(
                    hotel_id=row["hotel_id"],
                    name=row["name"],
                    room_type=row["room_type"],
                    source=row["source"].lower(),
                    region=row.get("region", ""),
                    source_ref=row.get("source_ref", ""),
                    url=row.get("url", ""),
                    rating=_optional_number(row.get("rating", ""), float, where, "rating"),
                    review_count=_optional_number(
                        row.get("review_count", ""), int, where, "review_count"
                    ),
                    note=row.get("note", ""),
                )
            except ValueError as e:
                errors.append(str(e))
                continue
            if hotel.key in seen:
                errors.append(
                    f"{where}：{hotel.hotel_id} / {hotel.room_type} 重複出現"
                )
                continue
            seen.add(hotel.key)
            hotels.append(hotel)

    if errors:
        raise ValueError("住宿清單有錯誤：\n  " + "\n  ".join(errors))
    return hotels
