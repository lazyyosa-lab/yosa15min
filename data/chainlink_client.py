"""
Chainlink client — fetches BTC/USD price via direct JSON-RPC eth_call.
No web3.py dependency, no API key needed.
Tries multiple public RPC endpoints with automatic fallback.

Resolution source matches what Polymarket uses:
https://data.chain.link/streams/btc-usd (on-chain aggregator 0xF4030...)
"""

import logging
import aiohttp
from typing import Optional

from config import Config

logger = logging.getLogger("chainlink")

# Multiple public RPC endpoints — tried in order until one works
FALLBACK_RPCS = [
    "https://ethereum.publicnode.com",
    "https://1rpc.io/eth",
    "https://eth.drpc.org",
    "https://rpc.ankr.com/eth",
]

# Chainlink BTC/USD aggregator on Ethereum mainnet
BTC_USD_FEED = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"

# Function selector for latestRoundData()
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"


class ChainlinkClient:

    async def get_price(self) -> Optional[float]:
        """
        Fetch BTC/USD price directly from the Chainlink on-chain aggregator
        via raw JSON-RPC eth_call. No web3.py needed.
        Tries multiple public RPC endpoints with fallback.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": BTC_USD_FEED,
                    "data": LATEST_ROUND_DATA_SELECTOR
                },
                "latest"
            ],
            "id": 1
        }

        for rpc_url in FALLBACK_RPCS:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        rpc_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=8),
                        headers={"Content-Type": "application/json"}
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"RPC {rpc_url} returned HTTP {resp.status}")
                            continue
                        data = await resp.json()

                result_hex = data.get("result", "")
                if not result_hex or result_hex == "0x":
                    logger.warning(f"RPC {rpc_url} returned empty result")
                    continue

                # latestRoundData() returns 5 x 32-byte words:
                # [0] roundId, [1] answer, [2] startedAt, [3] updatedAt, [4] answeredInRound
                # We need word [1] — bytes 64 to 128 of the hex string (after stripping 0x)
                hex_data = result_hex[2:]
                if len(hex_data) < 128:
                    continue

                answer_hex = hex_data[64:128]
                answer = int(answer_hex, 16)

                # Handle negative int256 (two's complement)
                if answer >= 2 ** 255:
                    answer -= 2 ** 256

                # BTC/USD feed uses 8 decimal places
                price = answer / 1e8

                # Sanity check — BTC should be between $1k and $1M
                if 1_000 < price < 1_000_000:
                    logger.info(f"Chainlink BTC/USD via {rpc_url}: ${price:,.2f}")
                    return price
                else:
                    logger.warning(f"Chainlink price out of range: {price}")
                    continue

            except Exception as e:
                logger.warning(f"RPC {rpc_url} failed: {e}")
                continue

        logger.error("All Chainlink RPC endpoints failed")
        return None

    async def check_spread(self, binance_price: float) -> tuple[bool, float]:
        """
        Compare Chainlink BTC/USD to Binance spot price.
        Returns (spread_ok, spread_pct).

        Spread > 0.3% = block the signal.
        Chainlink unavailable = block the signal (fail closed).
        Resolution is Chainlink — trading blind without it is wrong.
        """
        chainlink_price = await self.get_price()

        if chainlink_price is None:
            logger.warning("Chainlink unavailable — blocking all signals (fail closed)")
            return False, 0.0

        spread = abs(binance_price - chainlink_price) / chainlink_price
        spread_ok = spread < Config.CHAINLINK_SPREAD_MAX

        logger.info(
            f"Binance: ${binance_price:,.2f} | Chainlink: ${chainlink_price:,.2f} | "
            f"Spread: {spread:.4%} — {'OK ✅' if spread_ok else 'FLAGGED ⚠️'}"
        )
        return spread_ok, spread
