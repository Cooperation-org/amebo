#!/usr/bin/env python3
"""
Start Slack Command Handler (Simple Version)
Uses raw Socket Mode SDK - no Bolt framework
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.slack_commands_simple import main
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("SLACK HELPER BOT - COMMAND HANDLER (SIMPLE)")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Available commands in Slack:")
    logger.info("  /ask <question>      - Ask a question (private)")
    logger.info("  /askall <question>   - Ask a question (public)")
    logger.info("  @bot <question>      - Mention the bot")
    logger.info("")
    logger.info("=" * 70)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        sys.exit(1)
