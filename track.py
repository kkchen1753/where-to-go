#!/usr/bin/env python3
"""週末不加價：住宿價格追蹤工具。

    python track.py plan                 # 看今天要追蹤哪些入住日
    python track.py template             # 產生人工填價表
    python track.py import input/xxx.csv # 匯入填好的價格
    python track.py fetch                # 自動抓價（非 manual 來源）
    python track.py status               # 各住宿資料累積狀況
    python track.py export prices.csv    # 匯出全部價格
"""
from __future__ import annotations

import argparse
import sys
import time
import unicodedata
from contextlib import closing
from datetime import date
from pathlib import Path

from tracker import db
from tracker.config import load_config
from tracker.dates import tracked_checkins, weekday_label
from tracker.hotels import load_hotels
from tracker.manual import read_filled, write_template
from tracker.sources import MANUAL, get_source

ROOT = Path(__file__).resolve().parent


def _date_arg(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("日期格式要是 YYYY-MM-DD") from None


def _nights_arg(text: str):
    return [n for n in text.split(",") if n.strip()]


def cmd_plan(cfg, args):
    nights = args.nights or cfg.nights
    checkins = tracked_checkins(args.date, cfg.weeks_ahead, nights)
    print(f"抓價日 {args.date}，追蹤未來 {cfg.weeks_ahead} 週、共 {len(checkins)} 個入住日：")
    for d in checkins:
        print(f"  {d}  {weekday_label(d)}")
    hotels = load_hotels(cfg.hotels_csv)
    manual = sum(h.source == MANUAL for h in hotels)
    print(f"\n住宿清單 {len(hotels)} 筆（人工 {manual}、自動 {len(hotels) - manual}），"
          f"今天共 {len(hotels) * len(checkins)} 個價格要記錄")


def cmd_template(cfg, args):
    hotels = load_hotels(cfg.hotels_csv)
    checkins = tracked_checkins(args.date, cfg.weeks_ahead, args.nights or cfg.nights)
    out = args.output or cfg.input_dir / f"{args.date}.csv"
    if out.exists() and not args.force:
        sys.exit(f"{out} 已經存在，要覆蓋請加 --force")
    n = write_template(out, hotels, checkins, args.date)
    if n == 0:
        print("hotels.csv 裡沒有 source=manual 的住宿，沒有產生任何列")
    print(f"已產生 {out}（{n} 列）。填好「價格」或「無房」後執行：")
    print(f"  python track.py import {out}")


def cmd_import(cfg, args):
    hotels = load_hotels(cfg.hotels_csv)
    snapshots = read_filled(args.file, hotels)
    with closing(db.connect(cfg.db_path)) as conn:
        n = db.save_snapshots(conn, snapshots)
    sold_out = sum(not s.available for s in snapshots)
    print(f"匯入 {n} 筆（其中無房 {sold_out} 筆）→ {cfg.db_path}")


def cmd_fetch(cfg, args):
    hotels = [h for h in load_hotels(cfg.hotels_csv) if h.source != MANUAL]
    if args.hotel:
        hotels = [h for h in hotels if h.hotel_id in args.hotel]
    if not hotels:
        print("沒有需要自動抓價的住宿（source 都是 manual）")
        return
    sources = {h.source: get_source(h.source) for h in hotels}
    checkins = tracked_checkins(args.date, cfg.weeks_ahead, args.nights or cfg.nights)
    captured_on = args.date.isoformat()

    saved = failed = 0
    with closing(db.connect(cfg.db_path)) as conn:
        for hotel in hotels:
            source = sources[hotel.source]
            snapshots = []
            for checkin in checkins:
                try:
                    q = source.fetch(hotel, checkin)
                    snapshots.append(db.Snapshot(
                        captured_on=captured_on, hotel_id=hotel.hotel_id,
                        room_type=hotel.room_type, checkin=checkin.isoformat(),
                        price=q.price, available=q.available, source=source.name,
                        currency=q.currency, note=q.note,
                    ))
                except Exception as e:  # 單筆失敗不影響其他筆
                    failed += 1
                    print(f"  ✗ {hotel.name} {checkin}：{e}", file=sys.stderr)
                if source.uses_network:
                    time.sleep(cfg.request_delay_seconds)
            # 每間存一次，中途中斷也不會全部白抓
            saved += db.save_snapshots(conn, snapshots)
            print(f"  {hotel.name}（{hotel.room_type}）：{len(snapshots)}/{len(checkins)}")
    print(f"完成：存入 {saved} 筆，失敗 {failed} 筆 → {cfg.db_path}")
    if failed:
        sys.exit(1)


def _row(cells, widths):
    """對齊表格欄位；中文字在終端機佔兩格。"""
    def pad(text, width):
        text = str(text)
        shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
        return text + " " * max(width - shown, 1)
    return "".join(pad(c, w) for c, w in zip(cells, widths)).rstrip()


def cmd_status(cfg, args):
    hotels = {h.key: h for h in load_hotels(cfg.hotels_csv)}
    with closing(db.connect(cfg.db_path)) as conn:
        rows = {(r["hotel_id"], r["room_type"]): r for r in db.coverage(conn)}
    widths = [24, 12, 9, 11, 11, 5, 5]
    print(_row(["住宿", "房型", "累積天數", "最早", "最新", "有價", "無房"], widths))
    for key, h in hotels.items():
        r = rows.get(key)
        if r is None:
            print(_row([h.name, h.room_type, "尚無資料"], widths))
            continue
        print(_row([h.name, h.room_type, r["days_captured"], r["first_captured"],
                    r["last_captured"], r["priced"], r["sold_out"]], widths))
    orphans = set(rows) - set(hotels)
    if orphans:
        print(f"\n資料庫裡有 {len(orphans)} 筆住宿已不在 hotels.csv：")
        for hotel_id, room in sorted(orphans):
            print(f"  {hotel_id} / {room}")


def cmd_export(cfg, args):
    with closing(db.connect(cfg.db_path)) as conn:
        n = db.export_csv(conn, args.output)
    print(f"匯出 {n} 筆 → {args.output}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="週末不加價：住宿價格追蹤工具")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json",
                        help="設定檔路徑（預設 config.json，可不存在）")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_dates(p):
        p.add_argument("--date", type=_date_arg, default=date.today(),
                       help="抓價日，預設今天")
        p.add_argument("--nights", type=_nights_arg,
                       help="覆蓋設定檔，例如 wed,sat")
        return p

    with_dates(sub.add_parser("plan", help="列出要追蹤的入住日"))
    p = with_dates(sub.add_parser("template", help="產生人工填價表"))
    p.add_argument("-o", "--output", type=Path, help="輸出路徑，預設 input/<日期>.csv")
    p.add_argument("--force", action="store_true", help="覆蓋已存在的檔案")
    p = sub.add_parser("import", help="匯入填好的價格表")
    p.add_argument("file", type=Path)
    p = with_dates(sub.add_parser("fetch", help="自動抓價"))
    p.add_argument("--hotel", action="append", help="只抓指定 hotel_id，可重複")
    sub.add_parser("status", help="各住宿資料累積狀況")
    p = sub.add_parser("export", help="匯出全部價格為 CSV")
    p.add_argument("output", type=Path)

    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        {
            "plan": cmd_plan, "template": cmd_template, "import": cmd_import,
            "fetch": cmd_fetch, "status": cmd_status, "export": cmd_export,
        }[args.command](cfg, args)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f"錯誤：{e}")


if __name__ == "__main__":
    main()
