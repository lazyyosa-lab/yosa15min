"""
Configuration — loaded from environment variables.
Copy .env.example to .env and fill in your values.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Binance (public API — no keys needed for candle data)
    BINANCE_BASE_URL: str = "https://api.binance.us"
    BINANCE_SYMBOL: str = "BTCUSDT"
    BINANCE_INTERVAL: str = "15m"
    BINANCE_CANDLE_LIMIT: int = 50  # enough for ATR(14) + buffer

    # Chainlink (Ethereum mainnet — public RPC)
    CHAINLINK_RPC_URL: str = os.getenv(
        "CHAINLINK_RPC_URL",
        "https://cloudflare-eth.com"  # fallback — set CHAINLINK_RPC_URL env var to Alchemy/Infura for reliability
    )
    CHAINLINK_BTC_USD_FEED: str = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"

    # Polymarket
    POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"

    # Signal thresholds
    EDGE_THRESHOLD: float = 0.12          # min model_prob - market_prob
    VOLUME_RATIO_MIN: float = 1.3         # volume vs 20-period avg
    BODY_RATIO_MIN: float = 0.6           # candle body commitment
    VWAP_BAND_PCT: float = 0.0015         # 0.15% min distance from VWAP
    CHAINLINK_SPREAD_MAX: float = 0.003   # 0.3% max Binance vs Chainlink

    # Tier thresholds (filters required out of 10)
    TIER_1_MIN_FILTERS: int = 7           # 9:00 AM ET window (relaxed — was 6/8)
    TIER_3_MIN_FILTERS: int = 9           # all other windows (strict — was 8/8)

    # Position sizing suggestion (informational only — no auto-trading)
    TIER_1_SIZE_PCT: float = 0.08         # 8% of bankroll
    TIER_3_SIZE_PCT: float = 0.06         # 6% of bankroll

    # Priority window (ET)
    PRIORITY_HOUR: int = 9
    PRIORITY_MINUTE: int = 0

    @classmethod
    def validate(cls):
        missing = []
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not cls.TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")
