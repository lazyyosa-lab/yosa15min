"""
Polymarket client — robustly finds BTC short-term UP/DOWN markets.
Uses flexible matching, full debug logging, and safe field access.
"""

import logging
import re
from typing import Optional
import aiohttp

from config import Config

logger = logging.getLogger("polymarket")

# Flexible keyword sets — any match is enough
BTC_KEYWORDS   = ["bitcoin", "btc"]
UP_DOWN_KEYS   = ["up or down", "up/down", "higher or lower", "above or below", "bull or bear"]
SHORT_EXPIRY   = ["15m", "15 m", "15min", "15 min", "15-min", "15 minute",
                  "5m", "5 min", "5min", "1h", "1 hour", "30m", "30 min",
                  "hourly", "intraday"]


class PolymarketClient:

    async def get_btc_windows(self) -> list[dict]:
        """
        Fetch BTC UP/DOWN short-term markets from Polymarket.
        Tries /events and /markets endpoints, logs everything.
        """
        raw = []

        async with aiohttp.ClientSession() as session:

            # ── 1. Events endpoint ───────────────────────────────────────
            try:
                async with session.get(
                    f"{Config.POLYMARKET_GAMMA_URL}/events",
                    params={"active": "true", "closed": "false", "limit": 100},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        events = data if isinstance(data, list) else data.get("events", [])
                        logger.info(f"/events returned {len(events)} items")
                        for e in events:
                            # events may contain nested markets
                            for m in e.get("markets", []):
                                raw.append(("events/nested", m))
                            # or the event itself may be a market
                            if e.get("outcomes") or e.get("outcomePrices"):
                                raw.append(("events/direct", e))
                    else:
                        logger.warning(f"/events returned HTTP {r.status}")
            except Exception as ex:
                logger.warning(f"/events failed: {ex}")

            # ── 2. Markets endpoint — paginate 3 pages ───────────────────
            for offset in [0, 100, 200]:
                try:
                    async with session.get(
                        f"{Config.POLYMARKET_GAMMA_URL}/markets",
                        params={"active": "true", "closed": "false",
                                "limit": 100, "offset": offset},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            page = data if isinstance(data, list) else data.get("markets", [])
                            logger.info(f"/markets offset={offset} returned {len(page)} items")
                            for m in page:
                                raw.append((f"markets/offset{offset}", m))
                        else:
                            logger.warning(f"/markets offset={offset} returned HTTP {r.status}")
                except Exception as ex:
                    logger.warning(f"/markets offset={offset} failed: {ex}")

        logger.info(f"Total raw items collected: {len(raw)}")

        # ── 3. Filter with full debug logging ───────────────────────────
        results = []
        seen = set()

        for source, m in raw:
            mid = m.get("id") or m.get("conditionId") or m.get("marketId") or id(m)
            if mid in seen:
                continue
            seen.add(mid)

            title = (
                m.get("question") or m.get("title") or
                m.get("name") or m.get("description") or ""
            ).strip()
            title_lower = title.lower()

            # ── check BTC ────────────────────────────────────────────────
            is_btc = any(k in title_lower for k in BTC_KEYWORDS)
            if not is_btc:
                continue  # silent skip — too noisy to log every non-BTC market

            # ── log every BTC market from here on ────────────────────────
            logger.info(f"[{source}] BTC market: '{title}'")
            logger.info(f"  fields: {list(m.keys())}")

            # ── check UP/DOWN ────────────────────────────────────────────
            is_updown = any(k in title_lower for k in UP_DOWN_KEYS)
            if not is_updown:
                logger.info(f"  ✗ SKIP — no up/down keyword in title")
                continue

            # ── check short expiry ───────────────────────────────────────
            is_short = any(k in title_lower for k in SHORT_EXPIRY)
            if not is_short:
                logger.info(f"  ✗ SKIP — no short-expiry keyword in title")
                continue

            # ── check not closed/resolved ────────────────────────────────
            closed   = m.get("closed") or m.get("resolved") or m.get("isResolved") or False
            end_date = m.get("endDate") or m.get("end_date_iso") or m.get("expirationDate") or ""
            if closed:
                logger.info(f"  ✗ SKIP — market is closed/resolved")
                continue

            # ── extract price safely ─────────────────────────────────────
            yes_price = self._extract_yes_price(m)
            if yes_price is None:
                logger.info(f"  ✗ SKIP — could not extract YES price. outcomePrices={m.get('outcomePrices')} outcomes={m.get('outcomes')}")
                continue

            # ── check liquidity ──────────────────────────────────────────
            liquidity = 0.0
            for field in ["volumeNum", "volume", "liquidityNum", "liquidity", "volume24hr"]:
                val = m.get(field)
                if val is not None:
                    try:
                        liquidity = float(val)
                        break
                    except (TypeError, ValueError):
                        pass

            if liquidity < 100:  # lowered from 500 for debugging
                logger.info(f"  ✗ SKIP — liquidity too low ({liquidity})")
                continue

            logger.info(f"  ✅ PASS — yes_price={yes_price:.3f} liquidity={liquidity:.0f}")

            results.append({
                "id":        mid,
                "title":     title,
                "yes_price": yes_price,
                "no_price":  round(1 - yes_price, 4),
                "liquidity": liquidity,
                "end_date":  end_date,
                "raw":       m,
            })

        logger.info(f"After filter: {len(results)} BTC UP/DOWN short-term markets")
        return results

    def _extract_yes_price(self, m: dict) -> Optional[float]:
        """
        Safely extract the UP/YES price from any Polymarket market structure.
        Handles multiple field name variations.
        """
        # Try outcomePrices + outcomes together
        outcomes = m.get("outcomes", [])
        prices   = m.get("outcomePrices", [])

        if outcomes and prices:
            for i, outcome in enumerate(outcomes):
                if str(outcome).lower() in ["up", "yes", "higher", "above", "bull"]:
                    try:
                        p = float(prices[i])
                        if 0 < p < 1:
                            return p
                    except (IndexError, ValueError, TypeError):
                        pass

        # Fallback: first price in outcomePrices
        if prices:
            try:
                p = float(prices[0])
                if 0 < p < 1:
                    return p
            except (ValueError, TypeError):
                pass

        # Fallback: tokens array (CLOB structure)
        tokens = m.get("tokens", [])
        for token in tokens:
            if str(token.get("outcome", "")).lower() in ["up", "yes", "higher", "above"]:
                price = token.get("price")
                if price is not None:
                    try:
                        p = float(price)
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
