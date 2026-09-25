import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from main import rsi_wilder, candle_end, completed_bars, ema_series, atr_series, make_signals

NY = ZoneInfo("America/New_York")


def sample_bars(closes, volumes=None):
    if volumes is None:
        volumes = [100] * len(closes)
    return [
        {"close": float(close), "high": float(close) + 1,
         "low": float(close) - 1, "volume": float(volume)}
        for close, volume in zip(closes, volumes)
    ]


class StockAlarmTests(unittest.TestCase):
    def test_rsi_rising(self):
        self.assertAlmostEqual(rsi_wilder(list(range(30))), 100.0)

    def test_rsi_falling(self):
        self.assertAlmostEqual(rsi_wilder(list(range(30, 0, -1))), 0.0)

    def test_ema_seed_and_constant(self):
        result = ema_series([10] * 90, 20)
        self.assertIsNone(result[18])
        self.assertAlmostEqual(result[-1], 10.0)

    def test_atr_constant_candles(self):
        bars = sample_bars([10] * 90)
        result = atr_series(bars)
        self.assertIsNone(result[13])
        self.assertAlmostEqual(result[-1], 2.0)

    def test_short_session_bar_ends_at_market_close(self):
        end = candle_end(datetime(2026, 9, 25, 13, 30, tzinfo=NY))
        self.assertEqual(end.hour, 16)

    def test_partial_candle_is_excluded(self):
        now = datetime(2026, 9, 25, 14, 0, tzinfo=NY)
        bars = [{"dt": datetime(2026, 9, 25, 9, 30, tzinfo=NY)},
                {"dt": datetime(2026, 9, 25, 13, 30, tzinfo=NY)}]
        self.assertEqual(len(completed_bars(bars, now)), 1)

    def test_volume_spike_alert(self):
        bars = sample_bars([10] * 90, [100] * 89 + [250])
        alerts, metrics = make_signals(bars)
        self.assertAlmostEqual(metrics["volume_ratio"], 2.5)
        self.assertTrue(any("hacim" in reason.lower() for reason in alerts))

    def test_no_duplicate_ema_signal_on_flat_series(self):
        bars = sample_bars([10] * 90)
        alerts, metrics = make_signals(bars)
        self.assertFalse(any("EMA" in reason for reason in alerts))
        self.assertAlmostEqual(metrics["atr_ratio"], 1.0)

    def test_ema_bullish_crossover(self):
        bars = sample_bars([10] * 80 + [10.05, 10.1, 10.2, 10.5, 12])
        alerts, metrics = make_signals(bars)
        self.assertGreater(metrics["ema_fast"], metrics["ema_slow"])
        self.assertTrue(any("YUKARI" in reason for reason in alerts))

    def test_atr_spike_crossing(self):
        bars = sample_bars([10] * 89 + [10])
        bars[-1]["high"] = 18
        bars[-1]["low"] = 2
        alerts, metrics = make_signals(bars)
        self.assertGreaterEqual(metrics["atr_ratio"], 1.5)
        self.assertTrue(any("ATR" in reason for reason in alerts))

    def test_support_is_disabled_by_default(self):
        bars = sample_bars([10] * 89 + [9.8])
        alerts, _ = make_signals(bars)
        self.assertFalse(any("Destek" in reason for reason in alerts))


if __name__ == "__main__":
    unittest.main()
