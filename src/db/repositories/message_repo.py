"""
Message repository for database operations.
"""

import logging
from typing import Dict, List, Optional
from psycopg2 import extras
import json

logger = logging.getLogger(__name__)


class MessageRepository:
    """
    Handles database operations for messages and related data.
    """

    def __init__(self, db_connection):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
        """
        self.conn = db_connection

    def upsert_message(self, message: Dict) -> int:
        """
        Insert or update a message.

        Args:
            message: Message dict

        Returns:
            message_id
        """
        query = """
            INSERT INTO messages (
                slack_ts, channel_id, channel_name, user_id, user_name,
                message_text, message_type, thread_ts, reply_count, reply_users_count,
                attachments, mentions, blocks, permalink, is_pinned,
                edited_at, created_at, raw_data
            ) VALUES (
                %(slack_ts)s, %(channel_id)s, %(channel_name)s, %(user_id)s, %(user_name)s,
                %(message_text)s, %(message_type)s, %(thread_ts)s, %(reply_count)s, %(reply_users_count)s,
                %(attachments)s, %(mentions)s, %(blocks)s, %(permalink)s, %(is_pinned)s,
                %(edited_at)s, %(created_at)s, %(raw_data)s
            )
            ON CONFLICT (slack_ts) DO UPDATE SET
                message_text = EXCLUDED.message_text,
                reply_count = EXCLUDED.reply_count,
                reply_users_count = EXCLUDED.reply_users_count,
                edited_at = EXCLUDED.edited_at,
                raw_data = EXCLUDED.raw_data
            RETURNING message_id
        """

        # Convert lists/dicts to JSON strings for JSONB columns
        params = message.copy()
        for key in ['attachments', 'mentions', 'blocks', 'raw_data']:
            if key in params and params[key] is not None:
                params[key] = json.dumps(params[key])

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                message_id = cur.fetchone()[0]
                self.conn.commit()
                return message_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to upsert message {message.get('slack_ts')}: {e}")
            raise

    def insert_reactions(self, message_id: int, reactions: List[Dict]):
        """
        Insert reactions for a message (bulk insert).

        Args:
            message_id: Message ID
            reactions: List of reaction dicts
        """
        if not reactions:
            return

        query = """
            INSERT INTO reactions (message_id, user_id, user_name, reaction_name, reacted_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (message_id, user_id, reaction_name) DO NOTHING
        """

        params_list = [
            (message_id, r['user_id'], r.get('user_name', ''), r['reaction_name'], r['reacted_at'])
            for r in reactions
        ]

        try:
            with self.conn.cursor() as cur:
                extras.execute_batch(cur, query, params_list)
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert reactions for message {message_id}: {e}")
            raise

    def insert_links(self, message_id: int, links: List[Dict]):
        """
        Insert links extracted from a message.

        Args:
            message_id: Message ID
            links: List of link dicts
        """
        if not links:
            return

        query = """
            INSERT INTO links (message_id, url, link_type, domain, title, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """

        params_list = [
            (message_id, link['url'], link['link_type'], link['domain'],
             link.get('title'), link.get('description'))
            for link in links
        ]

        try:
            with self.conn.cursor() as cur:
                extras.execute_batch(cur, query, params_list)
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert links for message {message_id}: {e}")
            raise

    def insert_files(self, message_id: int, files: List[Dict]):
        """
        Insert file metadata.

        Args:
            message_id: Message ID
            files: List of file dicts
        """
        if not files:
            return

        query = """
            INSERT INTO files (
                slack_file_id, message_id, file_name, file_type, file_size,
                mime_type, url_private, url_private_download, permalink,
                uploaded_by, uploaded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (slack_file_id) DO UPDATE SET
                message_id = EXCLUDED.message_id
        """

        params_list = [
            (
                f['slack_file_id'], message_id, f['file_name'], f['file_type'],
                f['file_size'], f['mime_type'], f['url_private'],
                f['url_private_download'], f['permalink'], f['uploaded_by'],
                f['uploaded_at']
            )
            for f in files
        ]

        try:
            with self.conn.cursor() as cur:
                extras.execute_batch(cur, query, params_list)
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert files for message {message_id}: {e}")
            raise

    def get_message_by_slack_ts(self, slack_ts: str) -> Optional[Dict]:
        """
        Get message by Slack timestamp.

        Args:
            slack_ts: Slack timestamp

        Returns:
            Message dict or None
        """
        query = "SELECT * FROM messages WHERE slack_ts = %s"

        try:
            with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (slack_ts,))
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Failed to fetch message {slack_ts}: {e}")
            raise

    def get_messages_count(self, channel_id: Optional[str] = None) -> int:
        """
        Get total message count, optionally filtered by channel.

        Args:
            channel_id: Optional channel ID filter

        Returns:
            Message count
        """
        if channel_id:
            query = "SELECT COUNT(*) FROM messages WHERE channel_id = %s AND deleted_at IS NULL"
            params = (channel_id,)
        else:
            query = "SELECT COUNT(*) FROM messages WHERE deleted_at IS NULL"
            params = None

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to get message count: {e}")
            raise
