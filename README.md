# BTC 15-Min Window Bot

Scans Polymarket UP/DOWN BTC markets across all 15-min windows.
Runs 8 technical filters before sending a signal. Priority tier for the 9:00–9:15 AM ET pre-NYSE window.

## How it works

The bot fires 5 minutes before each 15-min window boundary (at :55, :10, :25, :40).
It fetches BTC candles from Binance, runs all indicators, checks Chainlink spread,
scans Polymarket for active UP/DOWN markets, and sends a GO or SKIP to Telegram.

**Priority window (9:00–9:15 AM ET):** needs 6/8 filters + mispricing edge.
**All other windows:** needs 8/8 filters + mispricing edge (strict).

## Filters

| # | Filter | What it checks |
|---|--------|---------------|
| 1 | ATR expanded | Current ATR > 20-period ATR average |
| 2 | VWAP clear | Price > 0.15% away from VWAP |
| 3 | EMA aligned | EMA9/21 aligned + agrees with VWAP bias |
| 4 | EMA diverging | EMA gap widening (not converging) |
| 5 | MACD accelerating | Histogram growing in same direction |
| 6 | Volume confirmed | Current volume ≥ 1.3x 20-period average |
| 7 | Body committed | Candle body ratio ≥ 0.6 (no doji) |
| 8 | Chainlink spread | Binance vs Chainlink < 0.3% |
| + | Mispricing | Model prob − market prob ≥ 12% |

## Setup

```bash
git clone <your-repo>
cd btc-window-bot
pip install -r requirements.txt
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python main.py
```

## Deploy on Railway

1. Push to GitHub
2. Create new Railway project → Deploy from repo
3. Add env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CHAINLINK_RPC_URL`
4. Railway picks up `railway.toml` automatically

## Project structure

```
btc-window-bot/
├── main.py              ← entry point, scheduler
├── scanner.py           ← orchestrates full scan cycle
├── config.py            ← all settings and thresholds
├── data/
│   ├── binance_client.py    ← 15-min candles + spot price
│   ├── chainlink_client.py  ← on-chain BTC/USD price
│   └── polymarket_client.py ← UP/DOWN market scanner
├── signals/
│   ├── indicators.py        ← ATR, VWAP, EMA, MACD, Volume, Body
│   └── filters.py           ← full 8-filter checklist
└── bot/
    └── telegram_bot.py      ← signal + skip message formatter
```

## Tuning

All thresholds live in `config.py`:
- `EDGE_THRESHOLD` — min mispricing to signal (default 12%)
- `VOLUME_RATIO_MIN` — volume multiplier (default 1.3x)
- `BODY_RATIO_MIN` — candle commitment (default 0.6)
- `TIER_1_MIN_FILTERS` / `TIER_3_MIN_FILTERS` — pass thresholds per tier
- `CHAINLINK_SPREAD_MAX` — max allowed Binance/Chainlink divergence

## Notes

- Resolution is Chainlink BTC/USD, not Binance spot. The spread check is critical.
- No auto-trading. The bot is signals-only. You place trades manually.
- Suggested sizes are informational: 8% for priority window, 6% for others.
