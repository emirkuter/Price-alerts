"""Experimental long/short candidate evaluator; NOT connected to live Telegram scans.

Uses the existing 4-hour OHLCV indicators. Requires fresh, complete candles and
external BTC/venue liquidity checks before classifying a candidate as confirmed.
Never places trades; parameters require backtesting and paper-trading validation.
"""
import statistics

from main import atr_series, ema_series, rsi_wilder


def evaluate_trade_candidate(
    bars,
    *,
    market="crypto",
    btc_daily_trend=None,
    venue_quote_volume_24h=None,
    venue_spread_pct=None,
    short_venue_verified=False,
    candle_age_minutes=None,
    equity_usd=None,
    risk_fraction=0.005,
    volume_threshold=1.5,
    max_candle_age_minutes=45,
    minimum_quote_volume_24h=20_000_000,
    maximum_spread_pct=0.15,
    stop_atr_multiple=1.5,
    target_r_multiple=2.0,
):
    """Return a transparent directional *candidate*, never an execution command.

    `bars` must contain only COMPLETE 4-hour OHLCV candles, in chronological order.
    `btc_daily_trend` must be independently computed from closed BTC daily candles:
        "bull", "bear", or None.
    Venue values must be taken from the exchange/instrument the user can trade.
    Short venues must be independently verified for futures liquidity/access.
    """
    if market not in {"crypto", "stock"}:
        raise ValueError("market must be crypto or stock")
    if not (0 < risk_fraction <= 0.01):
        raise ValueError("risk_fraction must be between 0 and 1%")
    if stop_atr_multiple <= 0 or target_r_multiple <= 0:
        raise ValueError("stop and target factors must be positive")
    if len(bars) < 60:
        return {"status": "NO_SIGNAL", "reason": "Insufficient completed 4h candles"}

    close = [float(b["close"]) for b in bars]
    fast = ema_series(close, 20)[-1]
    slow = ema_series(close, 50)[-1]
    rsi = rsi_wilder(close, 14)
    previous_rsi = rsi_wilder(close[:-1], 14)
    atr = atr_series(bars, 14)[-1]
    current = close[-1]
    previous_volumes = [float(b.get("volume") or 0) for b in bars[-21:-1]]
    latest_volume = float(bars[-1].get("volume") or 0)
    avg_volume = statistics.mean(previous_volumes) if all(v > 0 for v in previous_volumes) else 0
    volume_ratio = latest_volume / avg_volume if avg_volume > 0 and latest_volume > 0 else None
    metrics = {
        "close": current, "ema20": fast, "ema50": slow,
        "rsi14": rsi, "previous_rsi14": previous_rsi,
        "atr14": atr, "volume_ratio": volume_ratio,
    }
    if not current > 0 or atr is None or atr <= 0 or rsi is None or previous_rsi is None:
        return {"status": "NO_SIGNAL", "reason": "Invalid price/indicator data", "metrics": metrics}
    if volume_ratio is None:
        return {"status": "DATA_INCOMPLETE", "reason": "4h volume missing; no trade signal", "metrics": metrics}
    if volume_ratio < volume_threshold:
        return {"status": "NO_SIGNAL", "reason": "Volume confirmation absent", "metrics": metrics}

    long_ok = current > fast > slow and 50 <= rsi <= 65 and rsi > previous_rsi
    short_ok = current < fast < slow and 35 <= rsi <= 50 and rsi < previous_rsi
    if not (long_ok or short_ok):
        return {"status": "NO_SIGNAL", "reason": "EMA and RSI do not align", "metrics": metrics}

    direction = "LONG" if long_ok else "SHORT"
    risk_per_unit = atr * stop_atr_multiple
    stop = current - risk_per_unit if long_ok else current + risk_per_unit
    target = (current + risk_per_unit * target_r_multiple if long_ok
              else current - risk_per_unit * target_r_multiple)
    if stop <= 0 or target <= 0:
        return {"status": "NO_SIGNAL", "reason": "Invalid ATR stop/target", "metrics": metrics}

    missing = []
    if candle_age_minutes is None or candle_age_minutes < 0 or candle_age_minutes > max_candle_age_minutes:
        missing.append("Missing or stale candle-close timestamp")
    if market == "crypto":
        required_btc = "bull" if long_ok else "bear"
        if btc_daily_trend != required_btc:
            missing.append("BTC closed-daily EMA50 market filter unconfirmed")
        if venue_quote_volume_24h is None or venue_quote_volume_24h < minimum_quote_volume_24h:
            missing.append("Venue 24h liquidity unconfirmed/insufficient")
        if venue_spread_pct is None or not 0 <= venue_spread_pct <= maximum_spread_pct:
            missing.append("Venue bid-ask spread unconfirmed/too wide")
        if direction == "SHORT" and not short_venue_verified:
            missing.append("Short venue/futures market not independently verified")

    position_units = None
    if equity_usd is not None:
        if equity_usd <= 0:
            raise ValueError("equity_usd must be positive")
        position_units = (equity_usd * risk_fraction) / risk_per_unit
    return {
        "status": "CANDIDATE" if not missing else "WATCH_ONLY",
        "direction": direction,
        "entry_reference": current,
        "stop_reference": stop,
        "target_reference": target,
        "reward_to_risk": target_r_multiple,
        "risk_fraction": risk_fraction,
        "position_units_before_costs": position_units,
        "checks_pending": missing,
        "metrics": metrics,
        "note": "Indicative at 4h close, not a live quote or trading instruction. Stops can slip.",
    }
