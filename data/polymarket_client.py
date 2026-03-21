"""
Polymarket client — scans for active BTC UP/DOWN 15-min markets
and fetches YES/NO prices from the CLOB.
"""

import logging
from typing import Optional
from datetime import datetime, timezone
import aiohttp

from config import Config

logger = logging.getLogger("polymarket")


class PolymarketClient:

    async def get_btc_windows(self) -> list[dict]:
        """
        Query Gamma API for active BTC 15-min UP/DOWN markets.
        Tries multiple tag slugs since the 15-min markets are in a specific category.
        """
        # Try these tag slugs — 15-min markets may be under a specific one
        tag_slugs = ["15-min-crypto", "crypto-15m", "15m", "15-minutes", "crypto"]

        all_markets = []
        seen_ids = set()

        for tag_slug in tag_slugs:
            url = f"{Config.POLYMARKET_GAMMA_URL}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": 100,
                "tag_slug": tag_slug,
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                markets = data if isinstance(data, list) else data.get("markets", [])
                for m in markets:
                    mid = m.get("id") or m.get("conditionId")
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        all_markets.append(m)
                logger.info(f"tag_slug={tag_slug}: got {len(markets)} markets")
            except Exception as e:
                logger.warning(f"tag_slug={tag_slug} failed: {e}")

        logger.info(f"Total unique markets fetched: {len(all_markets)}")

        # Log every market title so we can see exactly what's available
        for m in all_markets:
            t = (m.get("question") or m.get("title") or "")
            if "bitcoin" in t.lower() or "btc" in t.lower() or "up or down" in t.lower():
                logger.info(f"  BTC/UP-DOWN market: {t}")

        btc_windows = self._filter_window_markets(all_markets)
        logger.info(f"Found {len(btc_windows)} active BTC window markets")
        return btc_windows

    def _filter_window_markets(self, markets: list) -> list[dict]:
        """
        Filter to only 15-min UP/DOWN BTC markets.
        Checks title keywords and resolves UP/DOWN structure.
        """
        results = []
        keywords = ["bitcoin"]
        direction_keywords = ["up or down"]
        # Actual title: "Bitcoin Up or Down - 15 min" (lowercase min, dash separator)

        for m in markets:
            title = (m.get("question") or m.get("title") or "").lower()

            is_btc = any(k in title for k in keywords)
            is_direction = any(k in title for k in direction_keywords)
            is_15min = "15 min" in title or "15min" in title or "15-min" in title

            if not (is_btc and is_direction and is_15min):
                continue

            # Parse YES price from outcomes
            yes_price = self._extract_yes_price(m)
            if yes_price is None:
                continue

            # Filter out very low liquidity markets
            liquidity = float(m.get("volumeNum") or m.get("volume") or 0)
            if liquidity < 500:
                continue

            results.append({
                "id": m.get("id") or m.get("conditionId"),
                "title": m.get("question") or m.get("title"),
                "yes_price": yes_price,           # 0.0 - 1.0 (UP probability)
                "no_price": round(1 - yes_price, 4),
                "liquidity": liquidity,
                "end_date": m.get("endDate") or m.get("end_date_iso"),
                "raw": m
            })

        return results

    def _looks_like_window(self, title: str) -> bool:
        """Rough check that title contains a time range like 9:00-9:15."""
        import re
        return bool(re.search(r"\d{1,2}:\d{2}.*\d{1,2}:\d{2}", title))

    def _extract_yes_price(self, market: dict) -> Optional[float]:
        """
        Extract the UP (YES) price from market outcomes.
        Polymarket stores outcomes as a list with token prices.
        """
        outcomes = market.get("outcomes", [])
        prices = market.get("outcomePrices", [])

        if outcomes and prices:
            for i, outcome in enumerate(outcomes):
                if str(outcome).lower() in ["up", "yes"]:
                    try:
                        return float(prices[i])
                    except (IndexError, ValueError):
                        pass

        # Fallback: if only 2 outcomes, index 0 is typically YES/UP
        if prices and len(prices) >= 1:
            try:
                price = float(prices[0])
                if 0 < price < 1:
                    return price
            except ValueError:
                pass

        return None

    async def get_market_prices(self, market_id: str) -> Optional[dict]:
        """
        Fetch live order book prices from CLOB for a specific market.
        More accurate than Gamma for real-time YES/NO prices.
        """
        url = f"{Config.POLYMARKET_CLOB_URL}/markets/{market_id}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            logger.error(f"CLOB fetch failed for {market_id}: {e}")
            return None
