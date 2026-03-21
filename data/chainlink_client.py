"""
Chainlink client — reads BTC/USD price from the on-chain aggregator.
Resolution source for Polymarket UP/DOWN markets.
Uses web3.py with a public Ethereum RPC.
"""

import logging
from typing import Optional
from web3 import Web3

from config import Config

logger = logging.getLogger("chainlink")

# Chainlink AggregatorV3Interface — only need latestRoundData
AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]


class ChainlinkClient:

    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(Config.CHAINLINK_RPC_URL))
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(Config.CHAINLINK_BTC_USD_FEED),
            abi=AGGREGATOR_ABI
        )
        self._decimals: Optional[int] = None

    def _get_decimals(self) -> int:
        if self._decimals is None:
            self._decimals = self.contract.functions.decimals().call()
        return self._decimals

    def get_price(self) -> Optional[float]:
        """
        Returns the latest Chainlink BTC/USD price.
        Chainlink feeds return price as int256 with N decimals.
        BTC/USD feed uses 8 decimals.
        """
        try:
            round_data = self.contract.functions.latestRoundData().call()
            answer = round_data[1]  # int256 raw price
            decimals = self._get_decimals()
            price = answer / (10 ** decimals)
            logger.info(f"Chainlink BTC/USD: {price:.2f} (updated: {round_data[3]})")
            return price
        except Exception as e:
            logger.error(f"Chainlink fetch failed: {e}")
            return None

    def check_spread(self, binance_price: float) -> tuple[bool, float]:
        """
        Compare Chainlink price to Binance spot.
        Returns (spread_ok, spread_pct).
        Spread > 0.3% is flagged — resolution is Chainlink, not Binance.
        """
        chainlink_price = self.get_price()
        if chainlink_price is None:
            logger.warning("Chainlink unavailable — skipping spread check")
            return True, 0.0  # fail open if RPC is down

        spread = abs(binance_price - chainlink_price) / chainlink_price
        spread_ok = spread < Config.CHAINLINK_SPREAD_MAX
        logger.info(f"Spread: {spread:.4%} — {'OK' if spread_ok else 'FLAGGED'}")
        return spread_ok, spread
