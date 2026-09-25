#!/usr/bin/env python3
"""4-hour stock alerts for Twelve Data + Telegram. No trading or order execution."""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Europe/Istanbul")
STATE = Path("state.json")
CONFIG = Path("config.json")


def request_json(url, payload=None):
    headers = {"User-Agent": "EmirPriceAlerts/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        data = None
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=25) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: check the service credentials/limits") from None
    except URLError:
        raise RuntimeError("Network error; retry next scheduled run") from None


def telegram_url(method):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in GitHub Actions secrets")
    return f"https://api.telegram.org/bot{token}/{method}"


def find_chat_id():
    # Send /start or any new message to the bot first.
    result = request_json(telegram_url("getUpdates") + "?limit=20")
    updates = result.get("result", [])
    ids = {}
    for update in updates:
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            ids[str(chat["id"])] = chat.get("title") or chat.get("first_name") or "Telegram chat"
    if not ids:
        print("No chat found. Open your bot, press Start, send /start and rerun 'chat-id'.")
        return
    for chat_id, label in ids.items():
        print(f"TELEGRAM_CHAT_ID: {chat_id} ({label})")
    print("Copy ONLY your chat ID into the TELEGRAM_CHAT_ID Actions secret.")


def send_message(message):
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID in GitHub Actions secrets")
    result = request_json(
        telegram_url("sendMessage"),
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
    )
    if not result.get("ok"):
        raise RuntimeError("Telegram send failed")


