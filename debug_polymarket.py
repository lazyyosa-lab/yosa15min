"""
Run this once to inspect what Polymarket's API actually returns.
python debug_polymarket.py

Prints raw titles and field names so we can fix the filter.
"""

import asyncio
import aiohttp


GAMMA_URL = "https://gamma-api.polymarket.com"


async def main():

    async with aiohttp.ClientSession() as session:

        # ── /markets ─────────────────────────────────────────────────────
        print("\n========== /markets (first 10 titles) ==========")
        async with session.get(
            f"{GAMMA_URL}/markets",
            params={"active": "true", "closed": "false", "limit": 10}
        ) as r:
            data = await r.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            for m in markets[:10]:
                print(m.get("question") or m.get("title") or "NO TITLE")

        print("\n========== /markets fields (first item) ==========")
        if markets:
            print(list(markets[0].keys()))

        # ── /events ──────────────────────────────────────────────────────
        print("\n========== /events (first 10 titles) ==========")
        async with session.get(
            f"{GAMMA_URL}/events",
            params={"active": "true", "closed": "false", "limit": 10}
        ) as r:
            data = await r.json()
            events = data if isinstance(data, list) else data.get("events", [])
            for e in events[:10]:
                print(e.get("title") or e.get("name") or "NO TITLE")
                for m in e.get("markets", [])[:3]:
                    print(f"  → {m.get('question') or m.get('title') or 'NO TITLE'}")

        print("\n========== /events fields (first item) ==========")
        if events:
            print(list(events[0].keys()))

        # ── Search specifically for UP/DOWN ───────────────────────────────
        print("\n========== Searching all markets for 'up' 'down' '15' ==========")
        async with session.get(
            f"{GAMMA_URL}/markets",
            params={"active": "true", "closed": "false", "limit": 100}
        ) as r:
            data = await r.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            hits = 0
            for m in markets:
                t = (m.get("question") or m.get("title") or "").lower()
                if any(k in t for k in ["up", "down", "15", "higher", "lower"]):
                    print(f"  HIT: {m.get('question') or m.get('title')}")
                    hits += 1
            print(f"Total hits: {hits} / {len(markets)}")


asyncio.run(main())
