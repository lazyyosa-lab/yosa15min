"""
Telegram bot — formats and sends signal/skip messages.
Uses the Bot API sendMessage endpoint directly (no python-telegram-bot overhead).
"""

import logging
from datetime import datetime
import asyncio
import aiohttp
import pytz

from config import Config
from signals.indicators import IndicatorResult
from signals.filters import FilterResult

logger = logging.getLogger("telegram")

ET = pytz.timezone("America/New_York")


class TelegramBot:

    async def send(self, text: str):
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": Config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
                    logger.info("Telegram message sent")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def send_signal(
        self,
        market_title: str,
        indicators: IndicatorResult,
        filters: FilterResult,
        chainlink_spread: float
    ):
        now_et = datetime.now(ET).strftime("%I:%M %p ET")
        tier_label = {
            "STRONG_TRADE": "🔥 STRONG SIGNAL",
            "TRADE": "🟢 SIGNAL",
        }.get(filters.signal_tier, "🟢 SIGNAL")

        tier = "🔥 PRIORITY" if filters.is_priority_window else tier_label
        size_pct = int(filters.size_pct * 100)
        edge_pct = int(filters.edge * 100)
        model_pct = int(filters.model_prob * 100)
        market_pct = int(filters.market_prob * 100)

        # Filter summary — show which ones passed/failed compactly
        checks = {
            "ATR": filters.atr_expanded,
            "VWAP": filters.vwap_clear,
            "EMA align": filters.ema_aligned,
            "EMA div": filters.ema_diverging,
            "MACD": filters.macd_accelerating,
            "Volume": filters.volume_confirmed,
            "Body": filters.body_committed,
            "Chainlink": filters.chainlink_spread_ok,
            "RSI8": filters.rsi_signal,
            "BB compr": filters.bb_compressed,
        }
        filter_lines = " ".join(
            f"{'✅' if v else '⚠️'}{k}" for k, v in checks.items()
        )

        msg = (
            f"{tier} SIGNAL — BTC 15-Min\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>{market_title}</b>\n"
            f"⏰ Scanned: {now_et}\n\n"
            f"Direction: <b>{filters.direction}</b>\n"
            f"Model Prob: <b>{model_pct}%</b> | Market: <b>{market_pct}%</b>\n"
            f"Edge: <b>+{edge_pct}%</b>\n\n"
            f"BTC Price: ${indicators.current_price:,.2f}\n"
            f"VWAP: ${indicators.vwap:,.2f}\n"
            f"EMA9/21: {indicators.ema9:,.0f} / {indicators.ema21:,.0f}\n"
            f"RSI(8): {indicators.rsi8:.1f}\n"
            f"ATR: {indicators.current_atr:.1f} (avg {indicators.avg_atr_20:.1f})\n"
            f"BB width rank: {indicators.bb_width_pct_rank:.0%}\n"
            f"Volume: {indicators.volume_ratio:.2f}x avg\n"
            f"Body Ratio: {indicators.body_ratio:.2f}\n"
            f"Chainlink spread: {chainlink_spread:.3%}\n\n"
            f"Filters: {filters.filters_passed}/10 passed\n"
            f"{filter_lines}\n\n"
            f"💰 Suggested size: <b>{size_pct}% of bankroll</b>"
        )

        await self.send(msg)

    async def send_skip(
        self,
        market_title: str,
        filters: FilterResult,
        is_priority: bool = False
    ):
        now_et = datetime.now(ET).strftime("%I:%M %p ET")
        reasons = "\n".join(f"  • {r}" for r in filters.failed_reasons[:4])  # max 4

        msg = (
            f"⏭️ SKIP — BTC 15-Min\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 {market_title}\n"
            f"⏰ {now_et}\n\n"
            f"Filters: {filters.filters_passed}/10 passed "
            f"({'priority' if is_priority else 'standard'} window)\n\n"
            f"Reasons:\n{reasons}"
        )

        await self.send(msg)

    async def send_error(self, context: str, error: str):
        msg = f"⚠️ Bot Error\n{context}\n<code>{error}</code>"
        await self.send(msg)

    async def send_startup(self):
        msg = (
            "🤖 <b>BTC Window Bot Online</b>\n"
            "Scanning all 15-min windows\n"
            "Priority: 9:00 AM ET (pre-NYSE)\n"
            "All times in ET"
        )
        await self.send(msg)
