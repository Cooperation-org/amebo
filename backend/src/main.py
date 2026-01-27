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
import os
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

        # Get port from environment variable, default to 8003
        api_port = int(os.getenv('API_PORT', 8003))

        logger.info(f"Starting FastAPI server on http://0.0.0.0:{api_port}")

        config = Config(
            app=fastapi_app,
            host="0.0.0.0",
            port=api_port,
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

        NOTE: Disabled when using Event Subscriptions API (USE_EVENT_SUBSCRIPTIONS=true)
        """
        import os
        from slack_sdk.web.async_client import AsyncWebClient
        from slack_sdk.socket_mode.aiohttp import SocketModeClient
        from src.services.slack_commands import process_slash_command, process_events

        # Check if using Event Subscriptions instead
        if os.getenv("USE_EVENT_SUBSCRIPTIONS", "false").lower() == "true":
            logger.info("Using Event Subscriptions API - Socket Mode disabled")
            return

        bot_token = os.getenv("SLACK_BOT_TOKEN")
        app_token = os.getenv("SLACK_APP_TOKEN")

        if not bot_token or not app_token:
            logger.warning(" Slack tokens not configured - Slack features disabled")
            logger.warning("   Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN to enable")
            return

        logger.info("Starting Slack Socket Mode listener")
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

            logger.info("Slack listener ready - slash commands enabled")

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

    async def initialize_workspace(self):
        """
        Initialize workspace in database and create backfill schedule.
        Runs on startup to ensure workspace is set up.
        """
        from src.db.connection import DatabaseConnection
        from slack_sdk import WebClient

        logger.info("Starting workspace initialization...")

        bot_token = os.getenv("SLACK_BOT_TOKEN")
        if not bot_token:
            logger.warning("SLACK_BOT_TOKEN not found - skipping workspace initialization")
            return

        try:
            # Get workspace info from Slack
            logger.info(f"Connecting to Slack with bot token: {bot_token[:20]}...")
            client = WebClient(token=bot_token)
            auth_response = client.auth_test()
            workspace_id = auth_response['team_id']
            team_name = auth_response['team']

            logger.info(f"Connected to workspace: {team_name} ({workspace_id})")

            # Initialize database connection
            DatabaseConnection.initialize_pool()
            conn = DatabaseConnection.get_connection()

            try:
                with conn.cursor() as cur:
                    # Insert or update workspace
                    logger.info(f"Creating/updating workspace record in database...")
                    cur.execute(
                        """
                        INSERT INTO workspaces (workspace_id, team_name, is_active)
                        VALUES (%s, %s, TRUE)
                        ON CONFLICT (workspace_id) DO UPDATE
                        SET team_name = EXCLUDED.team_name, is_active = TRUE, updated_at = NOW()
                        """,
                        (workspace_id, team_name)
                    )

                    # Check if backfill schedule exists
                    cur.execute(
                        "SELECT schedule_id FROM backfill_schedules WHERE workspace_id = %s",
                        (workspace_id,)
                    )
                    schedule_exists = cur.fetchone()

                    if not schedule_exists:
                        # Create backfill schedule (every 30 minutes)
                        logger.info("Creating backfill schedule (every 30 minutes)...")
                        cur.execute(
                            """
                            INSERT INTO backfill_schedules (
                                workspace_id, schedule_type, cron_expression,
                                days_to_backfill, include_all_channels, is_active
                            )
                            VALUES (%s, 'cron', '*/30 * * * *', 90, TRUE, TRUE)
                            """,
                            (workspace_id,)
                        )
                        logger.info("Backfill schedule created")

                        # Trigger initial backfill
                        logger.info("Triggering initial 90-day backfill...")
                        from src.services.backfill_service import BackfillService
                        backfill_service = BackfillService(workspace_id, bot_token)
                        asyncio.create_task(backfill_service.backfill_messages(days=90))
                        logger.info("Backfill task started in background")
                    else:
                        logger.info("Backfill schedule already exists - skipping creation")

                    conn.commit()
                    logger.info("Database changes committed")

            finally:
                DatabaseConnection.return_connection(conn)

            logger.info(f"Workspace initialization complete for {team_name}")

        except Exception as e:
            logger.error(f"FAILED to initialize workspace: {e}", exc_info=True)
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")

    async def start_scheduler(self):
        """
        Start the background task scheduler.
        Handles automated backfills, cleanup jobs, etc.
        """
        from src.services.scheduler import TaskScheduler

        logger.info("Starting background task scheduler")

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

        # Initialize workspace and backfill schedule
        await self.initialize_workspace()

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

        # Get port for display
        api_port = int(os.getenv('API_PORT', 8003))

        logger.info("")
        logger.info("=" * 70)
        logger.info("All services started successfully")
        logger.info("=" * 70)
        logger.info("")
        logger.info(f"API Documentation: http://localhost:{api_port}/api/docs")
        logger.info(f"Health Check: http://localhost:{api_port}/health")
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
        logger.info("Shutting down Slack Helper Bot...")
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

        logger.info("Shutdown complete")
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