def fetch_bars(symbol, crypto=False):
    key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY in GitHub Actions secrets")
    query = urlencode({
        "symbol": symbol, "interval": "4h", "outputsize": 180,
        "timezone": "UTC" if crypto else "America/New_York", "apikey": key,
    })
    data = request_json("https://api.twelvedata.com/time_series?" + query)
    if data.get("status") == "error" or "values" not in data:
        # Avoid echoing the API key or other request data into build logs.
        raise RuntimeError(f"Twelve Data rejected {symbol}: {data.get('code', 'no candles')}")
    candles = []
    for item in reversed(data["values"]):
        try:
            candles.append({
                "dt": datetime.fromisoformat(item["datetime"]).replace(tzinfo=timezone.utc if crypto else NY),
                "close": float(item["close"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "volume": float(item.get("volume") or 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return candles


def candle_end(dt):
    # Some 4-hour bars end early when the US regular market closes at 16:00 NY.
    return min(dt + timedelta(hours=4), datetime.combine(dt.date(), time(16), NY))


def completed_bars(bars, now, crypto=False):
    return [bar for bar in bars if (bar["dt"] + timedelta(hours=4) if crypto else candle_end(bar["dt"])) + timedelta(minutes=2) <= now]


def rsi_wilder(closes, period=14):
    if len(closes) <= period:
        return None
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def ema_series(closes, period):
    """Exponential moving average, initialized from the first period's SMA."""
    values = [None] * len(closes)
    if len(closes) < period:
        return values
    previous = sum(closes[:period]) / period
    values[period - 1] = previous
    factor = 2.0 / (period + 1)
    for idx in range(period, len(closes)):
        previous = closes[idx] * factor + previous * (1 - factor)
        values[idx] = previous
    return values


def atr_series(bars, period=14):
    """Wilder's ATR. True range uses high, low and PREVIOUS close."""
    values = [None] * len(bars)
    if len(bars) <= period:
        return values
    true_ranges = []
    for idx in range(1, len(bars)):
        bar = bars[idx]
        prev_close = bars[idx - 1]["close"]
        true_ranges.append(max(
            bar["high"] - bar["low"],
            abs(bar["high"] - prev_close),
            abs(bar["low"] - prev_close),
        ))
    previous = sum(true_ranges[:period]) / period
    values[period] = previous
    for idx in range(period + 1, len(bars)):
        previous = (previous * (period - 1) + true_ranges[idx - 1]) / period
        values[idx] = previous
    return values


def make_signals(
    bars, support=None, tolerance=0.01, volume_multiple=2.0,
    atr_multiple=1.5, ema_fast_period=20, ema_slow_period=50,
    atr_period=14, atr_window=20,
):
    """All calculations use completed four-hour candles. One combined alert/bar."""
    minimum = max(22, ema_slow_period + 1, atr_period + atr_window + 2)
    if len(bars) < minimum:
        return [], {}
    latest, previous = bars[-1], bars[-2]
    closes = [b["close"] for b in bars]
    rsi = rsi_wilder(closes)
    prior_rsi = rsi_wilder(closes[:-1])
    average_volume = statistics.mean(b["volume"] for b in bars[-21:-1])
    volume_ratio = latest["volume"] / average_volume if average_volume else None

    ema_fast = ema_series(closes, ema_fast_period)
    ema_slow = ema_series(closes, ema_slow_period)
    atr = atr_series(bars, atr_period)
    # Compare the current ATR with the PRIOR 20 ATR values (exclude current).
    atr_baseline = statistics.mean(atr[-(atr_window + 1):-1])
    previous_atr_baseline = statistics.mean(atr[-(atr_window + 2):-2])
    atr_ratio = atr[-1] / atr_baseline if atr_baseline > 0 else 0.0
    previous_atr_ratio = (
        atr[-2] / previous_atr_baseline if previous_atr_baseline > 0 else 0.0
    )
    reasons = []

    if rsi is not None and prior_rsi is not None:
        if rsi <= 15 < prior_rsi:
            reasons.append(f"RSI 15 altına geçti: {rsi:.1f} (önceki {prior_rsi:.1f})")
        elif rsi <= 20 < prior_rsi:
            reasons.append(f"RSI 20 altına geçti: {rsi:.1f} (önceki {prior_rsi:.1f})")
    if volume_ratio is not None and volume_ratio >= volume_multiple:
        reasons.append(f"4s hacim, önceki 20 mum ortalamasının {volume_ratio:.1f} katı")

    if ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
        reasons.append(f"EMA {ema_fast_period}, EMA {ema_slow_period}'yi YUKARI kesti")
    elif ema_fast[-2] >= ema_slow[-2] and ema_fast[-1] < ema_slow[-1]:
        reasons.append(f"EMA {ema_fast_period}, EMA {ema_slow_period}'yi AŞAĞI kesti")

    # Alert on the first ATR threshold crossing, rather than every volatile bar.
    if atr_ratio >= atr_multiple and previous_atr_ratio < atr_multiple:
        reasons.append(
            f"ATR({atr_period}) yükseldi: önceki {atr_window} ATR ortalamasının "
            f"{atr_ratio:.2f} katı"
        )

    # Support/resistance is intentionally disabled until levels are configured.
    if support is not None and support > 0:
        if latest["close"] < support <= previous["close"]:
            reasons.append(f"Destek aşağı kırıldı: {support:.2f} USD")
        elif (support <= latest["close"] <= support * (1 + tolerance)
              and previous["close"] > support * (1 + tolerance)):
            reasons.append(f"Desteğe %{tolerance*100:.1f} yaklaştı: {support:.2f} USD")

    indicators = {
        "rsi": rsi, "volume_ratio": volume_ratio,
        "ema_fast": ema_fast[-1], "ema_slow": ema_slow[-1],
        "atr": atr[-1], "atr_ratio": atr_ratio,
    }
    return reasons, indicators


STABLE_IDS = {
    "tether", "usd-coin", "dai", "ethena-usde", "first-digital-usd",
    "paypal-usd", "usdd", "true-usd", "frax", "usds", "pax-dollar",
    "binance-usd", "usde", "tether-gold", "pax-gold",
}
STABLE_SYMBOLS = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "PYUSD",
                  "USDD", "TUSD", "FRAX", "USDS", "BUSD", "PAXG", "XAUT"}


def crypto_universe(state, config, now):
    """Refresh top-30 non-stable, non-wrapped assets at most every 6 hours."""
    previous = state.get("_crypto_universe", {})
    last = previous.get("checked_at")
    if last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(hours=6):
                return previous.get("pairs") or config["crypto_symbols"]
        except ValueError:
            pass
    pairs = previous.get("pairs") or config["crypto_symbols"]
    try:
        params = urlencode({"vs_currency": "usd", "order": "market_cap_desc",
                            "per_page": 100, "page": 1, "sparkline": "false"})
        entries = request_json("https://api.coingecko.com/api/v3/coins/markets?" + params)
        selected = []
        seen = set()
        for coin in entries:
            symbol = str(coin.get("symbol", "")).upper()
            name = str(coin.get("name", "")).lower()
            coin_id = str(coin.get("id", "")).lower()
            if (not symbol or symbol in seen or coin_id in STABLE_IDS
                    or symbol in STABLE_SYMBOLS
                    or any(x in name for x in ("wrapped", "bridged", "staked", "tokenized", "synthetic", "liquid staking"))
                    or not coin.get("market_cap")):
                continue
            selected.append(symbol + "/USD")
            seen.add(symbol)
            if len(selected) == 30:
                break
        if len(selected) == 30:
            pairs = selected
            print("CoinGecko top-30 universe refreshed.")
        else:
            print("Incomplete CoinGecko list, using last known 30 pairs.")
    except Exception as exc:
        print(f"CoinGecko unavailable; using cached/fallback list: {type(exc).__name__}")
    state["_crypto_universe"] = {"pairs": pairs, "checked_at": now.isoformat()}
    return pairs


def scheduled_batch(now, config):
    """16 UTC slots per 4h, two crypto pairs per slot; US stock close sweeps."""
    utc = now.astimezone(timezone.utc)
    slot = (utc.hour % 4) * 4 + utc.minute // 15
    cryptos = config["crypto_symbols"][slot * 2:slot * 2 + 2]
    ny = now.astimezone(NY)
    stocks = []
    if ny.weekday() < 5:
        for hour, minute in ((13, 35), (16, 5)):
            begin = datetime.combine(ny.date(), time(hour, minute), NY)
            if begin <= ny < begin + timedelta(hours=1):
                offset = int((ny - begin).total_seconds() // 900)
                names = [n for n, v in config["symbols"].items() if v.get("enabled", True)]
                stocks = names[offset * 2:offset * 2 + 2]
                break
    return stocks, cryptos


def indicators_for(bars, settings, config):
    return make_signals(
        bars, support=settings.get("support"),
        tolerance=config["support_tolerance"],
        volume_multiple=config["volume_multiplier"],
        atr_multiple=config["atr_spike_multiple"],
        ema_fast_period=config["ema_fast_period"],
        ema_slow_period=config["ema_slow_period"],
        atr_period=config["atr_period"],
        atr_window=config["atr_baseline_bars"],
    )


def scan():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    now = datetime.now(timezone.utc)
    pairs = crypto_universe(state, config, now)
    config["crypto_symbols"] = pairs
    stocks, cryptos = scheduled_batch(now, config)
    targets = [(symbol, False) for symbol in stocks]
    targets += [(symbol, True) for symbol in cryptos]
    print(f"Batch: {len(stocks)} stocks + {len(cryptos)} crypto pairs.")
    changed = "_crypto_universe" in state
    for symbol, crypto in targets:
        try:
            bars = completed_bars(fetch_bars(symbol, crypto=crypto), now, crypto=crypto)
            minimum = max(22, config["ema_slow_period"] + 1,
                          config["atr_period"] + config["atr_baseline_bars"] + 2)
            if len(bars) < minimum:
                print(f"{symbol}: insufficient completed candles ({len(bars)})")
                continue
            latest = bars[-1]
            bar_id = latest["dt"].isoformat()
            if state.get(symbol) == bar_id:
                print(f"{symbol}: latest candle already processed")
                continue
            end = latest["dt"] + timedelta(hours=4) if crypto else candle_end(latest["dt"])
            age = now - end
            limit = config["max_crypto_signal_age_minutes"] if crypto else config["max_stock_signal_age_minutes"]
            if not timedelta(0) <= age <= timedelta(minutes=limit):
                state[symbol] = bar_id
                changed = True
                print(f"{symbol}: historical candle initialized silently")
                continue
            signals, m = indicators_for(bars, {} if crypto else config["symbols"][symbol], config)
            if not m:
                print(f"{symbol}: missing indicator history")
                continue
            if signals:
                category = "Kripto" if crypto else "Hisse"
                volume = f"{m['volume_ratio']:.2f}x" if m["volume_ratio"] is not None else "veri yok"
                when = end.astimezone(IST).strftime("%d.%m.%Y %H:%M")
                lines = [
                    f"{category}: {symbol} | 4 saatlik",
                    f"Kapanış: {latest['close']:.5g} USD",
                    f"RSI14: {m['rsi']:.1f}",
                    f"Hacim/20: {volume}",
                    f"EMA20/50: {m['ema_fast']:.5g}/{m['ema_slow']:.5g}",
                    f"ATR14: {m['atr']:.5g} (oran {m['atr_ratio']:.2f}x)",
                    f"Mum bitişi (İstanbul): {when}",
                ]
                send_message("\n".join(lines + [""] + ["• " + v for v in signals]
                                       + ["", "Otomatik teknik uyarıdır, işlem emri değildir."]))
                print(f"{symbol}: sent {len(signals)} signals")
            else:
                print(f"{symbol}: no signals")
            state[symbol] = bar_id
            changed = True
        except Exception as exc:
            print(f"{symbol}: DATA/DELIVERY ERROR: {exc}", file=sys.stderr)
    if changed:
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("State updated.")



def diagnose():
    """Read live API history and show all four indicators; never sends or changes state."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = datetime.now(NY)
    failures = []
    # Validate newly added stock symbols; original FLNC/TSLA/LEU were checked earlier.
    for symbol, settings in list(cfg["symbols"].items())[3:]:
        try:
            bars = completed_bars(fetch_bars(symbol), now)
            reasons, values = make_signals(
                bars,
                support=settings.get("support"),
                tolerance=cfg["support_tolerance"],
                volume_multiple=cfg["volume_multiplier"],
                atr_multiple=cfg["atr_spike_multiple"],
                ema_fast_period=cfg["ema_fast_period"],
                ema_slow_period=cfg["ema_slow_period"],
                atr_period=cfg["atr_period"],
                atr_window=cfg["atr_baseline_bars"],
            )
            if not values:
                raise RuntimeError(
                    f"Only {len(bars)} completed bars; indicator history is insufficient"
                )
            latest = bars[-1]
            print(
                f"{symbol}: API OK, {len(bars)} completed 4-hour bars, "
                f"last candle {latest['dt'].isoformat()}, "
                f"close {latest['close']:.2f}, RSI {values['rsi']:.1f}, "
                f"volume {values['volume_ratio'] if values['volume_ratio'] is not None else 'N/A'}, "
                f"EMA20/50 {values['ema_fast']:.2f}/{values['ema_slow']:.2f}, "
                f"ATR14 {values['atr']:.2f}, ATR ratio {values['atr_ratio']:.2f}x, "
                f"historical candle signals {len(reasons)}"
            )
        except Exception as exc:
            failures.append(symbol)
            print(f"{symbol}: DIAGNOSTIC ERROR: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(
            f"Data diagnostic failed for: {', '.join(failures)}. "
            "Check symbol access, Twelve Data quota, timezone or API settings."
        )
    print("Data diagnostic completed successfully; no Telegram alerts sent.")


def diagnose_crypto():
    """Check only first two crypto pairs to conserve free API credits."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    failures = []
    for pair in cfg["crypto_symbols"][:2]:
        try:
            bars = completed_bars(fetch_bars(pair, crypto=True), now, crypto=True)
            _, values = indicators_for(bars, {}, cfg)
            if not values:
                raise RuntimeError(f"insufficient completed candles: {len(bars)}")
            volume = "unavailable" if values["volume_ratio"] is None else f'{values["volume_ratio"]:.2f}x'
            print(
                f"{pair}: CRYPTO API OK, candles {len(bars)}, "
                f"RSI {values['rsi']:.1f}, volume {volume}, "
                f"EMA20/50 {values['ema_fast']:.5g}/{values['ema_slow']:.5g}, "
                f"ATR ratio {values['atr_ratio']:.2f}x"
            )
        except Exception as exc:
            failures.append(pair)
            print(f"{pair}: CRYPTO DIAGNOSTIC ERROR: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError("Crypto provider did not validate: " + ", ".join(failures))
    print("Crypto API diagnostic completed; no Telegram alerts sent.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["chat-id", "test", "scan", "diagnose", "diagnose-crypto"], required=True)
    mode = parser.parse_args().mode
    if mode == "chat-id":
        find_chat_id()
    elif mode == "test":
        send_message("✅ Emir Trade Alarm test mesajı. Telegram bağlantısı çalışıyor.")
        print("Telegram test message delivered")
    elif mode == "diagnose":
        diagnose()
    elif mode == "diagnose-crypto":
        diagnose_crypto()
    else:
        scan()


if __name__ == "__main__":
    main()
