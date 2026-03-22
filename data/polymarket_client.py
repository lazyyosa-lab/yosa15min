"""
Polymarket client — constructs BTC 15-min market slugs directly from timestamps.

Slug pattern: btc-updown-15m-{unix_timestamp_of_window_open}
e.g. btc-updown-15m-1774161900 = window opening at 2026-03-22 06:45:00 UTC

No searching needed — we calculate the slug, fetch it directly.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import aiohttp

from config import Config

logger = logging.getLogger("polymarket")


class PolymarketClient:

    def _next_window_timestamps(self, lookahead_windows: int = 3) -> list[int]:
        """
        Returns Unix timestamps for the next N 15-min window open times.
        Windows open at :00, :15, :30, :45 of every hour UTC.
        """
        now = datetime.now(timezone.utc)

        # Round down to current 15-min boundary
        minute = (now.minute // 15) * 15
        current_window = now.replace(minute=minute, second=0, microsecond=0)

        timestamps = []
        for i in range(lookahead_windows + 1):
            w = current_window + timedelta(minutes=15 * i)
            timestamps.append(int(w.timestamp()))

        return timestamps

    async def get_btc_windows(self) -> list[dict]:
        """
        Fetch BTC 15-min UP/DOWN markets by constructing slugs directly.
        Tries current window + next 2 windows.
        """
        results = []
        timestamps = self._next_window_timestamps(lookahead_windows=2)

        logger.info(f"Checking window timestamps: {timestamps}")

        async with aiohttp.ClientSession() as session:
            for ts in timestamps:
                slug = f"btc-updown-15m-{ts}"
                market = await self._fetch_by_slug(session, slug, ts)
                if market:
                    results.append(market)

        logger.info(f"Found {len(results)} active BTC window markets")
        return results

    async def _fetch_by_slug(
        self, session: aiohttp.ClientSession, slug: str, ts: int
    ) -> Optional[dict]:
        """Fetch a specific market by slug from the Gamma events endpoint."""

        window_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        mins_until = (window_dt - datetime.now(timezone.utc)).total_seconds() / 60
        logger.info(f"Fetching slug: {slug} (opens in {mins_until:.1f} mins)")

        try:
            async with session.get(
                f"{Config.POLYMARKET_GAMMA_URL}/events",
                params={"slug": slug},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    logger.warning(f"  slug {slug}: HTTP {r.status}")
                    return None

                data = await r.json()
                events = data if isinstance(data, list) else data.get("events", [])

                if not events:
                    logger.info(f"  slug {slug}: no event found")
                    return None

                event = events[0]
                logger.info(f"  Event found: {event.get('title')}")

                # Extract the nested market
                markets = event.get("markets", [])
                if not markets:
                    logger.warning(f"  slug {slug}: event has no nested markets")
                    return None

                m = markets[0]  # UP/DOWN is a single binary market
                title = m.get("question") or event.get("title") or slug

                yes_price = self._extract_yes_price(m)
                if yes_price is None:
                    logger.warning(f"  slug {slug}: could not extract price")
                    logger.info(f"  outcomes={m.get('outcomes')} prices={m.get('outcomePrices')}")
                    return None

                down_price = round(1 - yes_price, 4)

                # Check market is still active and not closed
                if m.get("closed") or not m.get("active", True):
                    logger.info(f"  slug {slug}: market closed/inactive")
                    return None

                liquidity = float(
                    m.get("liquidityNum") or m.get("volumeNum") or
                    m.get("volume24hr") or m.get("volume") or 0
                )

                logger.info(
                    f"  ✅ {title} | UP={yes_price:.3f} DOWN={down_price:.3f} liq={liquidity:.0f}"
                )

                return {
                    "id":         m.get("id") or m.get("conditionId"),
                    "title":      title,
                    "slug":       slug,
                    "yes_price":  yes_price,
                    "no_price":   down_price,
                    "liquidity":  liquidity,
                    "end_date":   m.get("endDateIso") or m.get("endDate") or "",
                    "raw":        m,
                }

        except Exception as e:
            logger.error(f"  slug {slug} failed: {e}")
            return None

    def _extract_yes_price(self, m: dict) -> Optional[float]:
        """
        Extract UP price by zipping outcomes to prices.
        outcomePrices comes back from Polymarket as a JSON string — parse first.
        """
        import json

        outcomes = m.get("outcomes", [])
        prices   = m.get("outcomePrices", [])

        # Parse JSON strings if needed
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = []

        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                prices = []

        # Build outcome → price map
        price_map = {}
        for outcome, price in zip(outcomes, prices):
            try:
                price_map[str(outcome).lower()] = float(price)
            except (ValueError, TypeError):
                continue

        logger.info(f"  price_map: {price_map}")

        up_price   = price_map.get("up")
        down_price = price_map.get("down")

        if up_price is None or down_price is None:
            # Fallback: yes/no structure
            up_price   = price_map.get("yes")
            down_price = price_map.get("no")

        if up_price is None:
            logger.warning(f"  Missing up price — outcomes={outcomes} prices={prices}")
            return None

        return up_price

    async def get_market_prices(self, market_id: str) -> Optional[dict]:
        """Fetch live CLOB prices for a specific market."""
        url = f"{Config.POLYMARKET_CLOB_URL}/markets/{market_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            logger.error(f"CLOB fetch failed for {market_id}: {e}")
            return None
