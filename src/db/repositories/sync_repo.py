"""
Sync status repository for tracking backfill progress.
"""

import logging
from typing import Dict, Optional
from psycopg2 import extras
from datetime import datetime

logger = logging.getLogger(__name__)


class SyncRepository:
    """
    Handles database operations for sync status tracking.
    """

    def __init__(self, db_connection):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
        """
        self.conn = db_connection

    def start_sync(self, channel_id: str, sync_type: str = 'backfill') -> int:
        """
        Create a new sync record and mark as running.

        Args:
            channel_id: Channel ID
            sync_type: Type of sync (backfill, incremental, realtime)

        Returns:
            sync_id
        """
        query = """
            INSERT INTO sync_status (
                channel_id, status, sync_type, sync_started_at
            ) VALUES (
                %s, 'running', %s, NOW()
            )
            RETURNING sync_id
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (channel_id, sync_type))
                sync_id = cur.fetchone()[0]
                self.conn.commit()
                return sync_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to start sync for {channel_id}: {e}")
            raise

    def update_sync_progress(
        self,
        sync_id: int,
        messages_synced: int,
        last_message_ts: Optional[str] = None,
        oldest_message_ts: Optional[str] = None
    ):
        """
        Update sync progress.

        Args:
            sync_id: Sync ID
            messages_synced: Number of messages synced so far
            last_message_ts: Latest message timestamp processed
            oldest_message_ts: Oldest message timestamp processed
        """
        query = """
            UPDATE sync_status
            SET messages_synced = %s,
                last_message_ts = COALESCE(%s, last_message_ts),
                oldest_message_ts = COALESCE(%s, oldest_message_ts)
            WHERE sync_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (messages_synced, last_message_ts, oldest_message_ts, sync_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update sync progress for {sync_id}: {e}")
            raise

    def complete_sync(self, sync_id: int, total_messages: int):
        """
        Mark sync as completed.

        Args:
            sync_id: Sync ID
            total_messages: Total messages synced
        """
        query = """
            UPDATE sync_status
            SET status = 'completed',
                messages_synced = %s,
                total_messages = %s,
                sync_completed_at = NOW()
            WHERE sync_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (total_messages, total_messages, sync_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to complete sync {sync_id}: {e}")
            raise

    def fail_sync(self, sync_id: int, error_message: str):
        """
        Mark sync as failed.

        Args:
            sync_id: Sync ID
            error_message: Error description
        """
        query = """
            UPDATE sync_status
            SET status = 'failed',
                error_message = %s
            WHERE sync_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (error_message, sync_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to mark sync {sync_id} as failed: {e}")
            raise

    def get_last_sync(self, channel_id: str) -> Optional[Dict]:
        """
        Get the most recent sync record for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            Sync status dict or None
        """
        query = """
            SELECT * FROM sync_status
            WHERE channel_id = %s
            ORDER BY sync_started_at DESC
            LIMIT 1
        """

        try:
            with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (channel_id,))
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Failed to fetch last sync for {channel_id}: {e}")
            raise

    def get_sync_summary(self) -> Dict:
        """
        Get summary of all sync operations.

        Returns:
            Dict with sync statistics
        """
        query = """
            SELECT
                COUNT(*) as total_syncs,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                COUNT(CASE WHEN status = 'running' THEN 1 END) as running,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                SUM(messages_synced) as total_messages_synced
            FROM sync_status
        """

        try:
            with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query)
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Failed to fetch sync summary: {e}")
            raise
