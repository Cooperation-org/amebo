#!/usr/bin/env python3
"""
Backfill script with PostgreSQL + ChromaDB hybrid architecture.

Usage:
    python scripts/backfill_chromadb.py --all --workspace W_DEFAULT
    python scripts/backfill_chromadb.py --channels C123,C456 --workspace W_DEFAULT
    python scripts/backfill_chromadb.py --days 7 --workspace W_DEFAULT
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Optional

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.collector.slack_client import SlackClient
from src.collector.processors.message_processor import MessageProcessor
from src.db.connection import DatabaseConnection
from src.db.repositories.message_repo import MessageRepository
from src.db.chromadb_client import ChromaDBClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HybridBackfillService:
    """
    Service to backfill Slack messages to PostgreSQL + ChromaDB.
    """

    def __init__(self, workspace_id: str):
        """
        Initialize backfill service.

        Args:
            workspace_id: Workspace ID for multi-tenant
        """
        self.workspace_id = workspace_id
        self.slack_client = SlackClient()
        self.processor = MessageProcessor()
        self.chromadb_client = ChromaDBClient()

        DatabaseConnection.initialize_pool()

        logger.info(f"Hybrid backfill service initialized for workspace: {workspace_id}")

    def sync_all_channels(self, days_back: Optional[int] = None):
        """
        Sync all channels the bot is a member of.

        Args:
            days_back: Only sync messages from last N days (None = all history)
        """
        logger.info("Fetching channel list...")
        channels = self.slack_client.get_channel_list()

        # Filter to only channels bot is a member of
        member_channels = [ch for ch in channels if ch.get('is_member', False)]

        logger.info(f"Found {len(member_channels)} channels where bot is a member")

        for i, channel in enumerate(member_channels, 1):
            logger.info(f"\n[{i}/{len(member_channels)}] Processing channel: #{channel['name']}")
            try:
                self.sync_channel(channel, days_back=days_back)
            except Exception as e:
                logger.error(f"Failed to sync channel {channel['name']}: {e}")
                continue

    def sync_channel(self, channel: dict, days_back: Optional[int] = None):
        """
        Sync a single channel's history to both PostgreSQL and ChromaDB.

        Args:
            channel: Channel dict from Slack API
            days_back: Only sync messages from last N days
        """
        channel_id = channel['id']
        channel_name = channel['name']

        conn = DatabaseConnection.get_connection()
        message_repo = MessageRepository(conn, self.workspace_id)

        # Upsert channel
        self._upsert_channel(conn, channel)

        # Start sync tracking
        sync_id = self._start_sync(conn, channel_id)

        # Calculate oldest timestamp if days_back is specified
        oldest_ts = None
        if days_back:
            oldest_dt = datetime.now() - timedelta(days=days_back)
            oldest_ts = str(oldest_dt.timestamp())
            logger.info(f"  Only syncing messages from last {days_back} days")

        try:
            messages_synced = 0
            last_ts = None
            oldest_synced_ts = None
            user_cache = set()

            logger.info(f"  Fetching messages...")

            for message in self.slack_client.get_channel_history(
                channel_id,
                oldest=oldest_ts,
                limit=100
            ):
                # Split message into metadata and content
                metadata, content = self._split_message(message, channel_id, channel_name)

                # 1. Insert metadata into PostgreSQL
                message_id = message_repo.upsert_message(metadata)

                # 2. Insert content into ChromaDB
                chromadb_id = self.chromadb_client.add_message(
                    workspace_id=self.workspace_id,
                    message_id=message_id,
                    slack_ts=message['ts'],
                    message_text=content['text'],
                    metadata=content['metadata']
                )

                # 3. Update PostgreSQL with ChromaDB reference
                message_repo.update_chromadb_id(message_id, chromadb_id)

                # 4. Insert reactions, links, files
                reactions = self.processor.extract_reactions(message)
                if reactions:
                    message_repo.insert_reactions(message_id, reactions)

                links = self.processor.extract_links(
                    message.get('text', ''),
                    message.get('attachments', [])
                )
                if links:
                    message_repo.insert_links(message_id, links)

                files = self.processor.extract_files(message)
                if files:
                    message_repo.insert_files(message_id, files)

                # 5. Cache user if not already cached
                user_id = message.get('user')
                if user_id and user_id not in user_cache:
                    try:
                        user_info = self.slack_client.get_user_info(user_id)
                        self._upsert_user(conn, user_info)
                        user_cache.add(user_id)
                    except Exception as e:
                        logger.warning(f"  Failed to fetch user {user_id}: {e}")

                # 6. If thread parent, fetch replies
                if self.processor.is_thread_parent(message):
                    self._sync_thread_replies(
                        channel_id, channel_name, message['ts'],
                        message_repo, user_cache
                    )

                messages_synced += 1
                last_ts = message['ts']
                if oldest_synced_ts is None:
                    oldest_synced_ts = message['ts']

                # Update progress every 50 messages
                if messages_synced % 50 == 0:
                    self._update_sync_progress(conn, sync_id, messages_synced, last_ts, oldest_synced_ts)
                    logger.info(f"  Progress: {messages_synced} messages synced")

            # Complete sync
            logger.info(f"  ✅ Synced {messages_synced} messages from #{channel_name}")
            self._complete_sync(conn, sync_id, messages_synced)
            self._update_channel_sync(conn, channel_id, last_ts)

        except Exception as e:
            logger.error(f"  ❌ Error syncing channel: {e}")
            self._fail_sync(conn, sync_id, str(e))
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def _split_message(self, message: dict, channel_id: str, channel_name: str):
        """
        Split message into metadata (PostgreSQL) and content (ChromaDB).

        Returns:
            (metadata_dict, content_dict)
        """
        # Metadata for PostgreSQL (no text content)
        metadata = {
            'slack_ts': message.get('ts'),
            'channel_id': channel_id,
            'channel_name': channel_name,
            'user_id': message.get('user', message.get('bot_id', 'UNKNOWN')),
            'user_name': message.get('username', ''),
            'message_type': self.processor._determine_message_type(message),
            'thread_ts': message.get('thread_ts'),
            'reply_count': message.get('reply_count', 0),
            'reply_users_count': message.get('reply_users_count', 0),
            'has_attachments': bool(message.get('attachments')),
            'has_files': bool(message.get('files')),
            'has_reactions': bool(message.get('reactions')),
            'mention_count': len(self.processor.extract_mentions(message.get('text', ''))),
            'link_count': len(self.processor.extract_links(message.get('text', ''), message.get('attachments', []))),
            'permalink': message.get('permalink', ''),
            'is_pinned': bool(message.get('pinned_to', [])),
            'edited_at': self.processor._parse_edited_ts(message),
            'created_at': self.processor._parse_timestamp(message.get('ts')),
            'chromadb_id': None  # Will be updated after ChromaDB insert
        }

        # Content for ChromaDB
        content = {
            'text': message.get('text', ''),
            'metadata': {
                'channel_id': channel_id,
                'channel_name': channel_name,
                'user_id': message.get('user', ''),
                'user_name': message.get('username', ''),
                'timestamp': message.get('ts'),
                'thread_ts': message.get('thread_ts', ''),
                'message_type': metadata['message_type']
            }
        }

        return metadata, content

    def _sync_thread_replies(
        self,
        channel_id: str,
        channel_name: str,
        thread_ts: str,
        message_repo: MessageRepository,
        user_cache: set
    ):
        """
        Sync replies in a thread.
        """
        try:
            replies = self.slack_client.get_thread_replies(channel_id, thread_ts)

            for reply in replies:
                metadata, content = self._split_message(reply, channel_id, channel_name)

                # Insert to PostgreSQL
                message_id = message_repo.upsert_message(metadata)

                # Insert to ChromaDB
                chromadb_id = self.chromadb_client.add_message(
                    workspace_id=self.workspace_id,
                    message_id=message_id,
                    slack_ts=reply['ts'],
                    message_text=content['text'],
                    metadata=content['metadata']
                )

                message_repo.update_chromadb_id(message_id, chromadb_id)

                # Reactions, links, files
                reactions = self.processor.extract_reactions(reply)
                if reactions:
                    message_repo.insert_reactions(message_id, reactions)

                links = self.processor.extract_links(reply.get('text', ''), reply.get('attachments', []))
                if links:
                    message_repo.insert_links(message_id, links)

                files = self.processor.extract_files(reply)
                if files:
                    message_repo.insert_files(message_id, files)

                # User
                user_id = reply.get('user')
                if user_id and user_id not in user_cache:
                    try:
                        user_info = self.slack_client.get_user_info(user_id)
                        conn = message_repo.conn
                        self._upsert_user(conn, user_info)
                        user_cache.add(user_id)
                    except Exception as e:
                        logger.warning(f"    Failed to fetch user {user_id}: {e}")

        except Exception as e:
            logger.warning(f"  Failed to sync thread {thread_ts}: {e}")

    # Helper methods for PostgreSQL operations
    def _upsert_channel(self, conn, channel: dict):
        """Upsert channel to PostgreSQL."""
        query = """
            INSERT INTO channels (
                workspace_id, channel_id, channel_name, is_private, is_archived, is_general,
                purpose, topic, member_count, creator_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                channel_name = EXCLUDED.channel_name,
                is_archived = EXCLUDED.is_archived,
                member_count = EXCLUDED.member_count
        """
        with conn.cursor() as cur:
            cur.execute(query, (
                self.workspace_id,
                channel['id'],
                channel['name'],
                channel.get('is_private', False),
                channel.get('is_archived', False),
                channel.get('is_general', False),
                channel.get('purpose', {}).get('value', ''),
                channel.get('topic', {}).get('value', ''),
                channel.get('num_members', 0),
                channel.get('creator'),
                datetime.fromtimestamp(channel['created']) if 'created' in channel else None
            ))
            conn.commit()

    def _upsert_user(self, conn, user: dict):
        """Upsert user to PostgreSQL."""
        profile = user.get('profile', {})
        query = """
            INSERT INTO users (
                workspace_id, user_id, user_name, real_name, display_name, email,
                title, is_bot, is_admin, timezone, avatar_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (workspace_id, user_id) DO UPDATE SET
                user_name = EXCLUDED.user_name,
                real_name = EXCLUDED.real_name,
                updated_at = NOW()
        """
        with conn.cursor() as cur:
            cur.execute(query, (
                self.workspace_id,
                user['id'],
                user.get('name', ''),
                user.get('real_name', profile.get('real_name', '')),
                profile.get('display_name', ''),
                profile.get('email', ''),
                profile.get('title', ''),
                user.get('is_bot', False),
                user.get('is_admin', False),
                user.get('tz', ''),
                profile.get('image_512', '')
            ))
            conn.commit()

    def _start_sync(self, conn, channel_id: str) -> int:
        """Start sync tracking."""
        query = """
            INSERT INTO sync_status (workspace_id, channel_id, status, sync_type, sync_started_at)
            VALUES (%s, %s, 'running', 'backfill', NOW())
            RETURNING sync_id
        """
        with conn.cursor() as cur:
            cur.execute(query, (self.workspace_id, channel_id))
            sync_id = cur.fetchone()[0]
            conn.commit()
            return sync_id

    def _update_sync_progress(self, conn, sync_id: int, messages_synced: int, last_ts: str, oldest_ts: str):
        """Update sync progress."""
        query = """
            UPDATE sync_status
            SET messages_synced = %s, last_message_ts = %s, oldest_message_ts = %s
            WHERE sync_id = %s
        """
        with conn.cursor() as cur:
            cur.execute(query, (messages_synced, last_ts, oldest_ts, sync_id))
            conn.commit()

    def _complete_sync(self, conn, sync_id: int, total: int):
        """Mark sync as completed."""
        query = """
            UPDATE sync_status
            SET status = 'completed', messages_synced = %s, total_messages = %s, sync_completed_at = NOW()
            WHERE sync_id = %s
        """
        with conn.cursor() as cur:
            cur.execute(query, (total, total, sync_id))
            conn.commit()

    def _fail_sync(self, conn, sync_id: int, error_msg: str):
        """Mark sync as failed."""
        query = """
            UPDATE sync_status
            SET status = 'failed', error_message = %s
            WHERE sync_id = %s
        """
        with conn.cursor() as cur:
            cur.execute(query, (error_msg, sync_id))
            conn.commit()

    def _update_channel_sync(self, conn, channel_id: str, last_ts: str):
        """Update channel last sync."""
        query = """
            UPDATE channels
            SET last_sync = NOW(), last_message_ts = %s
            WHERE workspace_id = %s AND channel_id = %s
        """
        with conn.cursor() as cur:
            cur.execute(query, (last_ts, self.workspace_id, channel_id))
            conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description='Backfill Slack messages to PostgreSQL + ChromaDB'
    )
    parser.add_argument(
        '--workspace',
        type=str,
        required=True,
        help='Workspace ID (e.g., W_DEFAULT)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Sync all channels bot is a member of'
    )
    parser.add_argument(
        '--channels',
        type=str,
        help='Comma-separated list of channel IDs to sync'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=None,
        help='Only sync messages from last N days (default: all history)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.all and not args.channels:
        parser.error("Must specify either --all or --channels")

    # Initialize service
    service = HybridBackfillService(workspace_id=args.workspace)

    try:
        if args.all:
            logger.info("=" * 60)
            logger.info(f"Starting backfill for workspace: {args.workspace}")
            if args.days:
                logger.info(f"Syncing messages from last {args.days} days")
            else:
                logger.info("Syncing all available message history")
            logger.info("=" * 60)

            service.sync_all_channels(days_back=args.days)

            logger.info("=" * 60)
            logger.info("✅ Backfill completed successfully!")
            logger.info("=" * 60)

        elif args.channels:
            channel_ids = [ch.strip() for ch in args.channels.split(',')]
            logger.info(f"Syncing {len(channel_ids)} specific channels")

            for channel_id in channel_ids:
                try:
                    logger.info(f"Fetching channel info for {channel_id}...")
                    channel = service.slack_client.get_channel_info(channel_id)
                    service.sync_channel(channel, days_back=args.days)
                except Exception as e:
                    logger.error(f"Failed to sync channel {channel_id}: {e}")
                    continue

            logger.info("✅ Channel sync completed!")

    except KeyboardInterrupt:
        logger.info("\n⚠️  Backfill interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    main()
