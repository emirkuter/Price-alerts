"""Supertrend(10, 3) closed-four-hour flip alerts, sharing main's existing scan.

Run this entry point from Actions in place of main.py; it appends Supertrend
reversal messages to the existing RSI/volume/EMA/ATR message, with no extra
market-data requests and no intrabar/repainting notifications. This is a
trend-change notice, NOT an automated long/short execution instruction.
"""
import main


def supertrend_series(bars, period=10, multiplier=3.0):
    """Return (direction, line) for each completed OHLC bar.

    Direction: 1 is BUY/uptrend, -1 is SELL/downtrend, None is warmup.
    Standard Wilder ATR and prior final-band rules; never use forming bars.
    The initial non-warmup bar initializes in SELL, so a flip requires two
    fully calculated observations (not an artificial initialization alert).
    """
    if period < 1 or multiplier <= 0:
        raise ValueError("Supertrend period and multiplier must be positive")
    if len(bars) < period + 2:
        return [(None, None)] * len(bars)
    atrs = main.atr_series(bars, period)
    results = [(None, None)] * len(bars)
    prev_upper = prev_lower = prev_close = None
    prev_dir = None
    for i, bar in enumerate(bars):
        atr = atrs[i]
        if atr is None:
            continue
        close = float(bar["close"])
        mid = (float(bar["high"]) + float(bar["low"])) / 2
        upper = mid + multiplier * atr
        lower = mid - multiplier * atr
        if prev_dir is None:
            direction = -1  # Seed, never report first calculated observation as a flip.
        else:
            # A band only resets when price closed beyond its prior value.
            upper = upper if upper < prev_upper or prev_close > prev_upper else prev_upper
            lower = lower if lower > prev_lower or prev_close < prev_lower else prev_lower
            if prev_dir == -1:
                direction = 1 if close > upper else -1
            else:
                direction = -1 if close < lower else 1
        results[i] = (direction, lower if direction == 1 else upper)
        prev_upper, prev_lower, prev_close, prev_dir = upper, lower, close, direction
    return results


def supertrend_flip(bars, *, period=10, multiplier=3.0):
    """Return only a confirmed flip on the last of the supplied completed bars."""
    values = supertrend_series(bars, period, multiplier)
    if len(values) < 2:
        return None
    before, now = values[-2], values[-1]
    if before[0] is None or now[0] is None or before[0] == now[0]:
        return None
    old = "BUY" if before[0] == 1 else "SELL"
    new = "BUY" if now[0] == 1 else "SELL"
    return f"Supertrend ({period},{multiplier:g}) {old} -> {new} | 4s KAPANIŞ | ST {now[1]:.5g}"


def indicators_with_supertrend(bars, settings, config):
    """Include Supertrend in the same already-fetched, same-candle alert."""
    reasons, metrics = main_original_indicators_for(bars, settings, config)
    if not metrics:
        return reasons, metrics
    text = supertrend_flip(
        bars,
        period=int(config.get("supertrend_period", 10)),
        multiplier=float(config.get("supertrend_multiplier", 3.0)),
    )
    if text:
        reasons.append(text)
    return reasons, metrics


main_original_indicators_for = main.indicators_for


def main_entry():
    # main.scan() supplies only completed candles; existing state.json ensures
    # at most one notice per pair and candle, including after schedule retries.
    main.indicators_for = indicators_with_supertrend
    main.main()


if __name__ == "__main__":
    main_entry()
