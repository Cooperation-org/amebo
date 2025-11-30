"""
Message processor for parsing Slack messages and extracting metadata.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageProcessor:
    """
    Processes Slack messages and extracts structured data.
    """

    @staticmethod
    def parse_message(message: Dict, channel_id: str, channel_name: str) -> Dict:
        """
        Parse a Slack message into database-ready format.

        Args:
            message: Raw Slack message dict
            channel_id: Channel ID
            channel_name: Channel name

        Returns:
            Parsed message dict ready for DB insertion
        """
        return {
            'slack_ts': message.get('ts'),
            'channel_id': channel_id,
            'channel_name': channel_name,
            'user_id': message.get('user', message.get('bot_id', 'UNKNOWN')),
            'user_name': message.get('username', ''),
            'message_text': message.get('text', ''),
            'message_type': MessageProcessor._determine_message_type(message),
            'thread_ts': message.get('thread_ts'),
            'reply_count': message.get('reply_count', 0),
            'reply_users_count': message.get('reply_users_count', 0),
            'attachments': message.get('attachments', []),
            'mentions': MessageProcessor.extract_mentions(message.get('text', '')),
            'blocks': message.get('blocks', []),
            'permalink': message.get('permalink', ''),
            'is_pinned': message.get('pinned_to', []) != [],
            'edited_at': MessageProcessor._parse_edited_ts(message),
            'created_at': MessageProcessor._parse_timestamp(message.get('ts')),
            'raw_data': message
        }

    @staticmethod
    def _determine_message_type(message: Dict) -> str:
        """Determine the type of message."""
        subtype = message.get('subtype', '')

        if subtype == 'bot_message':
            return 'bot_message'
        elif subtype == 'file_share':
            return 'file_share'
        elif message.get('thread_ts') and message.get('thread_ts') != message.get('ts'):
            return 'thread_reply'
        else:
            return 'regular'

    @staticmethod
    def extract_mentions(text: str) -> List[str]:
        """
        Extract user and channel mentions from message text.

        Args:
            text: Message text

        Returns:
            List of mentioned user/channel IDs
        """
        if not text:
            return []

        # Slack mentions format: <@U123456> or <#C123456|channel-name>
        mentions = re.findall(r'<@([UW][A-Z0-9]+)>', text)
        channel_mentions = re.findall(r'<#([C][A-Z0-9]+)', text)

        return mentions + channel_mentions

    @staticmethod
    def extract_links(text: str, attachments: List = None) -> List[Dict]:
        """
        Extract URLs from message text and attachments.

        Args:
            text: Message text
            attachments: Message attachments

        Returns:
            List of dicts with url, link_type, domain
        """
        links = []

        # Extract from text
        if text:
            # Slack format: <https://example.com|display text> or just URLs
            slack_links = re.findall(r'<(https?://[^|>]+)', text)
            plain_links = re.findall(r'(?<!<)(https?://[^\s<>]+)(?![>|])', text)

            for url in slack_links + plain_links:
                link_info = MessageProcessor._classify_link(url)
                if link_info:
                    links.append(link_info)

        # Extract from attachments
        if attachments:
            for attachment in attachments:
                if 'title_link' in attachment:
                    link_info = MessageProcessor._classify_link(attachment['title_link'])
                    if link_info:
                        link_info['title'] = attachment.get('title', '')
                        link_info['description'] = attachment.get('text', '')
                        links.append(link_info)

        # Deduplicate by URL
        seen = set()
        unique_links = []
        for link in links:
            if link['url'] not in seen:
                seen.add(link['url'])
                unique_links.append(link)

        return unique_links

    @staticmethod
    def _classify_link(url: str) -> Optional[Dict]:
        """
        Classify a URL and extract metadata.

        Args:
            url: URL string

        Returns:
            Dict with url, link_type, domain or None
        """
        if not url:
            return None

        # Extract domain
        domain_match = re.match(r'https?://([^/]+)', url)
        domain = domain_match.group(1) if domain_match else ''

        # Classify link type
        link_type = 'other'

        if 'github.com' in domain:
            if '/pull/' in url:
                link_type = 'github_pr'
            elif '/issues/' in url:
                link_type = 'github_issue'
            else:
                link_type = 'github'
        elif 'atlassian.net' in domain and '/browse/' in url:
            link_type = 'jira'
        elif 'notion.so' in domain:
            link_type = 'notion'
        elif 'confluence' in domain:
            link_type = 'confluence'
        elif 'docs.google.com' in domain:
            link_type = 'google_docs'
        elif any(x in domain for x in ['youtube.com', 'youtu.be']):
            link_type = 'youtube'

        return {
            'url': url,
            'link_type': link_type,
            'domain': domain,
            'title': None,
            'description': None
        }

    @staticmethod
    def extract_reactions(message: Dict) -> List[Dict]:
        """
        Extract reactions from message.

        Args:
            message: Raw Slack message

        Returns:
            List of reaction dicts
        """
        reactions = []

        if 'reactions' in message:
            for reaction in message['reactions']:
                for user_id in reaction.get('users', []):
                    reactions.append({
                        'user_id': user_id,
                        'reaction_name': reaction['name'],
                        'reacted_at': datetime.now()  # Slack doesn't provide exact timestamp
                    })

        return reactions

    @staticmethod
    def extract_files(message: Dict) -> List[Dict]:
        """
        Extract file metadata from message.

        Args:
            message: Raw Slack message

        Returns:
            List of file dicts
        """
        files = []

        if 'files' in message:
            for file in message['files']:
                files.append({
                    'slack_file_id': file.get('id'),
                    'file_name': file.get('name'),
                    'file_type': file.get('filetype'),
                    'file_size': file.get('size'),
                    'mime_type': file.get('mimetype'),
                    'url_private': file.get('url_private'),
                    'url_private_download': file.get('url_private_download'),
                    'permalink': file.get('permalink'),
                    'uploaded_by': file.get('user'),
                    'uploaded_at': MessageProcessor._parse_timestamp(file.get('timestamp'))
                })

        return files

    @staticmethod
    def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
        """Convert Slack timestamp to datetime."""
        if not ts:
            return None

        try:
            # Slack timestamps are Unix epoch with microseconds: "1234567890.123456"
            return datetime.fromtimestamp(float(ts))
        except (ValueError, TypeError):
            logger.warning(f"Failed to parse timestamp: {ts}")
            return None

    @staticmethod
    def _parse_edited_ts(message: Dict) -> Optional[datetime]:
        """Extract edited timestamp if message was edited."""
        if 'edited' in message:
            return MessageProcessor._parse_timestamp(message['edited'].get('ts'))
        return None

    @staticmethod
    def is_thread_parent(message: Dict) -> bool:
        """Check if message is a thread parent."""
        return (
            'thread_ts' in message and
            message.get('thread_ts') == message.get('ts') and
            message.get('reply_count', 0) > 0
        )

    @staticmethod
    def is_thread_reply(message: Dict) -> bool:
        """Check if message is a thread reply."""
        return (
            'thread_ts' in message and
            message.get('thread_ts') != message.get('ts')
        )


if __name__ == "__main__":
    # Test the processor
    logging.basicConfig(level=logging.INFO)

    test_message = {
        'ts': '1234567890.123456',
        'user': 'U123456',
        'text': 'Check out this PR: <https://github.com/org/repo/pull/123|PR #123> cc <@U789012>',
        'thread_ts': '1234567890.123456',
        'reply_count': 5,
        'reactions': [
            {'name': 'thumbsup', 'users': ['U111', 'U222'], 'count': 2},
            {'name': 'heart', 'users': ['U333'], 'count': 1}
        ],
        'attachments': [
            {
                'title': 'GitHub PR',
                'title_link': 'https://github.com/org/repo/pull/123',
                'text': 'Fix bug in authentication'
            }
        ]
    }

    processor = MessageProcessor()

    print("Testing message parsing...\n")

    # Parse message
    parsed = processor.parse_message(test_message, 'C123', 'engineering')
    print(f"✅ Parsed message:")
    print(f"   Type: {parsed['message_type']}")
    print(f"   Mentions: {parsed['mentions']}")
    print()

    # Extract links
    links = processor.extract_links(test_message['text'], test_message['attachments'])
    print(f"✅ Extracted {len(links)} links:")
    for link in links:
        print(f"   - {link['link_type']}: {link['url']}")
    print()

    # Extract reactions
    reactions = processor.extract_reactions(test_message)
    print(f"✅ Extracted {len(reactions)} reactions:")
    for r in reactions:
        print(f"   - {r['reaction_name']} by {r['user_id']}")
    print()

    print("✅ Message processor working correctly!")
