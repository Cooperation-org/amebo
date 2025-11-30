#!/usr/bin/env python3
"""
Start Slack Socket Mode Listener
Runs as a background service to collect real-time messages
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.slack_listener import SlackListener
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Start the Slack listener"""
    logger.info("=" * 70)
    logger.info("SLACK HELPER BOT - REAL-TIME LISTENER")
    logger.info("=" * 70)

    listener = SlackListener()

    try:
        await listener.start()
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down listener...")
        await listener.stop()
    except Exception as e:
        logger.error(f"❌ Listener error: {e}", exc_info=True)
        await listener.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
