"""
Binance client — fetches BTC/USDT 15-min candles.
No API key required for public market data.
"""

import logging
from typing import Optional
import aiohttp
import pandas as pd

from config import Config

logger = logging.getLogger("binance")


class BinanceClient:

    async def get_candles(self, limit: int = 50) -> Optional[pd.DataFrame]:
        """
        Fetch last `limit` 15-min candles from Binance.
        Returns a DataFrame with columns:
            open_time, open, high, low, close, volume
        """
        url = f"{Config.BINANCE_BASE_URL}/api/v3/klines"
        params = {
            "symbol": Config.BINANCE_SYMBOL,
            "interval": Config.BINANCE_INTERVAL,
            "limit": limit
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    raw = await resp.json()

            df = pd.DataFrame(raw, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])

            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)

            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()

            logger.info(f"Fetched {len(df)} candles. Last close: {df['close'].iloc[-1]:.2f}")
            return df

        except Exception as e:
            logger.error(f"Binance fetch failed: {e}")
            return None

    async def get_spot_price(self) -> Optional[float]:
        """Get current BTC/USDT spot price."""
        url = f"{Config.BINANCE_BASE_URL}/api/v3/ticker/price"
        params = {"symbol": Config.BINANCE_SYMBOL}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            return float(data["price"])
        except Exception as e:
            logger.error(f"Binance spot price failed: {e}")
            return None
