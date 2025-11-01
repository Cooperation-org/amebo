"""
Channel repository for database operations.
"""

import logging
from typing import Dict, List, Optional
from psycopg2 import extras
from datetime import datetime

logger = logging.getLogger(__name__)


class ChannelRepository:
    """
    Handles database operations for channels.
    """

    def __init__(self, db_connection):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
        """
        self.conn = db_connection

    def upsert_channel(self, channel: Dict) -> str:
        """
        Insert or update a channel.

        Args:
            channel: Channel dict from Slack API

        Returns:
            channel_id
        """
        query = """
            INSERT INTO channels (
                channel_id, channel_name, is_private, is_archived, is_general,
                purpose, topic, member_count, creator_id, created_at
            ) VALUES (
                %(channel_id)s, %(channel_name)s, %(is_private)s, %(is_archived)s, %(is_general)s,
                %(purpose)s, %(topic)s, %(member_count)s, %(creator_id)s, %(created_at)s
            )
            ON CONFLICT (channel_id) DO UPDATE SET
                channel_name = EXCLUDED.channel_name,
                is_archived = EXCLUDED.is_archived,
                purpose = EXCLUDED.purpose,
                topic = EXCLUDED.topic,
                member_count = EXCLUDED.member_count
            RETURNING channel_id
        """

        params = {
            'channel_id': channel['id'],
            'channel_name': channel['name'],
            'is_private': channel.get('is_private', False),
            'is_archived': channel.get('is_archived', False),
            'is_general': channel.get('is_general', False),
            'purpose': channel.get('purpose', {}).get('value', ''),
            'topic': channel.get('topic', {}).get('value', ''),
            'member_count': channel.get('num_members', 0),
            'creator_id': channel.get('creator'),
            'created_at': datetime.fromtimestamp(channel['created']) if 'created' in channel else None
        }

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                channel_id = cur.fetchone()[0]
                self.conn.commit()
                return channel_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to upsert channel {channel.get('id')}: {e}")
            raise

    def update_last_sync(self, channel_id: str, last_message_ts: Optional[str] = None):
        """
        Update channel's last sync timestamp.

        Args:
            channel_id: Channel ID
            last_message_ts: Latest message timestamp
        """
        query = """
            UPDATE channels
            SET last_sync = NOW(), last_message_ts = COALESCE(%s, last_message_ts)
            WHERE channel_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (last_message_ts, channel_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update last sync for {channel_id}: {e}")
            raise

    def get_channels_to_sync(self) -> List[Dict]:
        """
        Get all channels that are enabled for syncing.

        Returns:
            List of channel dicts
        """
        query = """
            SELECT * FROM channels
            WHERE sync_enabled = true AND is_archived = false
            ORDER BY last_sync ASC NULLS FIRST
        """

        try:
            with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Failed to fetch channels to sync: {e}")
            raise

    def get_channel(self, channel_id: str) -> Optional[Dict]:
        """
        Get a channel by ID.

        Args:
            channel_id: Channel ID

        Returns:
            Channel dict or None
        """
        query = "SELECT * FROM channels WHERE channel_id = %s"

        try:
            with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (channel_id,))
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Failed to fetch channel {channel_id}: {e}")
            raise
