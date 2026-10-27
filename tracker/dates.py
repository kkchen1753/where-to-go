"""決定要追蹤哪些入住日。每筆價格都是「該日入住、住一晚」。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Set

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_LABELS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def parse_nights(nights: Iterable[str]) -> Set[int]:
    result = set()
    for n in nights:
        key = n.strip().lower()
        if key not in WEEKDAY_KEYS:
            raise ValueError(
                f"不認得的星期「{n}」，請用 {', '.join(WEEKDAY_KEYS)}"
            )
        result.add(WEEKDAY_KEYS.index(key))
    if not result:
        raise ValueError("至少要追蹤一個星期幾")
    return result


def tracked_checkins(today: date, weeks_ahead: int, nights: Iterable[str]) -> List[date]:
    """從明天起算 weeks_ahead 週內，符合 nights 的入住日。"""
    wanted = parse_nights(nights)
    days = (today + timedelta(days=i) for i in range(1, weeks_ahead * 7 + 1))
    return [d for d in days if d.weekday() in wanted]


def weekday_label(d: date) -> str:
    return WEEKDAY_LABELS[d.weekday()]
