import json
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from tests.test_tracker import TempProject
from tracker import db
from tracker.calendar import FRIDAY, SATURDAY, SPECIAL, WEEKDAY, Calendar
from tracker.hotels import Hotel
from tracker.premium import BADGE_LOW_MARKUP, BADGE_NO_MARKUP, Thresholds, evaluate

def official_csv():
    """2026/10～11 的假行事曆：10/9（五）～10/11（日）三天連假，10/24（六）補班。"""
    lines = ["西元日期,星期,是否放假,備註"]
    for i in range(61):
        d = date(2026, 10, 1) + timedelta(days=i)
        off = d.weekday() >= 5 or d == date(2026, 10, 9)
        if d == date(2026, 10, 24):
            off = False
        lines.append(f"{d:%Y%m%d},,{'2' if off else '0'},")
    return "\n".join(lines)


class CalendarTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # 官方檔案常是 Big5
        (self.dir / "2026.csv").write_bytes(official_csv().encode("cp950"))
        (self.dir / "special.csv").write_text("日期,名稱\n2026-11-04,金山在地活動\n",
                                              encoding="utf-8")
        self.cal = Calendar.load(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def kind(self, m, d):
        return self.cal.classify(date(2026, m, d))

    def test_plain_week(self):
        self.assertEqual(self.kind(10, 15), WEEKDAY)  # 週四
        self.assertEqual(self.kind(10, 16), FRIDAY)
        self.assertEqual(self.kind(10, 17), SATURDAY)
        self.assertEqual(self.kind(10, 18), WEEKDAY)  # 一般週日晚上

    def test_long_weekend_and_eve(self):
        self.assertEqual(self.kind(10, 8), SPECIAL)   # 連假前夕（週四）
        self.assertEqual(self.kind(10, 10), SPECIAL)  # 連假中的週六
        self.assertEqual(self.kind(10, 11), SPECIAL)  # 連假最後一晚

    def test_makeup_workday_saturday(self):
        self.assertEqual(self.kind(10, 24), SPECIAL)

    def test_custom_special_date(self):
        self.assertEqual(self.kind(11, 4), SPECIAL)

    def test_coverage(self):
        self.assertTrue(self.cal.covers(date(2026, 10, 1)))
        self.assertFalse(self.cal.covers(date(2027, 1, 1)))


def make_rows(weekday_price, saturday_price, start=date(2026, 11, 1), weeks=4,
              capture_days=28, overrides=None):
    """在一般月份（無行事曆＝只看週末）產生快照。overrides: {(captured_on 序號, checkin): price}"""
    overrides = overrides or {}
    rows = []
    for c in range(capture_days):
        captured = (date(2026, 10, 1) + timedelta(days=c)).isoformat()
        for i in range(weeks * 7):
            d = start + timedelta(days=i)
            if d.weekday() == 4:
                continue
            price = saturday_price if d.weekday() == 5 else weekday_price
            price = overrides.get((c, d), price)
            rows.append({"captured_on": captured, "checkin": d.isoformat(),
                         "price": price, "available": price is not None})
    return rows


HOTEL = Hotel(hotel_id="h", name="測試", room_type="雙人房", source="manual",
              rating=8.8, review_count=300)


class PremiumTest(unittest.TestCase):
    def test_low_markup_badge_and_summary(self):
        r = evaluate(HOTEL, make_rows(2800, 2900), Calendar(), Thresholds())
        self.assertEqual(r.summary(), "平日 2,800／週六 2,900／加價 3.6%")
        self.assertEqual(r.badge, BADGE_LOW_MARKUP)
        self.assertTrue(r.quality)

    def test_cheaper_on_weekend(self):
        r = evaluate(HOTEL, make_rows(3000, 2700), Calendar(), Thresholds())
        self.assertEqual(r.badge, BADGE_NO_MARKUP)
        self.assertIn("減價 10.0%", r.summary())

    def test_over_threshold(self):
        r = evaluate(HOTEL, make_rows(2000, 2400), Calendar(), Thresholds())
        self.assertIsNone(r.badge)
        self.assertFalse(r.quality)

    def test_one_day_flash_sale_ignored(self):
        sat = date(2026, 11, 7)
        rows = make_rows(2800, 3500, overrides={(0, sat): 1000, (1, sat): 1000})
        r = evaluate(HOTEL, rows, Calendar(), Thresholds())
        self.assertEqual(r.saturday_avg, 3500)

    def test_needs_enough_capture_days(self):
        r = evaluate(HOTEL, make_rows(2800, 2800, capture_days=10), Calendar(), Thresholds())
        self.assertFalse(r.ok)
        self.assertIsNone(r.badge)
        self.assertIn("累積 10 天", r.summary())

    def test_sold_out_saturdays_not_compared(self):
        sats = [date(2026, 11, 7), date(2026, 11, 14)]
        overrides = {(c, d): None for c in range(28) for d in sats}
        r = evaluate(HOTEL, make_rows(2800, 2800, overrides=overrides),
                     Calendar(), Thresholds())
        self.assertEqual((r.saturdays, r.saturday_sold_out), (2, 2))
        self.assertFalse(r.ok)  # 少於 4 個週六

    def test_missing_rating_is_not_quality(self):
        hotel = Hotel(hotel_id="h", name="測試", room_type="雙人房", source="manual")
        r = evaluate(hotel, make_rows(2800, 2800), Calendar(), Thresholds())
        self.assertEqual(r.badge, BADGE_NO_MARKUP)
        self.assertFalse(r.quality)


class RankCliTest(TempProject):
    def test_json_only_contains_ranked_hotels(self):
        with closing(db.connect(self.dir / "data" / "prices.db")) as conn:
            for hotel_id, sat in (("h1", 2900), ("h2", 4000)):
                db.save_snapshots(conn, [
                    db.Snapshot(captured_on=r["captured_on"], hotel_id=hotel_id,
                                room_type="雙人房", checkin=r["checkin"],
                                price=r["price"] if r["price"] != 2900 else sat,
                                available=True, source="manual")
                    for r in make_rows(2800, 2900)
                ])
        out = self.dir / "rank.json"
        text = self.run_cli("rank", "--date", "2026-10-28", "--all", "--json", str(out))
        self.assertIn("旅館一（雙人房）[加價 ≤10%]", text)
        self.assertIn("內部檢視", text)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([h["hotel_id"] for h in data["hotels"]], ["h1"])


if __name__ == "__main__":
    unittest.main()
