"""
Backfill Service - Async message collection from Slack
Integrates with pgvector and PostgreSQL for storage
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from src.db.pgvector_client import PgvectorClient
from src.db.connection import DatabaseConnection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BackfillService:
    """
    Async service for backfilling Slack messages

    Features:
    - Fetch messages from Slack API
    - Store in ChromaDB for semantic search
    - Store metadata in PostgreSQL
    - Support for channel filtering
    - Date-based filtering
    """

    def __init__(self, workspace_id: str, bot_token: str):
        """
        Initialize backfill service

        Args:
            workspace_id: Workspace ID for data isolation
            bot_token: Slack bot token for API access
        """
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if not bot_token:
            raise ValueError("bot_token is required")

        self.workspace_id = workspace_id
        self.slack_client = AsyncWebClient(token=bot_token)
        self.pgvector = PgvectorClient()

    async def backfill_messages(
        self,
        days: int = 7,
        include_all_channels: bool = True,
        channel_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Backfill messages from Slack

        Args:
            days: Number of days to backfill
            include_all_channels: Whether to fetch from all channels
            channel_ids: Specific channel IDs to fetch (if not all)

        Returns:
            Dict with backfill results (total_messages, channels_processed, etc.)
        """
        logger.info(
            f"Starting backfill for workspace {self.workspace_id}\n"
            f"   Days: {days}\n"
            f"   All channels: {include_all_channels}"
        )

        # Calculate date range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        oldest_ts = start_date.timestamp()
        latest_ts = end_date.timestamp()

        # Get channels to process
        if include_all_channels:
            channels = await self._get_all_channels()
        elif channel_ids:
            channels = [{"id": ch_id} for ch_id in channel_ids]
        else:
            raise ValueError("Must specify either include_all_channels=True or provide channel_ids")

        logger.info(f"Processing {len(channels)} channels")

        # Track results
        total_messages = 0
        channels_processed = 0
        errors = []

        # Process each channel
        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel.get("name", "unknown")

            try:
                # Store/update channel metadata in database
                await self._store_channel_metadata(channel)

                messages = await self._fetch_channel_messages(
                    channel_id=channel_id,
                    channel_name=channel_name,
                    oldest=oldest_ts,
                    latest=latest_ts
                )

                if messages:
                    await self._store_messages(messages, channel_id, channel_name)
                    total_messages += len(messages)
                    channels_processed += 1

                    logger.info(
                        f"#{channel_name}: {len(messages)} messages collected"
                    )
                else:
                    logger.debug(f"⏭️  #{channel_name}: No messages in date range")

            except SlackApiError as e:
                error_msg = f"Slack API error for #{channel_name}: {e.response['error']}"
                logger.warning(error_msg)
                errors.append(error_msg)
            except Exception as e:
                error_msg = f"Error processing #{channel_name}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)

        logger.info(
            f"Backfill complete:\n"
            f"   Total messages: {total_messages}\n"
            f"   Channels processed: {channels_processed}/{len(channels)}\n"
            f"   Errors: {len(errors)}"
        )

        return {
            "total_messages": total_messages,
            "channels_processed": channels_processed,
            "total_channels": len(channels),
            "errors": errors,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }

    async def _get_all_channels(self) -> List[Dict[str, Any]]:
        """Get all public channels in workspace"""
        try:
            response = await self.slack_client.conversations_list(
                types="public_channel",
                exclude_archived=True,
                limit=200
            )

            channels = response.get("channels", [])
            logger.info(f"Found {len(channels)} public channels")
            return channels

        except SlackApiError as e:
            logger.error(f"Error fetching channels: {e.response['error']}")
            return []

    async def _store_channel_metadata(self, channel: Dict[str, Any]):
        """
        Store channel metadata in database

        Args:
            channel: Channel data from Slack API
        """
        try:
            from src.db.connection import DatabaseConnection

            conn = DatabaseConnection.get_connection()
            cur = conn.cursor()

            try:
                cur.execute(
                    """
                    INSERT INTO channels (channel_id, channel_name, workspace_id, is_private, is_archived)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, channel_id) DO UPDATE
                    SET channel_name = EXCLUDED.channel_name,
                        is_archived = EXCLUDED.is_archived,
                        last_sync = NOW()
                    """,
                    (
                        channel["id"],
                        channel.get("name", "unknown"),
                        self.workspace_id,
                        channel.get("is_private", False),
                        channel.get("is_archived", False)
                    )
                )
                conn.commit()

            finally:
                cur.close()
                DatabaseConnection.return_connection(conn)

        except Exception as e:
            logger.warning(f"Could not store channel metadata: {e}")

    async def _fetch_channel_messages(
        self,
        channel_id: str,
        channel_name: str,
        oldest: float,
        latest: float
    ) -> List[Dict[str, Any]]:
        """
        Fetch messages from a specific channel

        Args:
            channel_id: Channel ID
            channel_name: Channel name (for metadata)
            oldest: Oldest timestamp (unix)
            latest: Latest timestamp (unix)

        Returns:
            List of message dictionaries
        """
        messages = []
        cursor = None
        has_more = True

        while has_more:
            try:
                response = await self.slack_client.conversations_history(
                    channel=channel_id,
                    oldest=str(oldest),
                    latest=str(latest),
                    limit=200,
                    cursor=cursor
                )

                batch = response.get("messages", [])

                # Filter out bot messages, join notifications, etc.
                for msg in batch:
                    # Skip system messages and bot messages
                    if msg.get("subtype") in ["channel_join", "channel_leave", "bot_message"]:
                        continue

                    # Skip messages without text
                    if not msg.get("text"):
                        continue

                    # Skip very short messages (likely not useful)
                    if len(msg.get("text", "").strip()) < 10:
                        continue

                    # Add channel context
                    msg["channel_id"] = channel_id
                    msg["channel_name"] = channel_name

                    messages.append(msg)

                # Check pagination
                has_more = response.get("has_more", False)
                cursor = response.get("response_metadata", {}).get("next_cursor")

                if not has_more:
                    break

            except SlackApiError as e:
                logger.error(f"Error fetching messages from #{channel_name}: {e}")
                break

        return messages

    async def _store_messages(
        self,
        messages: List[Dict[str, Any]],
        channel_id: str,
        channel_name: str
    ):
        """
        Store messages in BOTH message_metadata (Postgres) AND message_vectors
        (pgvector).

        The realtime slack_listener writes to both; this batch path historically
        only wrote to pgvector, which left `message_metadata` silently stale.
        Any query that joins to message_metadata (channel stats, links, files,
        thread participants, reactions) breaks without this write.

        Args:
            messages: List of Slack messages
            channel_id: Channel ID
            channel_name: Channel name
        """
        if not messages:
            return

        # Get user info for usernames
        user_map = await self._get_user_info([msg.get("user") for msg in messages if msg.get("user")])

        # First write metadata rows and collect the assigned message_id per slack_ts
        # so pgvector can be linked back via FK. ON CONFLICT keeps re-ingestions
        # idempotent.
        ts_to_message_id: Dict[str, int] = {}
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                for msg in messages:
                    text = msg.get("text") or ""
                    user_id = msg.get("user", "unknown")
                    user_name = user_map.get(user_id, "unknown")
                    slack_ts = msg["ts"]
                    # Slack ts is "<seconds>.<microseconds>". Convert to UTC dt.
                    try:
                        created_at = datetime.fromtimestamp(float(slack_ts), tz=timezone.utc)
                    except (ValueError, TypeError):
                        created_at = datetime.now(timezone.utc)

                    cur.execute(
                        """
                        INSERT INTO message_metadata (
                            workspace_id, slack_ts, channel_id, channel_name,
                            user_id, user_name, message_type, thread_ts,
                            reply_count, reply_users_count,
                            has_attachments, has_files, has_reactions,
                            mention_count, link_count,
                            permalink, is_pinned, edited_at, created_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (workspace_id, slack_ts) DO UPDATE
                        SET reply_count = EXCLUDED.reply_count,
                            reply_users_count = EXCLUDED.reply_users_count,
                            has_reactions = EXCLUDED.has_reactions,
                            edited_at = EXCLUDED.edited_at
                        RETURNING message_id
                        """,
                        (
                            self.workspace_id, slack_ts, channel_id, channel_name,
                            user_id, user_name,
                            'thread_reply' if msg.get('thread_ts') and msg.get('thread_ts') != slack_ts else 'regular',
                            msg.get('thread_ts'),
                            msg.get('reply_count', 0),
                            msg.get('reply_users_count', 0),
                            bool(msg.get('attachments')),
                            bool(msg.get('files')),
                            bool(msg.get('reactions')),
                            text.count('<@'),
                            text.count('<http://') + text.count('<https://'),
                            msg.get('permalink'),
                            False,
                            datetime.fromtimestamp(float(msg['edited']['ts']), tz=timezone.utc)
                                if isinstance(msg.get('edited'), dict) and msg['edited'].get('ts') else None,
                            created_at,
                        ),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        ts_to_message_id[slack_ts] = row[0]
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error storing message_metadata batch: {e}", exc_info=True)
        finally:
            DatabaseConnection.return_connection(conn)

        # Now build the pgvector batch with message_id wired in.
        batch = []
        for msg in messages:
            user_id = msg.get("user", "unknown")
            user_name = user_map.get(user_id, "unknown")
            slack_ts = msg["ts"]

            batch.append({
                'text': msg["text"],
                'slack_ts': slack_ts,
                'message_id': ts_to_message_id.get(slack_ts),
                'metadata': {
                    'channel_id': channel_id,
                    'channel_name': channel_name,
                    'user_id': user_id,
                    'user_name': user_name,
                    'timestamp': slack_ts,
                }
            })

        try:
            self.pgvector.add_messages_batch(self.workspace_id, batch)
            logger.debug(f"Stored {len(messages)} messages in pgvector + metadata")
        except Exception as e:
            logger.error(f"Error storing in pgvector: {e}", exc_info=True)

    async def _get_user_info(self, user_ids: List[str]) -> Dict[str, str]:
        """
        Get user display names from Slack API

        Args:
            user_ids: List of user IDs

        Returns:
            Dict mapping user_id -> display_name
        """
        user_map = {}

        # Remove duplicates and None values
        unique_user_ids = set([uid for uid in user_ids if uid])

        for user_id in unique_user_ids:
            try:
                response = await self.slack_client.users_info(user=user_id)
                user = response.get("user", {})

                # Try display_name first, fallback to real_name
                display_name = (
                    user.get("profile", {}).get("display_name") or
                    user.get("profile", {}).get("real_name") or
                    user.get("name") or
                    user_id
                )

                user_map[user_id] = display_name

            except SlackApiError:
                # User might be deleted or not accessible
                user_map[user_id] = f"user_{user_id[:8]}"

        return user_map
