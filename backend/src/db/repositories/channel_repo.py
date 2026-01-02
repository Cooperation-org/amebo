"""
Channel repository for database operations.
"""

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ChannelRepository:
    """
    Handles database operations for channels.
    """

    def __init__(self, db_connection, workspace_id: str = None):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
            workspace_id: Workspace ID for multi-tenant isolation (optional for compatibility)
        """
        self.conn = db_connection
        self.workspace_id = workspace_id

    def upsert_channel(self, channel: Dict, workspace_id: str = None) -> None:
        """
        Insert or update channel metadata.

        Args:
            channel: Channel dict from Slack API
            workspace_id: Optional workspace ID (uses instance workspace_id if not provided)
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            INSERT INTO channels (
                workspace_id, channel_id, channel_name, is_private, is_archived,
                is_general, purpose, topic, member_count, creator_id, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                channel_name = EXCLUDED.channel_name,
                is_archived = EXCLUDED.is_archived,
                purpose = EXCLUDED.purpose,
                topic = EXCLUDED.topic,
                member_count = EXCLUDED.member_count
        """

        # Extract values from channel dict
        channel_id = channel.get('id')
        channel_name = channel.get('name', '')
        is_private = channel.get('is_private', False)
        is_archived = channel.get('is_archived', False)
        is_general = channel.get('is_general', False)
        purpose = channel.get('purpose', {}).get('value', '')
        topic = channel.get('topic', {}).get('value', '')
        member_count = channel.get('num_members', 0)
        creator_id = channel.get('creator', '')

        # Convert Slack timestamp to datetime if available
        created_ts = channel.get('created', 0)
        created_at = datetime.fromtimestamp(created_ts) if created_ts else datetime.now()

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (
                    ws_id, channel_id, channel_name, is_private, is_archived,
                    is_general, purpose, topic, member_count, creator_id, created_at
                ))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to upsert channel {channel_id}: {e}")
            raise

    def get_channel(self, channel_id: str, workspace_id: str = None) -> Optional[Dict]:
        """
        Get channel by ID.

        Args:
            channel_id: Channel ID
            workspace_id: Optional workspace ID

        Returns:
            Channel dict or None
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            SELECT channel_id, channel_name, is_private, is_archived, is_general,
                   purpose, topic, member_count, creator_id, last_message_ts,
                   created_at, last_sync, sync_enabled
            FROM channels
            WHERE workspace_id = %s AND channel_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (ws_id, channel_id))
                row = cur.fetchone()

                if row:
                    return {
                        'channel_id': row[0],
                        'channel_name': row[1],
                        'is_private': row[2],
                        'is_archived': row[3],
                        'is_general': row[4],
                        'purpose': row[5],
                        'topic': row[6],
                        'member_count': row[7],
                        'creator_id': row[8],
                        'last_message_ts': row[9],
                        'created_at': row[10],
                        'last_sync': row[11],
                        'sync_enabled': row[12]
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get channel {channel_id}: {e}")
            raise

    def update_last_sync(self, channel_id: str, last_message_ts: str = None, workspace_id: str = None):
        """
        Update the last sync timestamp for a channel.

        Args:
            channel_id: Channel ID
            last_message_ts: Last message timestamp synced
            workspace_id: Optional workspace ID
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            UPDATE channels
            SET last_sync = NOW(),
                last_message_ts = COALESCE(%s, last_message_ts)
            WHERE workspace_id = %s AND channel_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (last_message_ts, ws_id, channel_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update last sync for channel {channel_id}: {e}")
            raise

    def list_channels(self, workspace_id: str = None, include_archived: bool = False):
        """
        List all channels for a workspace.

        Args:
            workspace_id: Optional workspace ID
            include_archived: Whether to include archived channels

        Returns:
            List of channel dicts
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            SELECT channel_id, channel_name, is_private, is_archived, member_count
            FROM channels
            WHERE workspace_id = %s
        """

        params = [ws_id]

        if not include_archived:
            query += " AND is_archived = false"

        query += " ORDER BY channel_name"

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

                return [
                    {
                        'channel_id': row[0],
                        'channel_name': row[1],
                        'is_private': row[2],
                        'is_archived': row[3],
                        'member_count': row[4]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to list channels: {e}")
            raise
