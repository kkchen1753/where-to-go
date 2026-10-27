import csv
import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import date
from pathlib import Path

import track
from tracker import db
from tracker.dates import tracked_checkins
from tracker.hotels import load_hotels
from tracker.manual import COL_PRICE, COL_SOLD_OUT, read_filled, write_template

HOTELS_CSV = """hotel_id,name,region,room_type,source,source_ref,url,rating,review_count,note
h1,旅館一,宜蘭,雙人房,manual,,,8.7,"1,200",
h2,旅館二,台北,雙人房,demo,,,,,
"""


class TempProject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "hotels.csv").write_text(HOTELS_CSV, encoding="utf-8")
        self.config = self.dir / "config.json"
        self.config.write_text(json.dumps({"weeks_ahead": 2}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            track.main(["--config", str(self.config), *argv])
        return out.getvalue()

    def rows(self):
        with closing(db.connect(self.dir / "data" / "prices.db")) as conn:
            return conn.execute("SELECT * FROM price_snapshots ORDER BY checkin").fetchall()


class DatesTest(unittest.TestCase):
    def test_starts_tomorrow_and_filters_nights(self):
        # 2026-10-27 是週二
        days = tracked_checkins(date(2026, 10, 27), 1, ["sat", "wed"])
        self.assertEqual(days, [date(2026, 10, 28), date(2026, 10, 31)])

    def test_rejects_unknown_night(self):
        with self.assertRaises(ValueError):
            tracked_checkins(date(2026, 10, 27), 1, ["saturday"])


class HotelsTest(TempProject):
    def test_parses_numbers(self):
        h1 = load_hotels(self.dir / "hotels.csv")[0]
        self.assertEqual((h1.rating, h1.review_count), (8.7, 1200))

    def test_rejects_duplicates(self):
        path = self.dir / "dup.csv"
        path.write_text(HOTELS_CSV + "h1,重複,宜蘭,雙人房,manual,,,,,\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重複"):
            load_hotels(path)


class ManualFlowTest(TempProject):
    def fill(self, path, values):
        """values: 依序填入每一列的 (價格, 無房)。"""
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields, rows = reader.fieldnames, list(reader)
        for row, (price, sold_out) in zip(rows, values):
            row[COL_PRICE], row[COL_SOLD_OUT] = price, sold_out
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_template_then_import(self):
        self.run_cli("template", "--date", "2026-10-27", "--nights", "wed,sat")
        sheet = self.dir / "input" / "2026-10-27.csv"
        # 只有 manual 的 h1，兩週 × 兩晚 = 4 列
        self.fill(sheet, [("2,800", ""), ("NT$ 2900", ""), ("", "v"), ("", "")])
        out = self.run_cli("import", str(sheet))
        self.assertIn("匯入 3 筆", out)
        rows = self.rows()
        self.assertEqual([r["price"] for r in rows], [2800, 2900, None])
        self.assertEqual([r["available"] for r in rows], [1, 1, 0])

    def test_bad_row_blocks_whole_import(self):
        hotels = load_hotels(self.dir / "hotels.csv")
        sheet = self.dir / "sheet.csv"
        write_template(sheet, hotels, [date(2026, 10, 28), date(2026, 10, 31)],
                       date(2026, 10, 27))
        self.fill(sheet, [("2800", ""), ("abc", "")])
        with self.assertRaisesRegex(ValueError, "整份沒有匯入"):
            read_filled(sheet, hotels)

    def test_reimport_same_day_overwrites(self):
        self.run_cli("template", "--date", "2026-10-27", "--nights", "sat")
        sheet = self.dir / "input" / "2026-10-27.csv"
        self.fill(sheet, [("3000", "")])
        self.run_cli("import", str(sheet))
        self.fill(sheet, [("3100", "")])
        self.run_cli("import", str(sheet))
        self.assertEqual([r["price"] for r in self.rows()], [3100])


class FetchTest(TempProject):
    def test_demo_fetch_and_export(self):
        self.run_cli("fetch", "--date", "2026-10-27")
        rows = self.rows()
        # 只有 demo 的 h2；兩週內的週日～週四、週六 = 12 晚
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["hotel_id"] == "h2" and r["source"] == "demo" for r in rows))
        out = self.dir / "export.csv"
        self.run_cli("export", str(out))
        with out.open(encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 12)

    def test_status_lists_hotels_without_data(self):
        out = self.run_cli("status")
        self.assertIn("尚無資料", out)


if __name__ == "__main__":
    unittest.main()
