"""
Polymarket client — finds BTC UP/DOWN 15-min markets by expiry time.
Instead of guessing titles, we filter markets expiring within the next 30 mins.
That's the only reliable way to find short-window markets via the Gamma API.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import aiohttp

from config import Config

logger = logging.getLogger("polymarket")

BTC_KEYWORDS = ["bitcoin", "btc"]


class PolymarketClient:

    async def get_btc_windows(self) -> list[dict]:
        """
        Find active BTC UP/DOWN markets expiring in the next 30 minutes.
        Uses endDateIso to filter — no title guessing.
        Also tries slug-based direct lookup as a secondary approach.
        """
        results = []

        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=30)

        logger.info(f"Looking for markets expiring between {now.strftime('%H:%M')} and {window_end.strftime('%H:%M')} UTC")

        all_markets = []

        async with aiohttp.ClientSession() as session:

            # ── 1. Fetch from /events (nested markets) ───────────────────
            try:
                async with session.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/events",
                    params={"active": "true", "closed": "false", "limit": 100},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        events = data if isinstance(data, list) else data.get("events", [])
                        for e in events:
                            for m in e.get("markets", []):
                                all_markets.append(m)
            except Exception as ex:
                logger.warning(f"/events failed: {ex}")

            # ── 2. Fetch from /markets — multiple pages ──────────────────
            for offset in [0, 100, 200, 300]:
                try:
                    async with session.get(
                        f"{Config.POLYMARKET_GAMMA_URL}/markets",
                        params={
                            "active": "true",
                            "closed": "false",
                            "limit": 100,
                            "offset": offset,
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            page = data if isinstance(data, list) else data.get("markets", [])
                            all_markets.extend(page)
                except Exception as ex:
                    logger.warning(f"/markets offset={offset} failed: {ex}")

            # ── 3. Direct slug lookup ────────────────────────────────────
            # Try known slug patterns for Bitcoin 15-min markets
            slugs = [
                "bitcoin-up-or-down-15-min",
                "btc-up-or-down-15-min",
                "bitcoin-15-min",
                "bitcoin-up-or-down",
            ]
            for slug in slugs:
                try:
                    async with session.get(
                        f"{Config.POLYMARKET_GAMMA_URL}/markets",
                        params={"slug": slug},
                        timeout=aiohttp.ClientTimeout(total=8)
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            slug_markets = data if isinstance(data, list) else data.get("markets", [])
                            if slug_markets:
                                logger.info(f"Slug '{slug}' returned {len(slug_markets)} markets")
                                for m in slug_markets:
                                    logger.info(f"  slug hit: {m.get('question') or m.get('title')}")
                                all_markets.extend(slug_markets)
                except Exception as ex:
                    logger.warning(f"Slug {slug} failed: {ex}")

        logger.info(f"Total markets to check: {len(all_markets)}")

        # ── Deduplicate ──────────────────────────────────────────────────
        seen = set()
        unique = []
        for m in all_markets:
            mid = m.get("id") or m.get("conditionId")
            if mid and mid not in seen:
                seen.add(mid)
                unique.append(m)

        # ── Filter by expiry + BTC ───────────────────────────────────────
        for m in unique:
            title = (m.get("question") or m.get("title") or "").strip()
            title_lower = title.lower()

            # Must be BTC related
            is_btc = any(k in title_lower for k in BTC_KEYWORDS)
            if not is_btc:
                continue

            # Check expiry — must be within the next 30 mins
            end_iso = m.get("endDateIso") or m.get("endDate") or ""
            expiry = self._parse_iso(end_iso)

            if expiry is None:
                logger.info(f"BTC market no expiry date: '{title}' — skipping")
                continue

            mins_until_expiry = (expiry - now).total_seconds() / 60
            logger.info(f"BTC market: '{title}' | expires in {mins_until_expiry:.1f} mins")

            if not (0 < mins_until_expiry <= 30):
                # Log near-miss markets (expiring in 1hr) so we can tune the window
                if 0 < mins_until_expiry <= 60:
                    logger.info(f"  → expiring soon but outside 30min window ({mins_until_expiry:.1f} mins)")
                continue

            # Must be active and not closed
            if m.get("closed") or not m.get("active", True):
                logger.info(f"  → closed/inactive, skipping")
                continue

            yes_price = self._extract_yes_price(m)
            if yes_price is None:
                logger.info(f"  → could not extract price, skipping")
                continue

            liquidity = float(m.get("liquidityNum") or m.get("volumeNum") or m.get("volume") or 0)

            logger.info(f"  ✅ MATCHED — yes={yes_price:.3f} liq={liquidity:.0f}")
            results.append({
                "id":        m.get("id") or m.get("conditionId"),
                "title":     title,
                "yes_price": yes_price,
                "no_price":  round(1 - yes_price, 4),
                "liquidity": liquidity,
                "end_date":  end_iso,
                "raw":       m,
            })

        logger.info(f"Found {len(results)} active BTC window markets")
        return results

    def _parse_iso(self, iso_str: str) -> Optional[datetime]:
        """Parse ISO 8601 date string to UTC datetime."""
        if not iso_str:
            return None
        try:
            # Handle both Z and +00:00 suffixes
            s = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None

    def _extract_yes_price(self, m: dict) -> Optional[float]:
        """Safely extract UP/YES price from any Polymarket market structure."""
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

        # Fallback: first price
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
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            logger.error(f"CLOB fetch failed for {market_id}: {e}")
            return None
