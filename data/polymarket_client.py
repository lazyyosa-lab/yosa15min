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

                # Check market is still active and not closed
                if m.get("closed") or not m.get("active", True):
                    logger.info(f"  slug {slug}: market closed/inactive")
                    return None

                liquidity = float(
                    m.get("liquidityNum") or m.get("volumeNum") or
                    m.get("volume24hr") or m.get("volume") or 0
                )

                logger.info(
                    f"  ✅ {title} | yes={yes_price:.3f} "
                    f"no={1-yes_price:.3f} liq={liquidity:.0f}"
                )

                return {
                    "id":        m.get("id") or m.get("conditionId"),
                    "title":     title,
                    "yes_price": yes_price,
                    "no_price":  round(1 - yes_price, 4),
                    "liquidity": liquidity,
                    "end_date":  m.get("endDateIso") or m.get("endDate") or "",
                    "raw":       m,
                }

        except Exception as e:
            logger.error(f"  slug {slug} failed: {e}")
            return None

    def _extract_yes_price(self, m: dict) -> Optional[float]:
        """Safely extract UP/YES price."""
        outcomes = m.get("outcomes", [])
        prices   = m.get("outcomePrices", [])

        if outcomes and prices:
            for i, outcome in enumerate(outcomes):
                if str(outcome).lower() in ["up", "yes", "higher", "above"]:
                    try:
                        p = float(prices[i])
                        if 0 < p < 1:
                            return p
                    except (IndexError, ValueError, TypeError):
                        pass

        # Fallback: first price in list
        if prices:
            try:
                p = float(prices[0])
                if 0 < p < 1:
                    return p
            except (ValueError, TypeError):
                pass

        # CLOB tokens structure
        for token in m.get("tokens", []):
            if str(token.get("outcome", "")).lower() in ["up", "yes", "higher"]:
                try:
                    p = float(token.get("price", 0))
                    if 0 < p < 1:
                        return p
                except (ValueError, TypeError):
                    pass

        return None

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
