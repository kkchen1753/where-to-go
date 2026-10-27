"""讀取 config.json；沒有的欄位用預設值。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .dates import parse_nights

DEFAULT_NIGHTS = ["sun", "mon", "tue", "wed", "thu", "sat"]


@dataclass
class Config:
    base_dir: Path
    db_path: Path
    hotels_csv: Path
    input_dir: Path
    weeks_ahead: int = 8
    # 要追蹤哪幾晚的入住價。週日～週四算平日，週六是比較對象。
    nights: List[str] = field(default_factory=lambda: list(DEFAULT_NIGHTS))
    # 自動抓價時，每次請求之間等幾秒，避免對網站造成負擔。
    request_delay_seconds: float = 3.0


def load_config(path: Path) -> Config:
    base_dir = path.parent.resolve()
    raw = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)

    def resolve(key: str, default: str) -> Path:
        p = Path(raw.get(key, default))
        return p if p.is_absolute() else base_dir / p

    weeks_ahead = int(raw.get("weeks_ahead", 8))
    if weeks_ahead < 1:
        raise ValueError("config.json 的 weeks_ahead 至少要 1")
    nights = list(raw.get("nights", DEFAULT_NIGHTS))
    parse_nights(nights)  # 提早檢查拼字
    return Config(
        base_dir=base_dir,
        db_path=resolve("db_path", "data/prices.db"),
        hotels_csv=resolve("hotels_csv", "hotels.csv"),
        input_dir=resolve("input_dir", "input"),
        weeks_ahead=weeks_ahead,
        nights=nights,
        request_delay_seconds=float(raw.get("request_delay_seconds", 3.0)),
    )
