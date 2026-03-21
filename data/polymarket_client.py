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
        Fetch all active Polymarket markets and filter by title for
        'Bitcoin Up or Down' 15-min markets. Paginates to ensure full coverage.
        """
        all_markets = []
        offset = 0
        limit = 100

        try:
            async with aiohttp.ClientSession() as session:
                while True:
                    url = f"{Config.POLYMARKET_GAMMA_URL}/markets"
                    params = {
                        "active": "true",
                        "closed": "false",
                        "limit": limit,
                        "offset": offset,
                    }
                    async with session.get(
                        url, params=params, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json()

                    page = data if isinstance(data, list) else data.get("markets", [])
                    if not page:
                        break

                    all_markets.extend(page)

                    # Check if any UP/DOWN markets found yet — stop early if yes
                    found = [
                        m for m in page
                        if "up or down" in (m.get("question") or m.get("title") or "").lower()
                    ]
                    if found:
                        logger.info(f"Found UP/DOWN markets at offset {offset}")
                        break

                    # Stop after 5 pages (500 markets) to avoid hammering the API
                    if len(page) < limit or offset >= 400:
                        break

                    offset += limit

        except Exception as e:
            logger.error(f"Polymarket fetch failed: {e}")
            return []

        logger.info(f"Total markets scanned: {len(all_markets)}")

        # Log every UP/DOWN or Bitcoin market found
        for m in all_markets:
            t = (m.get("question") or m.get("title") or "")
            if "up or down" in t.lower() or ("bitcoin" in t.lower() and "15" in t.lower()):
                logger.info(f"  Candidate: {t}")

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
