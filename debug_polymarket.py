"""
Debug script v2 — fetch markets sorted by soonest expiry.
15-min markets will be at the top since they expire first.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone

GAMMA_URL = "https://gamma-api.polymarket.com"

async def main():
    async with aiohttp.ClientSession() as session:

        # Sort by endDate ascending — soonest expiry first
        print("\n=== Markets sorted by soonest expiry (first 20) ===")
        async with session.get(
            f"{GAMMA_URL}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": 20,
                "order": "end_date_iso",
                "ascending": "true"
            }
        ) as r:
            data = await r.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            print(f"Returned {len(markets)} markets")
            for m in markets:
                title = m.get("question") or m.get("title") or "NO TITLE"
                end = m.get("endDateIso") or m.get("endDate") or "NO DATE"
                print(f"  [{end}] {title}")

        print("\n=== Try order=endDate ===")
        async with session.get(
            f"{GAMMA_URL}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": 20,
                "order": "endDate",
                "ascending": "true"
            }
        ) as r:
            data = await r.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            print(f"Returned {len(markets)} markets")
            for m in markets:
                title = m.get("question") or m.get("title") or "NO TITLE"
                end = m.get("endDateIso") or m.get("endDate") or "NO DATE"
                print(f"  [{end}] {title}")

        print("\n=== Try endDate filter directly ===")
        now = datetime.now(timezone.utc)
        async with session.get(
            f"{GAMMA_URL}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": 50,
                "end_date_min": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_date_max": now.strftime("%Y-%m-%dT%H:%M:%SZ").replace(
                    now.strftime("%H:%M:%S"),
                    f"{now.hour:02d}:{(now.minute + 60) % 60:02d}:{now.second:02d}"
                )
            }
        ) as r:
            data = await r.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            print(f"Returned {len(markets)} markets")
            for m in markets[:10]:
                title = m.get("question") or m.get("title") or "NO TITLE"
                end = m.get("endDateIso") or m.get("endDate") or "NO DATE"
                print(f"  [{end}] {title}")

asyncio.run(main())
