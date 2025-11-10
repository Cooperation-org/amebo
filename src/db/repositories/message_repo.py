"""
Message metadata repository for database operations.
NOTE: Message TEXT content is stored in ChromaDB, not PostgreSQL.
"""

import logging
from typing import Dict, List, Optional
from psycopg2 import extras

logger = logging.getLogger(__name__)


class MessageRepository:
    """
    Handles database operations for message metadata (NOT content).
    """

    def __init__(self, db_connection, workspace_id: str):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
            workspace_id: Workspace ID for multi-tenant isolation
        """
        self.conn = db_connection
        self.workspace_id = workspace_id

    def upsert_message(self, message: Dict) -> int:
        """
        Insert or update message metadata.

        Args:
            message: Message metadata dict (NO message_text field)

        Returns:
            message_id
        """
        query = """
            INSERT INTO message_metadata (
                workspace_id, slack_ts, channel_id, channel_name, user_id, user_name,
                message_type, thread_ts, reply_count, reply_users_count,
                has_attachments, has_files, has_reactions, mention_count, link_count,
                permalink, is_pinned, edited_at, created_at, chromadb_id
            ) VALUES (
                %(workspace_id)s, %(slack_ts)s, %(channel_id)s, %(channel_name)s, %(user_id)s, %(user_name)s,
                %(message_type)s, %(thread_ts)s, %(reply_count)s, %(reply_users_count)s,
                %(has_attachments)s, %(has_files)s, %(has_reactions)s, %(mention_count)s, %(link_count)s,
                %(permalink)s, %(is_pinned)s, %(edited_at)s, %(created_at)s, %(chromadb_id)s
            )
            ON CONFLICT (workspace_id, slack_ts) DO UPDATE SET
                reply_count = EXCLUDED.reply_count,
                reply_users_count = EXCLUDED.reply_users_count,
                has_reactions = EXCLUDED.has_reactions,
                edited_at = EXCLUDED.edited_at,
                chromadb_id = EXCLUDED.chromadb_id
            RETURNING message_id
        """

        params = message.copy()
        params['workspace_id'] = self.workspace_id

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
            INSERT INTO reactions (workspace_id, message_id, user_id, user_name, reaction_name, reacted_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (workspace_id, message_id, user_id, reaction_name) DO NOTHING
        """

        params_list = [
            (self.workspace_id, message_id, r['user_id'], r.get('user_name', ''), r['reaction_name'], r['reacted_at'])
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
            INSERT INTO links (workspace_id, message_id, url, link_type, domain, title, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """

        params_list = [
            (self.workspace_id, message_id, link['url'], link['link_type'], link['domain'],
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
                workspace_id, slack_file_id, message_id, file_name, file_type, file_size,
                mime_type, url_private, url_private_download, permalink,
                uploaded_by, uploaded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (workspace_id, slack_file_id) DO UPDATE SET
                message_id = EXCLUDED.message_id
        """

        params_list = [
            (
                self.workspace_id, f['slack_file_id'], message_id, f['file_name'], f['file_type'],
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

    def update_chromadb_id(self, message_id: int, chromadb_id: str):
        """
        Update the ChromaDB reference for a message.

        Args:
            message_id: Message ID
            chromadb_id: ChromaDB document ID
        """
        query = """
            UPDATE message_metadata
            SET chromadb_id = %s
            WHERE workspace_id = %s AND message_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (chromadb_id, self.workspace_id, message_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update chromadb_id for message {message_id}: {e}")
            raise
