#!/usr/bin/env python3
"""
Backfill script to sync historical Slack messages into the database.

Usage:
    python scripts/backfill.py --all                    # Sync all channels
    python scripts/backfill.py --channels C123,C456     # Sync specific channels
    python scripts/backfill.py --days 30                # Only sync last 30 days
    python scripts/backfill.py --dry-run                # Test without writing to DB
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
from src.db.repositories.channel_repo import ChannelRepository
from src.db.repositories.user_repo import UserRepository
from src.db.repositories.sync_repo import SyncRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BackfillService:
    """
    Service to backfill historical Slack messages.
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialize backfill service.

        Args:
            dry_run: If True, don't write to database
        """
        self.dry_run = dry_run
        self.slack_client = SlackClient()
        self.processor = MessageProcessor()

        if not dry_run:
            DatabaseConnection.initialize_pool()

        logger.info(f"Backfill service initialized (dry_run={dry_run})")

    def sync_all_channels(self, days_back: Optional[int] = None):
        """
        Sync all channels the bot is a member of.

        Args:
            days_back: Only sync messages from last N days (None = all history)
        """
        logger.info("Fetching channel list...")
        channels = self.slack_client.get_channel_list()

        logger.info(f"Found {len(channels)} channels to sync")

        for i, channel in enumerate(channels, 1):
            logger.info(f"\n[{i}/{len(channels)}] Processing channel: #{channel['name']}")
            try:
                self.sync_channel(channel, days_back=days_back)
            except Exception as e:
                logger.error(f"Failed to sync channel {channel['name']}: {e}")
                continue

    def sync_channel(self, channel: dict, days_back: Optional[int] = None):
        """
        Sync a single channel's history.

        Args:
            channel: Channel dict from Slack API
            days_back: Only sync messages from last N days
        """
        channel_id = channel['id']
        channel_name = channel['name']

        conn = None
        if not self.dry_run:
            conn = DatabaseConnection.get_connection()
            channel_repo = ChannelRepository(conn)
            message_repo = MessageRepository(conn)
            user_repo = UserRepository(conn)
            sync_repo = SyncRepository(conn)

            # Upsert channel
            channel_repo.upsert_channel(channel)

            # Start sync tracking
            sync_id = sync_repo.start_sync(channel_id, 'backfill')
        else:
            sync_id = None

        # Calculate oldest timestamp if days_back is specified
        oldest_ts = None
        if days_back:
            oldest_dt = datetime.now() - timedelta(days=days_back)
            oldest_ts = str(oldest_dt.timestamp())
            logger.info(f"  Only syncing messages from last {days_back} days")

        try:
            # Fetch messages
            messages_synced = 0
            last_ts = None
            oldest_synced_ts = None
            user_cache = set()  # Track users we've already cached

            logger.info(f"  Fetching messages...")

            for message in self.slack_client.get_channel_history(
                channel_id,
                oldest=oldest_ts,
                limit=100
            ):
                # Parse message
                parsed = self.processor.parse_message(message, channel_id, channel_name)

                if not self.dry_run:
                    # Insert message
                    message_id = message_repo.upsert_message(parsed)

                    # Extract and insert reactions
                    reactions = self.processor.extract_reactions(message)
                    if reactions:
                        message_repo.insert_reactions(message_id, reactions)

                    # Extract and insert links
                    links = self.processor.extract_links(
                        message.get('text', ''),
                        message.get('attachments', [])
                    )
                    if links:
                        message_repo.insert_links(message_id, links)

                    # Extract and insert files
                    files = self.processor.extract_files(message)
                    if files:
                        message_repo.insert_files(message_id, files)

                    # Cache user if not already cached
                    user_id = message.get('user')
                    if user_id and user_id not in user_cache:
                        try:
                            user_info = self.slack_client.get_user_info(user_id)
                            user_repo.upsert_user(user_info)
                            user_cache.add(user_id)
                        except Exception as e:
                            logger.warning(f"  Failed to fetch user {user_id}: {e}")

                    # If thread parent, fetch replies
                    if self.processor.is_thread_parent(message):
                        self._sync_thread_replies(
                            channel_id, channel_name, message['ts'],
                            message_repo, user_repo, user_cache
                        )

                messages_synced += 1
                last_ts = message['ts']
                if oldest_synced_ts is None:
                    oldest_synced_ts = message['ts']

                # Update progress every 100 messages
                if not self.dry_run and messages_synced % 100 == 0:
                    sync_repo.update_sync_progress(
                        sync_id, messages_synced, last_ts, oldest_synced_ts
                    )
                    logger.info(f"  Progress: {messages_synced} messages synced")

            # Complete sync
            logger.info(f"  ✅ Synced {messages_synced} messages from #{channel_name}")

            if not self.dry_run:
                sync_repo.complete_sync(sync_id, messages_synced)
                channel_repo.update_last_sync(channel_id, last_ts)

        except Exception as e:
            logger.error(f"  ❌ Error syncing channel: {e}")
            if not self.dry_run and sync_id:
                sync_repo.fail_sync(sync_id, str(e))
            raise
        finally:
            if conn:
                DatabaseConnection.return_connection(conn)

    def _sync_thread_replies(
        self,
        channel_id: str,
        channel_name: str,
        thread_ts: str,
        message_repo: MessageRepository,
        user_repo: UserRepository,
        user_cache: set
    ):
        """
        Sync replies in a thread.

        Args:
            channel_id: Channel ID
            channel_name: Channel name
            thread_ts: Thread parent timestamp
            message_repo: Message repository
            user_repo: User repository
            user_cache: Set of already cached user IDs
        """
        try:
            replies = self.slack_client.get_thread_replies(channel_id, thread_ts)

            for reply in replies:
                parsed = self.processor.parse_message(reply, channel_id, channel_name)
                message_id = message_repo.upsert_message(parsed)

                # Reactions
                reactions = self.processor.extract_reactions(reply)
                if reactions:
                    message_repo.insert_reactions(message_id, reactions)

                # Links
                links = self.processor.extract_links(
                    reply.get('text', ''),
                    reply.get('attachments', [])
                )
                if links:
                    message_repo.insert_links(message_id, links)

                # Files
                files = self.processor.extract_files(reply)
                if files:
                    message_repo.insert_files(message_id, files)

                # User
                user_id = reply.get('user')
                if user_id and user_id not in user_cache:
                    try:
                        user_info = self.slack_client.get_user_info(user_id)
                        user_repo.upsert_user(user_info)
                        user_cache.add(user_id)
                    except Exception as e:
                        logger.warning(f"    Failed to fetch user {user_id}: {e}")

        except Exception as e:
            logger.warning(f"  Failed to sync thread {thread_ts}: {e}")

    def sync_specific_channels(self, channel_ids: List[str], days_back: Optional[int] = None):
        """
        Sync specific channels by ID.

        Args:
            channel_ids: List of channel IDs
            days_back: Only sync messages from last N days
        """
        for channel_id in channel_ids:
            try:
                logger.info(f"Fetching channel info for {channel_id}...")
                channel = self.slack_client.get_channel_info(channel_id)
                self.sync_channel(channel, days_back=days_back)
            except Exception as e:
                logger.error(f"Failed to sync channel {channel_id}: {e}")
                continue


def main():
    parser = argparse.ArgumentParser(
        description='Backfill historical Slack messages into database'
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
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without writing to database (test mode)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.all and not args.channels:
        parser.error("Must specify either --all or --channels")

    # Initialize service
    service = BackfillService(dry_run=args.dry_run)

    try:
        if args.all:
            logger.info("=" * 60)
            logger.info("Starting full workspace backfill")
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
            service.sync_specific_channels(channel_ids, days_back=args.days)
            logger.info("✅ Channel sync completed!")

    except KeyboardInterrupt:
        logger.info("\n⚠️  Backfill interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if not args.dry_run:
            DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    main()
