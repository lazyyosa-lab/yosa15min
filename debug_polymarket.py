"""
Debug v3 — try CLOB API directly for 15-min BTC markets.
"""

import asyncio
import aiohttp

CLOB_URL  = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"

async def main():
    async with aiohttp.ClientSession() as session:

        # ── 1. CLOB /markets ─────────────────────────────────────────────
        print("\n=== CLOB /markets (first 10) ===")
        async with session.get(f"{CLOB_URL}/markets", params={"limit": 10}) as r:
            print(f"Status: {r.status}")
            if r.status == 200:
                data = await r.json()
                markets = data.get("data", data) if isinstance(data, dict) else data
                print(f"Keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
                if isinstance(markets, list):
                    for m in markets[:10]:
                        print(f"  {m.get('question') or m.get('market_slug') or str(m)[:80]}")
                else:
                    print(f"  data type: {type(markets)}")

        # ── 2. CLOB sampling ─────────────────────────────────────────────
        print("\n=== CLOB /sampling-markets ===")
        async with session.get(f"{CLOB_URL}/sampling-markets", params={"limit": 10}) as r:
            print(f"Status: {r.status}")
            if r.status == 200:
                data = await r.json()
                markets = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(markets, list):
                    for m in markets[:10]:
                        print(f"  {m.get('question') or m.get('market_slug') or str(m)[:80]}")

        # ── 3. CLOB /sampling-simplified-markets ─────────────────────────
        print("\n=== CLOB /sampling-simplified-markets ===")
        async with session.get(f"{CLOB_URL}/sampling-simplified-markets") as r:
            print(f"Status: {r.status}")
            if r.status == 200:
                data = await r.json()
                print(str(data)[:500])

        # ── 4. Gamma events sorted by volume24hr ─────────────────────────
        print("\n=== Gamma /events by volume24hr (check for 15-min) ===")
        async with session.get(
            f"{GAMMA_URL}/events",
            params={"active": "true", "closed": "false", "limit": 50,
                    "order": "volume24hr", "ascending": "false"}
        ) as r:
            print(f"Status: {r.status}")
            if r.status == 200:
                data = await r.json()
                events = data if isinstance(data, list) else data.get("events", [])
                for e in events:
                    title = e.get("title") or e.get("name") or ""
                    tags = [t.get("slug","") for t in e.get("tags", [])]
                    if any(k in title.lower() for k in ["bitcoin","btc","crypto","15"]) \
                       or any("15" in t or "crypto" in t for t in tags):
                        print(f"  [{tags}] {title}")
                        for m in e.get("markets", [])[:2]:
                            print(f"    → {m.get('question','')}")

        # ── 5. Gamma markets with tag search ─────────────────────────────
        print("\n=== Gamma /markets tag_slug variations ===")
        for tag in ["crypto-15m", "15-minute", "15-min", "intraday", "short-term", "crypto-15"]:
            async with session.get(
                f"{GAMMA_URL}/markets",
                params={"active":"true","closed":"false","limit":5,"tag_slug": tag}
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    markets = data if isinstance(data, list) else data.get("markets",[])
                    if markets:
                        print(f"  tag={tag}: {len(markets)} markets")
                        for m in markets[:3]:
                            print(f"    {m.get('question') or m.get('title')}")

asyncio.run(main())
