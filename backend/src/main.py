"""
Slack Helper Bot - Unified Application Entry Point

This is the SINGLE entry point for the entire backend.
Starts all services in one process:
- FastAPI server (REST API)
- Slack Socket Mode listener (slash commands, mentions)
- Background task scheduler (automated backfills, cleanup)

Usage:
    python -m src.main

Environment Variables Required:
    - DATABASE_URL: PostgreSQL connection string
    - SLACK_BOT_TOKEN: Bot token (xoxb-...)
    - SLACK_APP_TOKEN: App token (xapp-...)
    - ANTHROPIC_API_KEY: Claude API key
    - ENCRYPTION_KEY: For encrypting credentials (optional for now)
"""

import asyncio
import signal
import sys
import logging
from typing import Optional

import uvicorn
from uvicorn import Config, Server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('slack_helper.log')
    ]
)

logger = logging.getLogger(__name__)

# Global app instance for API access (used by admin routes)
app_instance = None


class SlackHelperApp:
    """
    Main application class that manages all services.
    """

    def __init__(self):
        self.fastapi_server: Optional[Server] = None
        self.slack_task: Optional[asyncio.Task] = None
        self.scheduler_task: Optional[asyncio.Task] = None
        self.scheduler = None  # TaskScheduler instance
        self.shutdown_event = asyncio.Event()

    async def start_fastapi_server(self):
        """
        Start the FastAPI server.
        Handles REST API requests for Q&A, auth, workspace management.
        """
        from src.api.main import app as fastapi_app

        logger.info("🚀 Starting FastAPI server on http://0.0.0.0:8000")

        config = Config(
            app=fastapi_app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=True,
            loop="asyncio"
        )

        self.fastapi_server = Server(config=config)

        try:
            await self.fastapi_server.serve()
        except asyncio.CancelledError:
            logger.info("FastAPI server shutdown requested")
        except Exception as e:
            logger.error(f"FastAPI server error: {e}", exc_info=True)
            raise

    async def start_slack_listener(self):
        """
        Start the Slack Socket Mode listener.
        Handles slash commands (/ask, /askall) and app mentions.
        """
        import os
        from slack_sdk.web.async_client import AsyncWebClient
        from slack_sdk.socket_mode.aiohttp import SocketModeClient
        from src.services.slack_commands_simple import process_slash_command, process_events

        bot_token = os.getenv("SLACK_BOT_TOKEN")
        app_token = os.getenv("SLACK_APP_TOKEN")

        if not bot_token or not app_token:
            logger.warning("⚠️  Slack tokens not configured - Slack features disabled")
            logger.warning("   Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN to enable")
            return

        logger.info("🚀 Starting Slack Socket Mode listener")
        logger.info(f"   Bot token: {bot_token[:20]}...")
        logger.info(f"   App token: {app_token[:20]}...")

        try:
            # Create Socket Mode client
            client = SocketModeClient(
                app_token=app_token,
                web_client=AsyncWebClient(token=bot_token)
            )

            # Register event handlers
            client.socket_mode_request_listeners.append(process_slash_command)
            client.socket_mode_request_listeners.append(process_events)

            logger.info("✅ Slack listener ready - slash commands enabled")

            # Connect and keep running
            await client.connect()

            # Wait until shutdown is requested
            await self.shutdown_event.wait()

            # Disconnect gracefully
            await client.disconnect()
            logger.info("Slack listener disconnected")

        except asyncio.CancelledError:
            logger.info("Slack listener shutdown requested")
        except Exception as e:
            logger.error(f"Slack listener error: {e}", exc_info=True)
            raise

    async def start_scheduler(self):
        """
        Start the background task scheduler.
        Handles automated backfills, cleanup jobs, etc.
        """
        from src.services.scheduler import TaskScheduler

        logger.info("🚀 Starting background task scheduler")

        try:
            # Initialize scheduler
            self.scheduler = TaskScheduler()

            # Start scheduler (loads jobs from database)
            await self.scheduler.start()

            # Wait until shutdown is requested
            await self.shutdown_event.wait()

            # Stop scheduler gracefully
            await self.scheduler.stop()
            logger.info("Scheduler stopped")

        except asyncio.CancelledError:
            logger.info("Scheduler shutdown requested")
            if self.scheduler:
                await self.scheduler.stop()
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
            raise

    async def start(self):
        """
        Start all services concurrently.
        """
        logger.info("=" * 70)
        logger.info("SLACK HELPER BOT - UNIFIED BACKEND")
        logger.info("=" * 70)
        logger.info("")

        # Create tasks for all services
        tasks = []

        # 1. FastAPI server (HTTP API)
        fastapi_task = asyncio.create_task(
            self.start_fastapi_server(),
            name="fastapi-server"
        )
        tasks.append(fastapi_task)

        # 2. Slack listener (Socket Mode)
        self.slack_task = asyncio.create_task(
            self.start_slack_listener(),
            name="slack-listener"
        )
        tasks.append(self.slack_task)

        # 3. Background scheduler
        self.scheduler_task = asyncio.create_task(
            self.start_scheduler(),
            name="scheduler"
        )
        tasks.append(self.scheduler_task)

        logger.info("")
        logger.info("=" * 70)
        logger.info("✅ All services started successfully")
        logger.info("=" * 70)
        logger.info("")
        logger.info("📍 API Documentation: http://localhost:8000/api/docs")
        logger.info("📍 Health Check: http://localhost:8000/health")
        logger.info("")
        logger.info("Press Ctrl+C to shutdown")
        logger.info("")

        # Wait for shutdown signal or any task to fail
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Service failed: {e}")
            # Cancel all tasks on failure
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self):
        """
        Gracefully shutdown all services.
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("🛑 Shutting down Slack Helper Bot...")
        logger.info("=" * 70)

        # Signal all services to shutdown
        self.shutdown_event.set()

        # Cancel background tasks
        tasks_to_cancel = []

        if self.slack_task and not self.slack_task.done():
            tasks_to_cancel.append(self.slack_task)

        if self.scheduler_task and not self.scheduler_task.done():
            tasks_to_cancel.append(self.scheduler_task)

        if tasks_to_cancel:
            logger.info(f"Cancelling {len(tasks_to_cancel)} background tasks...")
            for task in tasks_to_cancel:
                task.cancel()

            # Wait for cancellation with timeout
            await asyncio.wait(tasks_to_cancel, timeout=5.0)

        # Shutdown FastAPI server
        if self.fastapi_server:
            logger.info("Shutting down FastAPI server...")
            self.fastapi_server.should_exit = True

        # Close database connections
        from src.db.connection import DatabaseConnection
        DatabaseConnection.close_all_connections()

        logger.info("✅ Shutdown complete")
        logger.info("=" * 70)


async def main():
    """
    Main entry point - creates app and handles signals.
    """
    global app_instance

    app = SlackHelperApp()
    app_instance = app  # Make available to admin routes

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler(signum):
        logger.info(f"Received signal {signum}")
        asyncio.create_task(app.shutdown())

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await app.shutdown()


if __name__ == "__main__":
    """
    Entry point when running: python -m src.main
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Failed to start: {e}", exc_info=True)
        sys.exit(1)
