import unittest
from unittest.mock import patch
from supertrend_alerts import supertrend_series, supertrend_flip, indicators_with_supertrend


def bars(prices):
    return [{"close": float(p), "high": float(p) + 1, "low": float(p) - 1, "volume": 100} for p in prices]


class SupertrendAlertsTests(unittest.TestCase):
    def test_flat_series_does_not_spam_flips(self):
        values = bars([100] * 50)
        self.assertIsNone(supertrend_flip(values))
        self.assertEqual(supertrend_series(values)[-1][0], -1)

    def test_upward_flip_at_last_completed_bar(self):
        values = bars([100] * 49 + [110])
        self.assertIsNone(supertrend_flip(values[:-1]))
        self.assertIn("SELL -> BUY", supertrend_flip(values))

    def test_downward_flip_at_last_completed_bar(self):
        values = bars([100] * 48 + [110, 90])
        self.assertIn("BUY -> SELL", supertrend_flip(values))

    def test_old_reversal_is_not_repeated(self):
        values = bars([100] * 48 + [110, 110])
        self.assertIsNone(supertrend_flip(values))

    def test_existing_reasons_preserved(self):
        values = bars([100] * 49 + [110])
        with patch("supertrend_alerts.main_original_indicators_for", return_value=(["EMA test"], {"rsi": 58})):
            reasons, metrics = indicators_with_supertrend(values, {}, {"supertrend_period": 10, "supertrend_multiplier": 3})
        self.assertEqual(metrics["rsi"], 58)
        self.assertTrue(any("EMA test" == s for s in reasons))
        self.assertTrue(any("SELL -> BUY" in s for s in reasons))

    def test_incomplete_indicators_do_not_produce_telegram_alert(self):
        values = bars([100] * 49 + [110])
        with patch("supertrend_alerts.main_original_indicators_for", return_value=([], {})):
            reasons, metrics = indicators_with_supertrend(values, {}, {})
        self.assertEqual(reasons, [])
        self.assertEqual(metrics, {})


if __name__ == "__main__":
    unittest.main()
