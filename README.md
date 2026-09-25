# Emir Trade Alarm — 8 requested stocks, 30 major cryptos

Technical Telegram alerts using completed **4-hour** candles, never live intrabar alerts. No trades placed; not a stop-loss system.

## Stock symbols
Active: **FLNC, TSLA, LEU, RDDT, GOOGL, ALB, TTWO**. `SPCX` is listed but **disabled pending symbol clarification**: the older SPCX ETF ticker changed to SPCK in 2026, and the desired SPCX listing must be confirmed before any alert is sent for an unintended asset.

## Crypto universe
- Select the **top 30 by market cap** automatically from CoinGecko, excluding known stablecoins, wrapped, tokenized and staked assets (including gold-backed assets). Refresh at most every 6 hours.
- If CoinGecko is unavailable, retain the previous selection or use the 30-pair fallback list in `config.json`. This is a best-effort market-cap list, not a guaranteed continuously current or comprehensive index.
- Crypto symbols are queried as `SYMBOL/USD` through Twelve Data; some pairs may be unsupported by the free provider. Such errors are logged and cannot generate alerts until a supported data source exists. Where a crypto pair has no 4-hour volume data, its volume alarm is skipped while RSI, EMA and ATR still work.

## Shared signals
- RSI(14) falls through 20 or 15.
- Last completed 4-hour volume >= 2x average of previous 20 completed 4-hour volumes (only where volume is available).
- EMA 20 / EMA 50 crossover, both directions.
- ATR(14) first crosses above 1.5x its preceding 20 ATR observations' average.

Multiple signals in the same candle are combined into one Telegram message. **Support and resistance alerts remain disabled**.

## Scheduling and limitations
- GitHub runs on `:11, :26, :41, :56` UTC each hour (about 15-minute checks; GitHub may delay or miss runs).
- Each crypto batch has at most **two pairs**: all 30 selected pairs are scheduled once during each 4-hour cycle; a crypto alert can arrive up to roughly 4 hours after its candle closes. This is **not fast breakout monitoring**.
- US stock batches are staggered after 13:35 and 16:05 US Eastern on weekdays, normally completing each stock sweep within an hour after the stock bar close. Public-market holidays and delayed provider data can cause gaps.
- Average planned Twelve Data credit use is about 180 crypto requests/day plus stocks; confirm actual account quota and provider asset access on your own dashboard. Manual diagnostics consume additional credits.
- The `state.json` file persists processed candles between GitHub runs. Candle evaluations are deduplicated, but GitHub's workflow schedule is not a hard real-time guarantee.

## Setup
Configure **repository secrets** `TWELVE_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in Settings → Secrets and variables → Actions.
Enable the repository **variable** `ALERTS_ENABLED=true` to activate schedules.

To verify data access, run **Actions → 4-Hour Stock Alerts → Run workflow → diagnose**. Diagnostic is limited to the first 4 active equities to avoid spending all daily credits; inspect each symbol's `API OK` line. Use **scan** to execute one staggered live batch, checking `DATA/DELIVERY ERROR` lines for any unsupported pairs. The test mode only checks Telegram connectivity.

Do not put secrets in the repository or share them in screenshots. Use broker-native stops for time-critical orders.
