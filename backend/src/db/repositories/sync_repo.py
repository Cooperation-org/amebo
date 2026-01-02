"""
Sync status repository for tracking sync operations.
"""

import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SyncRepository:
    """
    Handles database operations for sync status tracking.
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

    def start_sync(self, channel_id: str, sync_type: str = 'backfill', workspace_id: str = None) -> int:
        """
        Start a new sync operation.

        Args:
            channel_id: Channel ID to sync
            sync_type: Type of sync ('backfill', 'incremental', 'realtime')
            workspace_id: Optional workspace ID

        Returns:
            sync_id
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            INSERT INTO sync_status (
                workspace_id, channel_id, sync_type, status, sync_started_at
            ) VALUES (
                %s, %s, %s, 'running', NOW()
            )
            RETURNING sync_id
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (ws_id, channel_id, sync_type))
                sync_id = cur.fetchone()[0]
                self.conn.commit()
                return sync_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to start sync for channel {channel_id}: {e}")
            raise

    def update_sync_progress(
        self,
        sync_id: int,
        messages_synced: int,
        last_message_ts: str = None,
        oldest_message_ts: str = None
    ):
        """
        Update sync progress.

        Args:
            sync_id: Sync ID
            messages_synced: Number of messages synced so far
            last_message_ts: Latest message timestamp synced
            oldest_message_ts: Oldest message timestamp synced
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
            logger.error(f"Failed to update sync progress for sync {sync_id}: {e}")
            raise

    def complete_sync(self, sync_id: int, total_messages: int = None):
        """
        Mark sync as completed.

        Args:
            sync_id: Sync ID
            total_messages: Total number of messages synced
        """
        query = """
            UPDATE sync_status
            SET status = 'completed',
                sync_completed_at = NOW(),
                total_messages = COALESCE(%s, messages_synced)
            WHERE sync_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (total_messages, sync_id))
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
            error_message: Error message
        """
        query = """
            UPDATE sync_status
            SET status = 'failed',
                sync_completed_at = NOW(),
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

    def get_sync_status(self, sync_id: int):
        """
        Get sync status by ID.

        Args:
            sync_id: Sync ID

        Returns:
            Sync status dict or None
        """
        query = """
            SELECT sync_id, workspace_id, channel_id, last_message_ts,
                   oldest_message_ts, messages_synced, total_messages,
                   sync_started_at, sync_completed_at, status,
                   error_message, sync_type
            FROM sync_status
            WHERE sync_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (sync_id,))
                row = cur.fetchone()

                if row:
                    return {
                        'sync_id': row[0],
                        'workspace_id': row[1],
                        'channel_id': row[2],
                        'last_message_ts': row[3],
                        'oldest_message_ts': row[4],
                        'messages_synced': row[5],
                        'total_messages': row[6],
                        'sync_started_at': row[7],
                        'sync_completed_at': row[8],
                        'status': row[9],
                        'error_message': row[10],
                        'sync_type': row[11]
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get sync status {sync_id}: {e}")
            raise

    def get_latest_sync_for_channel(self, channel_id: str, workspace_id: str = None):
        """
        Get the latest sync for a channel.

        Args:
            channel_id: Channel ID
            workspace_id: Optional workspace ID

        Returns:
            Sync status dict or None
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            SELECT sync_id, workspace_id, channel_id, last_message_ts,
                   oldest_message_ts, messages_synced, total_messages,
                   sync_started_at, sync_completed_at, status,
                   error_message, sync_type
            FROM sync_status
            WHERE workspace_id = %s AND channel_id = %s
            ORDER BY sync_started_at DESC
            LIMIT 1
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (ws_id, channel_id))
                row = cur.fetchone()

                if row:
                    return {
                        'sync_id': row[0],
                        'workspace_id': row[1],
                        'channel_id': row[2],
                        'last_message_ts': row[3],
                        'oldest_message_ts': row[4],
                        'messages_synced': row[5],
                        'total_messages': row[6],
                        'sync_started_at': row[7],
                        'sync_completed_at': row[8],
                        'status': row[9],
                        'error_message': row[10],
                        'sync_type': row[11]
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get latest sync for channel {channel_id}: {e}")
            raise
