"""週末溢價指數。

同一間、同一房型，「一般週六入住價」對比「同月份一般平日（週日～週四）均價」。

- 同一個入住日每天都會抓一次價，取所有抓價的中位數，避免單日特價誤判。
- 連假、補班、國定假日前夕、自訂特殊日期不列入計算（見 calendar.py）。
- 每個週六跟「自己那個月」的平日均價比；整體溢價 = 週六均價 ÷ 對應平日均價 − 1。
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from .calendar import SATURDAY, SPECIAL, WEEKDAY, Calendar
from .hotels import Hotel

BADGE_NO_MARKUP = "週末不加價"
BADGE_LOW_MARKUP = "加價 ≤10%"


@dataclass
class Thresholds:
    lookback_days: int = 56        # 只用最近幾天抓到的價格
    min_capture_days: int = 28     # 至少累積幾天的抓價
    min_saturdays: int = 4         # 至少幾個可比較的週六
    min_weekday_nights: int = 2    # 每個月至少幾晚平日價才算得出均價
    max_premium: float = 0.10
    min_rating: float = 8.5
    min_reviews: int = 100


@dataclass
class Night:
    checkin: date
    kind: str
    price: Optional[int]   # 各次抓價的中位數；全部無房時為 None
    captures: int


@dataclass
class Result:
    hotel: Hotel
    capture_days: int
    nights: List[Night]
    weekday_avg: Optional[int] = None
    saturday_avg: Optional[int] = None
    premium: Optional[float] = None
    max_premium: Optional[float] = None
    saturdays: int = 0
    saturday_sold_out: int = 0
    special_nights: int = 0
    problems: List[str] = field(default_factory=list)
    badge: Optional[str] = None
    quality: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        """例：平日 2,800／週六 2,900／加價 3.5%，資料不足時附上原因。"""
        parts = []
        if self.premium is not None:
            word = "加價" if self.premium >= 0 else "減價"
            parts.append(f"平日 {self.weekday_avg:,}／週六 {self.saturday_avg:,}／"
                         f"{word} {abs(self.premium) * 100:.1f}%")
        if self.problems:
            parts.append("（" + "；".join(self.problems) + "）")
        return " ".join(parts)


def _nights(rows, calendar: Calendar) -> List[Night]:
    prices, captures = defaultdict(list), defaultdict(int)
    for r in rows:
        d = date.fromisoformat(r["checkin"])
        captures[d] += 1
        if r["available"]:
            prices[d].append(r["price"])
    return [
        Night(checkin=d, kind=calendar.classify(d),
              price=round(statistics.median(prices[d])) if prices[d] else None,
              captures=captures[d])
        for d in sorted(captures)
    ]


def evaluate(hotel: Hotel, rows, calendar: Calendar, t: Thresholds) -> Result:
    """rows：這間住宿／房型在回溯期間內的快照（sqlite3.Row 或 dict）。"""
    nights = _nights(rows, calendar)
    res = Result(
        hotel=hotel,
        capture_days=len({r["captured_on"] for r in rows}),
        nights=nights,
        special_nights=sum(n.kind == SPECIAL for n in nights),
    )

    weekday_by_month: Dict[str, List[int]] = defaultdict(list)
    for n in nights:
        if n.kind == WEEKDAY and n.price is not None:
            weekday_by_month[n.checkin.strftime("%Y-%m")].append(n.price)

    pairs = []  # (週六價, 同月平日均價)
    for n in nights:
        if n.kind != SATURDAY:
            continue
        if n.price is None:
            res.saturday_sold_out += 1
            continue
        month = weekday_by_month[n.checkin.strftime("%Y-%m")]
        if len(month) >= t.min_weekday_nights:
            pairs.append((n.price, statistics.mean(month)))
    res.saturdays = len(pairs)

    if res.capture_days < t.min_capture_days:
        res.problems.append(f"累積 {res.capture_days} 天，需要 {t.min_capture_days} 天")
    if res.saturdays < t.min_saturdays:
        res.problems.append(f"可比較的週六 {res.saturdays} 個，需要 {t.min_saturdays} 個")
    if not pairs:
        return res

    sat_avg = statistics.mean(p[0] for p in pairs)
    ref_avg = statistics.mean(p[1] for p in pairs)
    res.saturday_avg, res.weekday_avg = round(sat_avg), round(ref_avg)
    res.premium = sat_avg / ref_avg - 1
    res.max_premium = max(s / w - 1 for s, w in pairs)
    if not res.ok:
        return res

    # 先四捨五入到 0.1%，跟畫面上顯示的數字一致
    shown = round(res.premium * 100, 1)
    if shown <= 0:
        res.badge = BADGE_NO_MARKUP
    elif shown <= t.max_premium * 100:
        res.badge = BADGE_LOW_MARKUP
    res.quality = (
        res.badge is not None
        and hotel.rating is not None and hotel.rating >= t.min_rating
        and hotel.review_count is not None and hotel.review_count >= t.min_reviews
    )
    return res


def evaluate_all(conn, hotels: List[Hotel], calendar: Calendar, t: Thresholds,
                 today: date) -> List[Result]:
    since = (today - timedelta(days=t.lookback_days)).isoformat()
    results = []
    for h in hotels:
        rows = conn.execute(
            "SELECT captured_on, checkin, price, available FROM price_snapshots "
            "WHERE hotel_id = ? AND room_type = ? AND captured_on > ? "
            "AND captured_on <= ?",
            (h.hotel_id, h.room_type, since, today.isoformat()),
        ).fetchall()
        results.append(evaluate(h, rows, calendar, t))
    # 良心榜在前、溢價低的在前；算不出來的排最後
    results.sort(key=lambda r: (not r.quality, r.premium is None,
                                r.premium if r.premium is not None else 0))
    return results


def uncovered_checkins(results: List[Result], calendar: Calendar) -> List[date]:
    """沒有官方行事曆涵蓋的入住日（隔天也要涵蓋，才判斷得出連假）。"""
    missing = set()
    for r in results:
        for n in r.nights:
            for d in (n.checkin, n.checkin + timedelta(days=1)):
                if not calendar.covers(d):
                    missing.add(d)
    return sorted(missing)
