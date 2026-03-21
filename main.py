"""
BTC 15-Min Window Bot
Scans Polymarket UP/DOWN BTC markets, runs technical filters,
and sends Telegram signals before each 15-min window opens.
"""

import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import Config
from scanner import WindowScanner

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("main")

ET = pytz.timezone("America/New_York")


async def scan_job():
    """Runs before every 15-min window: :55, :10, :25, :40"""
    scanner = WindowScanner()
    await scanner.run()


async def main():
    logger.info("BTC Window Bot starting...")
    Config.validate()

    scheduler = AsyncIOScheduler(timezone=ET)

    # Fire 5 mins before each 15-min window boundary
    # Windows open at :00, :15, :30, :45 → scan at :55, :10, :25, :40
    for minute in ["55", "10", "25", "40"]:
        scheduler.add_job(
            scan_job,
            CronTrigger(minute=minute, timezone=ET),
            id=f"scan_{minute}",
            max_instances=1,
            misfire_grace_time=60
        )

    scheduler.start()
    logger.info("Scheduler running. Waiting for window triggers...")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
