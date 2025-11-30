"""
Slack API client wrapper for data collection.
Provides helper methods for fetching channels, messages, users, etc.
"""

import os
import time
import logging
from typing import List, Dict, Optional, Generator
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class SlackClient:
    """
    Wrapper around Slack WebClient with rate limiting and helper methods.
    """

    def __init__(self, token: Optional[str] = None):
        """
        Initialize Slack client.

        Args:
            token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
        """
        self.token = token or os.getenv('SLACK_BOT_TOKEN')
        if not self.token:
            raise ValueError("SLACK_BOT_TOKEN not found in environment")

        self.client = WebClient(token=self.token)
        self.rate_limit_delay = 1.0  # Slack recommends 1 req/sec for most endpoints

    def _handle_rate_limit(self, error: SlackApiError):
        """Handle rate limiting with exponential backoff."""
        retry_after = int(error.response.headers.get('Retry-After', 60))
        logger.warning(f"Rate limited. Retrying after {retry_after} seconds...")
        time.sleep(retry_after)

    def test_auth(self) -> Dict:
        """
        Test authentication and return bot info.

        Returns:
            Dict with bot user info
        """
        try:
            response = self.client.auth_test()
            logger.info(f"✅ Connected as: {response['user']} in team: {response['team']}")
            return response
        except SlackApiError as e:
            logger.error(f"❌ Authentication failed: {e.response['error']}")
            raise

    def get_workspace_info(self) -> Dict:
        """
        Get workspace/team information.

        Returns:
            Dict with workspace details
        """
        try:
            response = self.client.team_info()
            return response['team']
        except SlackApiError as e:
            logger.error(f"Failed to fetch workspace info: {e}")
            raise

    def get_channel_list(self, types: str = "public_channel,private_channel") -> List[Dict]:
        """
        Fetch all channels the bot is a member of.

        Args:
            types: Channel types to fetch (comma-separated)

        Returns:
            List of channel dicts
        """
        channels = []
        cursor = None

        try:
            while True:
                response = self.client.conversations_list(
                    types=types,
                    limit=200,
                    cursor=cursor
                )

                channels.extend(response['channels'])

                if not response.get('response_metadata', {}).get('next_cursor'):
                    break

                cursor = response['response_metadata']['next_cursor']
                time.sleep(self.rate_limit_delay)

            logger.info(f"Found {len(channels)} channels")
            return channels

        except SlackApiError as e:
            logger.error(f"Failed to fetch channels: {e}")
            raise

    def get_channel_info(self, channel_id: str) -> Dict:
        """
        Get detailed info about a specific channel.

        Args:
            channel_id: Channel ID

        Returns:
            Channel info dict
        """
        try:
            response = self.client.conversations_info(channel=channel_id)
            return response['channel']
        except SlackApiError as e:
            logger.error(f"Failed to fetch channel {channel_id}: {e}")
            raise

    def get_channel_history(
        self,
        channel_id: str,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
        limit: int = 100
    ) -> Generator[Dict, None, None]:
        """
        Fetch message history from a channel with pagination.

        Args:
            channel_id: Channel ID
            oldest: Oldest timestamp to fetch (inclusive)
            latest: Latest timestamp to fetch (exclusive)
            limit: Messages per page (max 200)

        Yields:
            Message dicts
        """
        cursor = None
        messages_fetched = 0

        try:
            while True:
                params = {
                    'channel': channel_id,
                    'limit': min(limit, 200),
                    'cursor': cursor
                }

                if oldest:
                    params['oldest'] = oldest
                if latest:
                    params['latest'] = latest

                response = self.client.conversations_history(**params)
                messages = response['messages']

                for message in messages:
                    yield message
                    messages_fetched += 1

                if not response.get('has_more', False):
                    break

                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break

                time.sleep(self.rate_limit_delay)

            logger.info(f"Fetched {messages_fetched} messages from channel {channel_id}")

        except SlackApiError as e:
            if e.response['error'] == 'rate_limited':
                self._handle_rate_limit(e)
                # Retry after rate limit
                yield from self.get_channel_history(channel_id, oldest, latest, limit)
            else:
                logger.error(f"Failed to fetch history for {channel_id}: {e}")
                raise

    def get_thread_replies(
        self,
        channel_id: str,
        thread_ts: str
    ) -> List[Dict]:
        """
        Fetch all replies in a thread.

        Args:
            channel_id: Channel ID
            thread_ts: Parent message timestamp

        Returns:
            List of reply messages (includes parent as first message)
        """
        replies = []
        cursor = None

        try:
            while True:
                response = self.client.conversations_replies(
                    channel=channel_id,
                    ts=thread_ts,
                    cursor=cursor,
                    limit=200
                )

                replies.extend(response['messages'])

                if not response.get('has_more', False):
                    break

                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break

                time.sleep(self.rate_limit_delay)

            # Remove parent (first message) to get only replies
            return replies[1:] if len(replies) > 1 else []

        except SlackApiError as e:
            logger.error(f"Failed to fetch thread replies for {thread_ts}: {e}")
            raise

    def get_user_info(self, user_id: str) -> Dict:
        """
        Get user profile information.

        Args:
            user_id: User ID

        Returns:
            User info dict
        """
        try:
            response = self.client.users_info(user=user_id)
            return response['user']
        except SlackApiError as e:
            logger.error(f"Failed to fetch user {user_id}: {e}")
            raise

    def get_all_users(self) -> List[Dict]:
        """
        Fetch all users in the workspace.

        Returns:
            List of user dicts
        """
        users = []
        cursor = None

        try:
            while True:
                response = self.client.users_list(
                    cursor=cursor,
                    limit=200
                )

                users.extend(response['members'])

                if not response.get('response_metadata', {}).get('next_cursor'):
                    break

                cursor = response['response_metadata']['next_cursor']
                time.sleep(self.rate_limit_delay)

            logger.info(f"Found {len(users)} users")
            return users

        except SlackApiError as e:
            logger.error(f"Failed to fetch users: {e}")
            raise

    def get_file_info(self, file_id: str) -> Dict:
        """
        Get file metadata.

        Args:
            file_id: File ID

        Returns:
            File info dict
        """
        try:
            response = self.client.files_info(file=file_id)
            return response['file']
        except SlackApiError as e:
            logger.error(f"Failed to fetch file {file_id}: {e}")
            raise

    def get_bookmarks(self, channel_id: str) -> List[Dict]:
        """
        Get channel bookmarks.

        Args:
            channel_id: Channel ID

        Returns:
            List of bookmark dicts
        """
        try:
            response = self.client.bookmarks_list(channel_id=channel_id)
            return response.get('bookmarks', [])
        except SlackApiError as e:
            if e.response['error'] == 'method_not_supported_for_channel_type':
                # Some channel types don't support bookmarks
                return []
            logger.error(f"Failed to fetch bookmarks for {channel_id}: {e}")
            raise


if __name__ == "__main__":
    # Test the client when run directly
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Testing Slack connection...\n")

    try:
        client = SlackClient()

        # Test authentication
        print("1. Testing authentication...")
        auth_info = client.test_auth()
        print(f"   Bot: {auth_info['user']}")
        print(f"   Team: {auth_info['team']}\n")

        # Get workspace info
        print("2. Getting workspace info...")
        workspace = client.get_workspace_info()
        print(f"   Name: {workspace['name']}")
        print(f"   Domain: {workspace['domain']}.slack.com\n")

        # List channels
        print("3. Fetching channels...")
        channels = client.get_channel_list()
        print(f"   Found {len(channels)} channels:")
        for ch in channels[:5]:  # Show first 5
            print(f"     - {ch['name']} ({'private' if ch['is_private'] else 'public'})")
        if len(channels) > 5:
            print(f"     ... and {len(channels) - 5} more\n")

        # Get users
        print("4. Fetching users...")
        users = client.get_all_users()
        human_users = [u for u in users if not u.get('is_bot', False) and not u.get('deleted', False)]
        print(f"   Found {len(human_users)} human users (out of {len(users)} total)\n")

        print("✅ All tests passed! Slack client is ready.\n")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise
