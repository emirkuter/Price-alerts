import unittest
from unittest.mock import patch

from trade_strategy import evaluate_trade_candidate


def bars_for(close=110, latest_volume=180, missing_volume=False):
    bars = [{"close": close, "high": close + 2, "low": close - 2,
             "volume": 0 if missing_volume else 100} for _ in range(99)]
    bars.append({"close": close, "high": close + 2, "low": close - 2,
                 "volume": 0 if missing_volume else latest_volume})
    return bars


class TradeStrategyTests(unittest.TestCase):
    def long_context(self):
        return {
            "btc_daily_trend": "bull", "venue_quote_volume_24h": 30_000_000,
            "venue_spread_pct": 0.05, "candle_age_minutes": 12,
            "equity_usd": 1000,
        }

    def short_context(self):
        return {
            "btc_daily_trend": "bear", "venue_quote_volume_24h": 30_000_000,
            "venue_spread_pct": 0.05, "candle_age_minutes": 12,
            "short_venue_verified": True,
        }

    def test_long_candidate_has_atr_stop_target_and_risk_budget(self):
        with (patch("trade_strategy.ema_series", side_effect=[([105] * 100), ([100] * 100)]),
              patch("trade_strategy.rsi_wilder", side_effect=[58, 55]),
              patch("trade_strategy.atr_series", return_value=[2] * 100)):
            result = evaluate_trade_candidate(bars_for(), **self.long_context())
        self.assertEqual(result["status"], "CANDIDATE")
        self.assertEqual(result["direction"], "LONG")
        self.assertAlmostEqual(result["stop_reference"], 107)
        self.assertAlmostEqual(result["target_reference"], 116)
        self.assertAlmostEqual(result["position_units_before_costs"], 5 / 3)

    def test_short_candidate_is_distinct(self):
        with (patch("trade_strategy.ema_series", side_effect=[[95] * 100, [100] * 100]),
              patch("trade_strategy.rsi_wilder", side_effect=[42, 45]),
              patch("trade_strategy.atr_series", return_value=[2] * 100)):
            result = evaluate_trade_candidate(bars_for(close=90), **self.short_context())
        self.assertEqual(result["status"], "CANDIDATE")
        self.assertEqual(result["direction"], "SHORT")
        self.assertAlmostEqual(result["stop_reference"], 93)
        self.assertAlmostEqual(result["target_reference"], 84)

    def test_missing_volume_never_confirms_trade(self):
        result = evaluate_trade_candidate(bars_for(missing_volume=True))
        self.assertEqual(result["status"], "DATA_INCOMPLETE")

    def test_insufficient_history(self):
        result = evaluate_trade_candidate(bars_for()[:20])
        self.assertEqual(result["status"], "NO_SIGNAL")

    def test_short_requires_verified_venue(self):
        with (patch("trade_strategy.ema_series", side_effect=[[95] * 100, [100] * 100]),
              patch("trade_strategy.rsi_wilder", side_effect=[42, 45]),
              patch("trade_strategy.atr_series", return_value=[2] * 100)):
            context = self.short_context()
            context["short_venue_verified"] = False
            result = evaluate_trade_candidate(bars_for(close=90), **context)
        self.assertEqual(result["status"], "WATCH_ONLY")
        self.assertTrue(any("Short venue" in msg for msg in result["checks_pending"]))

    def test_stale_candle_is_watch_only(self):
        with (patch("trade_strategy.ema_series", side_effect=[[105] * 100, [100] * 100]),
              patch("trade_strategy.rsi_wilder", side_effect=[58, 55]),
              patch("trade_strategy.atr_series", return_value=[2] * 100)):
            context = self.long_context()
            context["candle_age_minutes"] = 160
            result = evaluate_trade_candidate(bars_for(), **context)
        self.assertEqual(result["status"], "WATCH_ONLY")

    def test_btc_unconfirmed_is_watch_only(self):
        with (patch("trade_strategy.ema_series", side_effect=[[105] * 100, [100] * 100]),
              patch("trade_strategy.rsi_wilder", side_effect=[58, 55]),
              patch("trade_strategy.atr_series", return_value=[2] * 100)):
            context = self.long_context()
            context["btc_daily_trend"] = None
            result = evaluate_trade_candidate(bars_for(), **context)
        self.assertEqual(result["status"], "WATCH_ONLY")


if __name__ == "__main__":
    unittest.main()
