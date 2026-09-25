import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from main import rsi_wilder, candle_end, make_signals, completed_bars

NY = ZoneInfo("America/New_York")


class StockAlarmTests(unittest.TestCase):
    def test_rsi_rising(self):
        self.assertAlmostEqual(rsi_wilder(list(range(30))), 100.0)
    def test_rsi_falling(self):
        self.assertAlmostEqual(rsi_wilder(list(range(30, 0, -1))), 0.0)
    def test_short_session_bar_ends_at_market_close(self):
        end = candle_end(datetime(2026, 9, 25, 13, 30, tzinfo=NY))
        self.assertEqual(end.hour, 16)
    def test_partial_candle_is_excluded(self):
        now = datetime(2026, 9, 25, 14, 0, tzinfo=NY)
        bars = [{"dt": datetime(2026, 9, 25, 9, 30, tzinfo=NY)},
                {"dt": datetime(2026, 9, 25, 13, 30, tzinfo=NY)}]
        self.assertEqual(len(completed_bars(bars, now)), 1)
    def test_volume_spike_alert(self):
        bars = [{"close": 10, "volume": 100} for _ in range(25)]
        bars[-1]["volume"] = 250
        alerts, _, ratio = make_signals(bars, None, 0.01, 2.0)
        self.assertAlmostEqual(ratio, 2.5)
        self.assertTrue(any("hacim" in text.lower() for text in alerts))


if __name__ == "__main__":
    unittest.main()
