#!/usr/bin/env python3
"""4-hour stock alerts for Twelve Data + Telegram. No trading or order execution."""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, time
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


def fetch_bars(symbol):
    key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY in GitHub Actions secrets")
    query = urlencode({
        "symbol": symbol, "interval": "4h", "outputsize": 90,
        "timezone": "America/New_York", "apikey": key,
    })
    data = request_json("https://api.twelvedata.com/time_series?" + query)
    if data.get("status") == "error" or "values" not in data:
        # Avoid echoing the API key or other request data into build logs.
        raise RuntimeError(f"Twelve Data rejected {symbol}: {data.get('code', 'no candles')}")
    candles = []
    for item in reversed(data["values"]):
        try:
            candles.append({
                "dt": datetime.fromisoformat(item["datetime"]).replace(tzinfo=NY),
                "close": float(item["close"]),
                "volume": float(item["volume"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return candles


def candle_end(dt):
    # Some 4-hour bars end early when the US regular market closes at 16:00 NY.
    return min(dt + timedelta(hours=4), datetime.combine(dt.date(), time(16), NY))


def completed_bars(bars, now):
    return [bar for bar in bars if candle_end(bar["dt"]) + timedelta(minutes=2) <= now]


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


def make_signals(bars, support, tolerance, volume_multiple):
    # All indicators use COMPLETED 4-hour candles, never unfinished bars.
    if len(bars) < 22:
        return [], None, None
    latest, previous = bars[-1], bars[-2]
    closes = [b["close"] for b in bars]
    rsi = rsi_wilder(closes)
    prior_rsi = rsi_wilder(closes[:-1])
    average_volume = statistics.mean(b["volume"] for b in bars[-21:-1])
    volume_ratio = latest["volume"] / average_volume if average_volume else 0.0
    reasons = []

    # Deep oversold gets priority if both 15 and 20 were crossed at once.
    if rsi is not None and prior_rsi is not None:
        if rsi <= 15 < prior_rsi:
            reasons.append(f"RSI 15 altına geçti: {rsi:.1f} (önceki {prior_rsi:.1f})")
        elif rsi <= 20 < prior_rsi:
            reasons.append(f"RSI 20 altına geçti: {rsi:.1f} (önceki {prior_rsi:.1f})")
    if volume_ratio >= volume_multiple:
        reasons.append(f"4s hacim son 20 mum ortalamasının {volume_ratio:.1f} katı")

    if support is not None and support > 0:
        if latest["close"] < support <= previous["close"]:
            reasons.append(f"Destek aşağı kırıldı: {support:.2f} USD")
        elif (support <= latest["close"] <= support * (1 + tolerance)
              and previous["close"] > support * (1 + tolerance)):
            reasons.append(f"Desteğe %{tolerance*100:.1f} yaklaştı: {support:.2f} USD")
    return reasons, rsi, volume_ratio


def scan():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    now = datetime.now(NY)
    # NY local clock handles US daylight-saving transitions automatically.
    if now.weekday() >= 5 or not (time(9, 30) <= now.time() <= time(16, 45)):
        print("Outside US regular-session review window. No API credits used.")
        return
    changed = False
    for symbol, setting in config["symbols"].items():
        try:
            bars = completed_bars(fetch_bars(symbol), now)
            if len(bars) < 22:
                print(f"{symbol}: not enough completed bars")
                continue
            latest = bars[-1]
            bar_id = latest["dt"].isoformat()
            if state.get(symbol) == bar_id:
                print(f"{symbol}: latest bar already evaluated")
                continue
            # Persist evaluation even if there is no signal, avoiding repeat alerts.
            state[symbol] = bar_id
            changed = True
            bar_age = now - candle_end(latest["dt"])
            if not timedelta(0) <= bar_age <= timedelta(minutes=config["max_signal_age_minutes"]):
                print(f"{symbol}: older bar recorded without alert")
                continue
            signals, rsi, volume_ratio = make_signals(
                bars, setting.get("support"), config["support_tolerance"],
                config["volume_multiplier"])
            if not signals:
                print(f"{symbol}: no signal on newly completed bar")
                continue
            when = candle_end(latest["dt"]).astimezone(IST).strftime("%d.%m.%Y %H:%M")
            message = (
                f"📊 {symbol} — 4 saatlik alarm\n"
                f"Kapanış: {latest['close']:.2f} USD\n"
                f"RSI(14): {rsi:.1f}\n"
                f"Hacim/20 mum: {volume_ratio:.1f}x\n"
                f"Bar bitişi (İstanbul): {when}\n\n"
                + "\n".join("• " + s for s in signals)
                + "\n\nOtomatik teknik uyarıdır, al/sat emri değildir."
            )
            send_message(message)
            print(f"{symbol}: {len(signals)} signals delivered")
        except Exception as exc:
            # If delivery or fetch fails, do not mark this candle as processed.
            if state.get(symbol) == locals().get("bar_id"):
                state.pop(symbol, None)
            print(f"{symbol}: ERROR: {exc}", file=sys.stderr)
    if changed:
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("State saved; workflow will commit it to prevent duplicate notifications.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["chat-id", "test", "scan"], required=True)
    mode = parser.parse_args().mode
    if mode == "chat-id":
        find_chat_id()
    elif mode == "test":
        send_message("✅ Emir Trade Alarm test mesajı. Telegram bağlantısı çalışıyor.")
        print("Telegram test message delivered")
    else:
        scan()


if __name__ == "__main__":
    main()
