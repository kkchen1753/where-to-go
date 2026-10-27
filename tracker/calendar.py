"""判斷某一晚是「一般平日」「一般週六」還是連假等特殊日子。

行事曆放在 calendar/ 資料夾，支援兩種 CSV：

1. 行政院人事行政總處「政府行政機關辦公日曆表」（data.gov.tw/dataset/14718），
   欄位：西元日期、星期、是否放假（2 放假、0 上班）、備註。直接下載放進來即可。
2. 自訂特殊日期，欄位：日期、名稱。列出的那一晚（入住日）直接視為特殊，
   用來標記旺季、在地活動等不是放假、但價格會異常的日子。

沒有官方行事曆涵蓋的日期，只能假設週六、週日放假，連假會被誤算成一般週末。
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional, Set

WEEKDAY = "weekday"   # 週日～週四入住，隔天上班
SATURDAY = "sat"      # 一般週末的週六入住
FRIDAY = "fri"        # 週五入住，不列入計算
SPECIAL = "special"   # 連假、補班、國定假日前夕、自訂特殊日期


def _parse_date(text: str) -> date:
    text = text.strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return date.fromisoformat(text)


def _read_rows(path: Path):
    for encoding in ("utf-8-sig", "cp950"):
        try:
            with path.open(encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name} 編碼無法辨識（請存成 UTF-8 或 Big5）")


class Calendar:
    def __init__(self, days_off: Optional[Dict[date, bool]] = None,
                 special: Optional[Set[date]] = None):
        self.official: Dict[date, bool] = days_off or {}
        self.special: Set[date] = special or set()

    @classmethod
    def load(cls, folder: Path) -> "Calendar":
        cal = cls()
        if not folder.exists():
            return cal
        for path in sorted(folder.glob("*.csv")):
            rows = _read_rows(path)
            if not rows:
                continue
            columns = {k.strip() for k in rows[0] if k}
            for line_no, row in enumerate(rows, start=2):
                row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                try:
                    if "是否放假" in columns:
                        cal.official[_parse_date(row["西元日期"])] = row["是否放假"] == "2"
                    elif "日期" in columns:
                        cal.special.add(_parse_date(row["日期"]))
                    else:
                        raise ValueError("看不懂的欄位，請參考 tracker/calendar.py 的說明")
                except (KeyError, ValueError) as e:
                    raise ValueError(f"{path.name} 第 {line_no} 行：{e}") from None
        return cal

    def covers(self, d: date) -> bool:
        return d in self.official

    def is_off(self, d: date) -> bool:
        if d in self.official:
            return self.official[d]
        return d.weekday() >= 5

    def _off_block(self, d: date):
        """d 所在的連續放假區間（d 必須是放假日）。"""
        start = end = d
        while self.is_off(start - timedelta(days=1)):
            start -= timedelta(days=1)
        while self.is_off(end + timedelta(days=1)):
            end += timedelta(days=1)
        return start, end

    def _is_plain_weekend(self, d: date) -> bool:
        start, end = self._off_block(d)
        return start.weekday() == 5 and end == start + timedelta(days=1)

    def classify(self, checkin: date) -> str:
        if checkin in self.special:
            return SPECIAL
        if checkin.weekday() == 4:
            return FRIDAY
        nxt = checkin + timedelta(days=1)
        # 隔天或當天是放假日、但不是單純的週六日 → 連假、補班、國定假日前夕
        for d in (nxt, checkin):
            if self.is_off(d) and not self._is_plain_weekend(d):
                return SPECIAL
        if checkin.weekday() == 5:
            return SATURDAY
        return WEEKDAY
