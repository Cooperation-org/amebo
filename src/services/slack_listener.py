"""
Slack Socket Mode Listener - Real-time event collection
Listens to message events from all connected workspaces and stores in PostgreSQL + ChromaDB
"""

import logging
import asyncio
from typing import Dict, List
from datetime import datetime

from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from src.db.connection import DatabaseConnection
from src.db.chromadb_client import ChromaDBClient
from psycopg2 import extras

logger = logging.getLogger(__name__)


class SlackListener:
    """
    Multi-workspace Slack event listener using Socket Mode.
    Handles message events, reactions, and user updates in real-time.
    """

    def __init__(self):
        """Initialize the listener"""
        self.chromadb_client = ChromaDBClient()
        self.workspace_apps: Dict[str, AsyncApp] = {}
        self.handlers: Dict[str, AsyncSocketModeHandler] = {}
        self.running = False

    async def load_workspaces(self):
        """Load all active workspace installations from database"""
        DatabaseConnection.initialize_pool()
        conn = DatabaseConnection.get_connection()

        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT workspace_id, bot_token, app_token
                    FROM installations
                    WHERE is_active = true AND app_token IS NOT NULL
                    """
                )
                installations = cur.fetchall()

            logger.info(f"Found {len(installations)} active workspace installations")
            return installations

        finally:
            DatabaseConnection.return_connection(conn)

    async def setup_workspace_app(self, workspace_id: str, bot_token: str, app_token: str):
        """
        Set up Slack app and socket mode handler for a workspace

        Args:
            workspace_id: Slack workspace ID
            bot_token: Bot user OAuth token
            app_token: App-level token for Socket Mode
        """
        try:
            # Create Slack app for this workspace
            app = AsyncApp(
                token=bot_token,
                # No signing secret needed for Socket Mode
            )

            # Register event handlers
            self._register_message_handler(app, workspace_id)
            self._register_reaction_handler(app, workspace_id)
            self._register_user_change_handler(app, workspace_id)
            self._register_channel_handler(app, workspace_id)

            # Create Socket Mode handler
            handler = AsyncSocketModeHandler(app, app_token)

            # Store references
            self.workspace_apps[workspace_id] = app
            self.handlers[workspace_id] = handler

            logger.info(f"✅ Set up listener for workspace {workspace_id}")

        except Exception as e:
            logger.error(f"Failed to setup workspace {workspace_id}: {e}", exc_info=True)

    def _register_message_handler(self, app: AsyncApp, workspace_id: str):
        """Register handler for message events"""

        @app.event("message")
        async def handle_message(event, client: AsyncWebClient):
            """Handle new message events"""
            try:
                # Ignore bot messages and message edits initially
                if event.get("subtype") in ["bot_message", "message_changed", "message_deleted"]:
                    return

                logger.info(f"📩 New message in {workspace_id}: {event.get('channel')}")

                # Extract message data
                message_data = {
                    'workspace_id': workspace_id,
                    'slack_ts': event.get('ts'),
                    'channel_id': event.get('channel'),
                    'user_id': event.get('user'),
                    'text': event.get('text', ''),
                    'thread_ts': event.get('thread_ts'),
                    'message_type': 'thread_reply' if event.get('thread_ts') else 'regular',
                }

                # Get channel name
                try:
                    channel_info = await client.conversations_info(channel=message_data['channel_id'])
                    message_data['channel_name'] = channel_info['channel']['name']
                except SlackApiError:
                    message_data['channel_name'] = 'unknown'

                # Get user name
                try:
                    user_info = await client.users_info(user=message_data['user_id'])
                    message_data['user_name'] = user_info['user']['name']
                except SlackApiError:
                    message_data['user_name'] = 'unknown'

                # Get permalink
                try:
                    permalink_response = await client.chat_getPermalink(
                        channel=message_data['channel_id'],
                        message_ts=message_data['slack_ts']
                    )
                    message_data['permalink'] = permalink_response['permalink']
                except SlackApiError:
                    message_data['permalink'] = None

                # Count links, mentions
                message_data['link_count'] = message_data['text'].count('http')
                message_data['mention_count'] = message_data['text'].count('<@')

                # Store message (dual-write to PostgreSQL + ChromaDB)
                await self._store_message(message_data)

            except Exception as e:
                logger.error(f"Error handling message: {e}", exc_info=True)

    def _register_reaction_handler(self, app: AsyncApp, workspace_id: str):
        """Register handler for reaction events"""

        @app.event("reaction_added")
        async def handle_reaction_added(event, client: AsyncWebClient):
            """Handle reaction added events"""
            try:
                logger.info(f"👍 Reaction added in {workspace_id}")

                reaction_data = {
                    'workspace_id': workspace_id,
                    'slack_ts': event['item']['ts'],
                    'channel_id': event['item']['channel'],
                    'user_id': event['user'],
                    'reaction_name': event['reaction'],
                }

                # Get user name
                try:
                    user_info = await client.users_info(user=reaction_data['user_id'])
                    reaction_data['user_name'] = user_info['user']['name']
                except SlackApiError:
                    reaction_data['user_name'] = 'unknown'

                # Store reaction
                await self._store_reaction(reaction_data)

            except Exception as e:
                logger.error(f"Error handling reaction: {e}", exc_info=True)

        @app.event("reaction_removed")
        async def handle_reaction_removed(event):
            """Handle reaction removed events"""
            try:
                logger.info(f"👎 Reaction removed in {workspace_id}")

                reaction_data = {
                    'workspace_id': workspace_id,
                    'slack_ts': event['item']['ts'],
                    'user_id': event['user'],
                    'reaction_name': event['reaction'],
                }

                # Remove reaction from database
                await self._remove_reaction(reaction_data)

            except Exception as e:
                logger.error(f"Error handling reaction removal: {e}", exc_info=True)

    def _register_user_change_handler(self, app: AsyncApp, workspace_id: str):
        """Register handler for user change events"""

        @app.event("user_change")
        async def handle_user_change(event):
            """Handle user profile changes"""
            try:
                logger.info(f"👤 User updated in {workspace_id}")

                user = event['user']
                await self._update_user(workspace_id, user)

            except Exception as e:
                logger.error(f"Error handling user change: {e}", exc_info=True)

    def _register_channel_handler(self, app: AsyncApp, workspace_id: str):
        """Register handler for channel events"""

        @app.event("channel_created")
        async def handle_channel_created(event):
            """Handle new channel creation"""
            try:
                logger.info(f"📢 Channel created in {workspace_id}")

                channel = event['channel']
                await self._store_channel(workspace_id, channel)

            except Exception as e:
                logger.error(f"Error handling channel creation: {e}", exc_info=True)

    async def _store_message(self, message_data: dict):
        """
        Store message in PostgreSQL (metadata) and ChromaDB (content)

        Args:
            message_data: Dictionary with message information
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Insert message metadata into PostgreSQL
                cur.execute(
                    """
                    INSERT INTO message_metadata (
                        workspace_id, slack_ts, channel_id, channel_name,
                        user_id, user_name, message_type, thread_ts,
                        permalink, link_count, mention_count,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (workspace_id, slack_ts) DO UPDATE
                    SET channel_name = EXCLUDED.channel_name,
                        user_name = EXCLUDED.user_name
                    RETURNING message_id
                    """,
                    (
                        message_data['workspace_id'],
                        message_data['slack_ts'],
                        message_data['channel_id'],
                        message_data['channel_name'],
                        message_data['user_id'],
                        message_data['user_name'],
                        message_data['message_type'],
                        message_data.get('thread_ts'),
                        message_data.get('permalink'),
                        message_data.get('link_count', 0),
                        message_data.get('mention_count', 0)
                    )
                )
                result = cur.fetchone()
                message_id = result['message_id']

                # Store message text in ChromaDB
                chromadb_id = self.chromadb_client.add_message(
                    workspace_id=message_data['workspace_id'],
                    message_id=message_id,
                    slack_ts=message_data['slack_ts'],
                    message_text=message_data['text'],
                    metadata={
                        'channel_id': message_data['channel_id'],
                        'channel_name': message_data['channel_name'],
                        'user_id': message_data['user_id'],
                        'user_name': message_data['user_name'],
                        'timestamp': message_data['slack_ts']
                    }
                )

                # Update message with ChromaDB ID
                cur.execute(
                    "UPDATE message_metadata SET chromadb_id = %s WHERE message_id = %s",
                    (chromadb_id, message_id)
                )

                conn.commit()
                logger.info(f"✅ Stored message {message_id} from {message_data['channel_name']}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store message: {e}", exc_info=True)
        finally:
            DatabaseConnection.return_connection(conn)

    async def _store_reaction(self, reaction_data: dict):
        """Store reaction in PostgreSQL"""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Get message_id from slack_ts
                cur.execute(
                    "SELECT message_id FROM message_metadata WHERE workspace_id = %s AND slack_ts = %s",
                    (reaction_data['workspace_id'], reaction_data['slack_ts'])
                )
                message = cur.fetchone()

                if not message:
                    logger.warning(f"Message not found for reaction: {reaction_data['slack_ts']}")
                    return

                # Insert reaction
                cur.execute(
                    """
                    INSERT INTO reactions (
                        workspace_id, message_id, user_id, user_name, reaction_name, reacted_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (workspace_id, message_id, user_id, reaction_name) DO NOTHING
                    """,
                    (
                        reaction_data['workspace_id'],
                        message['message_id'],
                        reaction_data['user_id'],
                        reaction_data.get('user_name', ''),
                        reaction_data['reaction_name']
                    )
                )

                # Update message has_reactions flag
                cur.execute(
                    "UPDATE message_metadata SET has_reactions = true WHERE message_id = %s",
                    (message['message_id'],)
                )

                conn.commit()
                logger.info(f"✅ Stored reaction {reaction_data['reaction_name']}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store reaction: {e}", exc_info=True)
        finally:
            DatabaseConnection.return_connection(conn)

    async def _remove_reaction(self, reaction_data: dict):
        """Remove reaction from PostgreSQL"""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                # Get message_id
                cur.execute(
                    "SELECT message_id FROM message_metadata WHERE workspace_id = %s AND slack_ts = %s",
                    (reaction_data['workspace_id'], reaction_data['slack_ts'])
                )
                message = cur.fetchone()

                if not message:
                    return

                # Delete reaction
                cur.execute(
                    """
                    DELETE FROM reactions
                    WHERE workspace_id = %s AND message_id = %s
                      AND user_id = %s AND reaction_name = %s
                    """,
                    (
                        reaction_data['workspace_id'],
                        message[0],
                        reaction_data['user_id'],
                        reaction_data['reaction_name']
                    )
                )

                conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to remove reaction: {e}", exc_info=True)
        finally:
            DatabaseConnection.return_connection(conn)

    async def _update_user(self, workspace_id: str, user: dict):
        """Update user information in PostgreSQL"""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (
                        workspace_id, user_id, user_name, real_name,
                        display_name, email, title, is_bot, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (workspace_id, user_id) DO UPDATE
                    SET user_name = EXCLUDED.user_name,
                        real_name = EXCLUDED.real_name,
                        display_name = EXCLUDED.display_name,
                        email = EXCLUDED.email,
                        title = EXCLUDED.title,
                        updated_at = NOW()
                    """,
                    (
                        workspace_id,
                        user['id'],
                        user.get('name'),
                        user.get('real_name'),
                        user.get('profile', {}).get('display_name'),
                        user.get('profile', {}).get('email'),
                        user.get('profile', {}).get('title'),
                        user.get('is_bot', False)
                    )
                )
                conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update user: {e}", exc_info=True)
        finally:
            DatabaseConnection.return_connection(conn)

    async def _store_channel(self, workspace_id: str, channel: dict):
        """Store channel information in PostgreSQL"""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO channels (
                        workspace_id, channel_id, channel_name,
                        is_private, is_archived, created_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (workspace_id, channel_id) DO UPDATE
                    SET channel_name = EXCLUDED.channel_name,
                        is_archived = EXCLUDED.is_archived
                    """,
                    (
                        workspace_id,
                        channel['id'],
                        channel['name'],
                        channel.get('is_private', False),
                        channel.get('is_archived', False)
                    )
                )
                conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store channel: {e}", exc_info=True)
        finally:
            DatabaseConnection.return_connection(conn)

    async def start(self):
        """Start listening to all workspaces"""
        logger.info("🚀 Starting Slack listener...")

        # Load all workspace installations
        installations = await self.load_workspaces()

        if not installations:
            logger.warning("No active workspace installations found")
            return

        # Set up apps for each workspace
        for installation in installations:
            await self.setup_workspace_app(
                workspace_id=installation['workspace_id'],
                bot_token=installation['bot_token'],
                app_token=installation['app_token']
            )

        # Start all handlers concurrently
        self.running = True
        tasks = [
            asyncio.create_task(handler.start_async())
            for handler in self.handlers.values()
        ]

        logger.info(f"✅ Listening to {len(tasks)} workspaces")

        # Wait for all handlers
        await asyncio.gather(*tasks)

    async def stop(self):
        """Stop all listeners"""
        logger.info("🛑 Stopping Slack listener...")
        self.running = False

        # Close all handlers
        for handler in self.handlers.values():
            await handler.close_async()

        logger.info("✅ Slack listener stopped")


async def main():
    """Main entry point for running the listener"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    listener = SlackListener()

    try:
        await listener.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
        await listener.stop()
    except Exception as e:
        logger.error(f"Listener crashed: {e}", exc_info=True)
        await listener.stop()


if __name__ == "__main__":
    asyncio.run(main())
