import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from main import rsi_wilder, candle_end, completed_bars, ema_series, atr_series, make_signals, scheduled_batch, eligible_crypto_coin, crypto_universe

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
        bars = sample_bars([10] * 89 + [12])
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

    def test_missing_crypto_volume(self):
        bars = sample_bars([10] * 90, [0] * 90)
        alerts, m = make_signals(bars)
        self.assertIsNone(m["volume_ratio"])
        self.assertAlmostEqual(m["ema_fast"], 10.0)
        self.assertFalse(any("hacim" in item.lower() for item in alerts))

    def test_crypto_utc_candle_completion(self):
        now = datetime(2026, 9, 25, 8, 10, tzinfo=timezone.utc)
        bars = [{"dt": datetime(2026, 9, 25, hour, tzinfo=timezone.utc)}
                for hour in (0, 4, 8)]
        self.assertEqual(len(completed_bars(bars, now, crypto=True)), 2)

    def test_thirty_crypto_pairs_in_sixteen_staggered_slots(self):
        cfg = {"symbols": {"FLNC": {}, "SPCX": {"enabled": False}},
               "crypto_symbols": [f"C{i}/USD" for i in range(30)]}
        seen = []
        for idx in range(16):
            now = datetime(2026, 9, 26, idx // 4, (idx % 4) * 15 + 11,
                           tzinfo=timezone.utc)
            stock, crypto = scheduled_batch(now, cfg)
            self.assertEqual(stock, [])
            seen += crypto
        self.assertEqual(len(seen), 30)
        self.assertEqual(len(set(seen)), 30)

    def test_stablecoins_and_tokenized_assets_are_ineligible(self):
        for coin in (
            {"symbol": "USD1", "name": "World Liberty Financial USD", "id": "world-liberty-financial-usd", "market_cap": 1000},
            {"symbol": "USDG", "name": "Global Dollar", "id": "global-dollar", "market_cap": 1000},
            {"symbol": "FIGR_HELOC", "name": "Figure HELOC", "id": "figure-heloc", "market_cap": 1000},
            {"symbol": "WBTC", "name": "Wrapped Bitcoin", "id": "wrapped-bitcoin", "market_cap": 1000},
        ):
            self.assertFalse(eligible_crypto_coin(coin), coin["symbol"])
        self.assertTrue(eligible_crypto_coin(
            {"symbol": "BTC", "name": "Bitcoin", "id": "bitcoin", "market_cap": 1000}))

    def test_dynamic_crypto_universe_excludes_stables_and_keeps_thirty(self):
        now = datetime(2026, 9, 25, 10, tzinfo=timezone.utc)
        entries = [
            {"symbol": "USD1", "name": "World Liberty Financial USD", "id": "world-liberty-financial-usd", "market_cap": 1000},
            {"symbol": "USDG", "name": "Global Dollar", "id": "global-dollar", "market_cap": 990},
            {"symbol": "FIGR_HELOC", "name": "Figure HELOC", "id": "figure-heloc", "market_cap": 980},
        ]
        entries += [
            {"symbol": f"C{i}", "name": f"Crypto {i}", "id": f"crypto-{i}", "market_cap": 900 - i}
            for i in range(35)
        ]
        with patch("main.request_json", return_value=entries):
            pairs = crypto_universe({}, {"crypto_symbols": ["BTC/USD"] * 30}, now)
        self.assertEqual(len(pairs), 30)
        self.assertNotIn("USD1/USD", pairs)
        self.assertNotIn("USDG/USD", pairs)
        self.assertNotIn("FIGR_HELOC/USD", pairs)

    def test_rejected_crypto_pair_is_not_reintroduced_from_cache(self):
        now = datetime(2026, 9, 25, 10, tzinfo=timezone.utc)
        state = {
            "_crypto_universe": {"pairs": ["USD1/USD", "BTC/USD", "USDG/USD", "ETH/USD"],
                                 "checked_at": now.isoformat()},
            "_unsupported_crypto": {"BTC/USD": now.isoformat()},
        }
        fallback = ["ETH/USD", "SOL/USD", "AVAX/USD"]
        with patch("main.request_json", side_effect=RuntimeError("CoinGecko unavailable")):
            pairs = crypto_universe(state, {"crypto_symbols": fallback}, now)
        self.assertEqual(pairs, ["ETH/USD", "SOL/USD", "AVAX/USD"])

    def test_support_is_disabled_by_default(self):
        bars = sample_bars([10] * 89 + [9.8])
        alerts, _ = make_signals(bars)
        self.assertFalse(any("Destek" in reason for reason in alerts))


if __name__ == "__main__":
    unittest.main()
