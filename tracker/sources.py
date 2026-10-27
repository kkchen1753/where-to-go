"""自動抓價的資料來源。

每個來源實作 PriceSource.fetch()，回傳某住宿某入住日（住一晚）的報價，
再登記到 SOURCES。hotels.csv 的 source 欄位填來源名稱，
source_ref 填該來源認得的住宿代號（網址、ID 等）。

source 填 manual 的住宿不走這裡，改用 template／import 人工輸入。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Type

from .hotels import Hotel

MANUAL = "manual"


@dataclass
class Quote:
    price: Optional[int]
    available: bool
    currency: str = "TWD"
    note: str = ""


class PriceSource:
    name = ""
    # 會連網的來源，每次請求之間要等 request_delay_seconds
    uses_network = True

    def fetch(self, hotel: Hotel, checkin: date) -> Quote:
        raise NotImplementedError


class DemoSource(PriceSource):
    """假資料，用來測試流程與後續的溢價計算、網頁。不要拿來發布。"""

    name = "demo"
    uses_network = False

    @staticmethod
    def _unit(*parts) -> float:
        digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2 ** 64

    def fetch(self, hotel: Hotel, checkin: date) -> Quote:
        base = 1800 + round(self._unit(hotel.hotel_id, "base") * 4200, -2)
        # 每間住宿有自己的週末加價習慣：-5% ～ +40%
        sat_premium = -0.05 + self._unit(hotel.hotel_id, "premium") * 0.45
        noise = (self._unit(hotel.hotel_id, hotel.room_type, checkin) - 0.5) * 0.06
        if self._unit(hotel.hotel_id, checkin, "sold-out") < 0.05:
            return Quote(price=None, available=False, note="demo")
        factor = 1 + noise + (sat_premium if checkin.weekday() == 5 else 0)
        return Quote(price=int(round(base * factor, -1)), available=True, note="demo")


SOURCES: Dict[str, Type[PriceSource]] = {
    DemoSource.name: DemoSource,
}


def get_source(name: str) -> PriceSource:
    try:
        return SOURCES[name]()
    except KeyError:
        known = ", ".join(sorted([MANUAL, *SOURCES]))
        raise ValueError(f"不認得的資料來源「{name}」，目前支援：{known}") from None
