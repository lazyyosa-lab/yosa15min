"""
WindowScanner — orchestrates data fetching, indicator computation,
filter evaluation, and signal dispatch for each 15-min window.
"""

import logging
from datetime import datetime, timezone
import pytz

from config import Config
from data.binance_client import BinanceClient
from data.chainlink_client import ChainlinkClient
from data.polymarket_client import PolymarketClient
from signals.indicators import compute_indicators
from signals.filters import run_filters
from bot.telegram_bot import TelegramBot

logger = logging.getLogger("scanner")

ET = pytz.timezone("America/New_York")


class WindowScanner:

    def __init__(self):
        self.binance = BinanceClient()
        self.chainlink = ChainlinkClient()
        self.polymarket = PolymarketClient()
        self.telegram = TelegramBot()

    async def run(self):
        """Main scan cycle — called before each 15-min window."""
        now_et = datetime.now(ET)
        logger.info(f"Scan triggered at {now_et.strftime('%H:%M ET')}")

        # ── 1. Fetch candle data ────────────────────────────────────────
        df = await self.binance.get_candles(limit=Config.BINANCE_CANDLE_LIMIT)
        if df is None or df.empty:
            await self.telegram.send_error("Candle fetch", "Binance returned no data")
            return

        # ── 2. Compute indicators ───────────────────────────────────────
        indicators = compute_indicators(df)
        if indicators is None:
            await self.telegram.send_error("Indicators", "Not enough candle data")
            return

        # ── 3. Chainlink spread check ───────────────────────────────────
        chainlink_ok, chainlink_spread = self.chainlink.check_spread(
            indicators.current_price
        )

        # ── 4. Fetch Polymarket markets ─────────────────────────────────
        markets = await self.polymarket.get_btc_windows()
        if not markets:
            logger.warning("No active BTC window markets found on Polymarket")
            await self.telegram.send_error(
                "Polymarket", "No active BTC 15-min UP/DOWN markets found"
            )
            return

        logger.info(f"Evaluating {len(markets)} markets")

        # ── 5. Evaluate each market ─────────────────────────────────────
        signalled = False

        for market in markets:
            title = market["title"] or "BTC UP/DOWN"
            yes_price = market["yes_price"]
            is_priority = self._is_priority_window(title, now_et)

            filters = run_filters(
                indicators=indicators,
                yes_price=yes_price,
                chainlink_spread_ok=chainlink_ok,
                chainlink_spread=chainlink_spread,
                is_priority_window=is_priority
            )

            if filters.signal:
                logger.info(f"SIGNAL on: {title}")
                await self.telegram.send_signal(
                    market_title=title,
                    indicators=indicators,
                    filters=filters,
                    chainlink_spread=chainlink_spread
                )
                signalled = True
            else:
                logger.info(f"SKIP: {title} ({filters.filters_passed}/8, edge={filters.edge:.2%})")
                # Only send skip messages for the priority window to avoid spam
                if is_priority:
                    await self.telegram.send_skip(
                        market_title=title,
                        filters=filters,
                        is_priority=True
                    )

        if not signalled:
            logger.info("No signals this cycle")

    def _is_priority_window(self, market_title: str, now_et: datetime) -> bool:
        """
        Returns True if the market corresponds to the 9:00-9:15 AM ET window,
        OR if we are currently scanning at the 8:55 trigger (5 mins before 9:00).
        """
        # Check if we're in the 8:55 scan window
        approaching_9am = (
            now_et.hour == 8 and now_et.minute >= 50
        ) or (
            now_et.hour == Config.PRIORITY_HOUR and
            now_et.minute == Config.PRIORITY_MINUTE
        )

        # Also check market title for "9:00" or "9:15"
        title_lower = market_title.lower()
        title_is_9am = "9:00" in title_lower or "9:15" in title_lower

        return approaching_9am or title_is_9am
