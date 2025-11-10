"""
Newsletter Service - Generate periodic summaries of Slack activity.
Includes trending topics, most reacted messages, and active discussions.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import Counter

from src.services.query_service import QueryService

logger = logging.getLogger(__name__)


class NewsletterService:
    """
    Service for generating newsletters from Slack activity.

    Features:
    - Trending topics (most discussed)
    - Most reacted messages
    - Active channels
    - Top contributors
    """

    def __init__(self, workspace_id: str):
        """
        Initialize newsletter service.

        Args:
            workspace_id: Workspace ID
        """
        self.workspace_id = workspace_id
        self.query_service = QueryService(workspace_id)

    def generate_newsletter(
        self,
        days_back: int = 7,
        max_topics: int = 5,
        max_messages: int = 10
    ) -> Dict:
        """
        Generate a complete newsletter.

        Args:
            days_back: Number of days to look back
            max_topics: Maximum trending topics to include
            max_messages: Maximum messages to include per section

        Returns:
            Newsletter dict with all sections
        """
        logger.info(f"Generating newsletter for last {days_back} days")

        newsletter = {
            'period': {
                'days_back': days_back,
                'start_date': (datetime.now() - timedelta(days=days_back)).isoformat(),
                'end_date': datetime.now().isoformat()
            },
            'trending_topics': self._get_trending_topics(days_back, max_topics),
            'most_reacted': self._get_most_reacted_messages(days_back, max_messages),
            'active_channels': self._get_active_channels(days_back),
            'top_contributors': self._get_top_contributors(days_back),
            'generated_at': datetime.now().isoformat()
        }

        return newsletter

    def _get_trending_topics(self, days_back: int, max_topics: int) -> List[Dict]:
        """
        Get trending topics using semantic clustering.

        Args:
            days_back: Days to look back
            max_topics: Maximum topics to return

        Returns:
            List of trending topic dicts
        """
        logger.info("Analyzing trending topics...")

        # Get recent messages
        recent_messages = self.query_service.get_recent_messages(
            days_back=days_back,
            limit=500  # Analyze up to 500 messages
        )

        if not recent_messages:
            return []

        # Extract keywords/topics (simple approach: common words)
        # In production, use LLM or NLP for better topic extraction
        topics = self._extract_topics_from_messages(recent_messages)

        return topics[:max_topics]

    def _extract_topics_from_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Extract topics from messages using keyword analysis.

        Args:
            messages: List of messages

        Returns:
            List of topic dicts with frequency
        """
        # Common stop words to filter out
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'should', 'could', 'may', 'might', 'can', 'i', 'you', 'he', 'she',
            'it', 'we', 'they', 'this', 'that', 'these', 'those'
        }

        # Extract words from all messages
        all_words = []
        topic_messages = {}  # Track which messages contain each topic

        for msg in messages:
            text = msg.get('text', '').lower()
            words = text.split()

            for word in words:
                # Clean word (remove punctuation)
                word = ''.join(c for c in word if c.isalnum())

                # Skip stop words and short words
                if word and len(word) > 3 and word not in stop_words:
                    all_words.append(word)

                    # Track message for this topic
                    if word not in topic_messages:
                        topic_messages[word] = []
                    if len(topic_messages[word]) < 3:  # Keep up to 3 example messages
                        topic_messages[word].append(msg)

        # Count word frequencies
        word_counts = Counter(all_words)

        # Build topic list
        topics = []
        for word, count in word_counts.most_common(20):  # Top 20 words
            if count >= 3:  # Minimum 3 mentions
                topics.append({
                    'topic': word,
                    'mention_count': count,
                    'example_messages': [
                        {
                            'text': msg['text'][:100] + ('...' if len(msg['text']) > 100 else ''),
                            'channel': msg['metadata'].get('channel_name', 'unknown'),
                            'user': msg['metadata'].get('user_name', 'unknown')
                        }
                        for msg in topic_messages.get(word, [])[:2]  # Top 2 examples
                    ]
                })

        return topics

    def _get_most_reacted_messages(self, days_back: int, limit: int) -> List[Dict]:
        """
        Get most reacted messages.

        Args:
            days_back: Days to look back
            limit: Maximum messages to return

        Returns:
            List of message dicts with reaction counts
        """
        logger.info("Fetching most reacted messages...")

        messages = self.query_service.get_most_reacted_messages(
            days_back=days_back,
            limit=limit
        )

        return messages

    def _get_active_channels(self, days_back: int) -> List[Dict]:
        """
        Get most active channels by message count.

        Args:
            days_back: Days to look back

        Returns:
            List of channel dicts with activity metrics
        """
        logger.info("Analyzing channel activity...")

        channels = self.query_service.get_channel_activity(days_back=days_back)

        return channels

    def _get_top_contributors(self, days_back: int, limit: int = 10) -> List[Dict]:
        """
        Get most active contributors.

        Args:
            days_back: Days to look back
            limit: Maximum contributors to return

        Returns:
            List of contributor dicts
        """
        logger.info("Finding top contributors...")

        contributors = self.query_service.get_top_contributors(
            days_back=days_back,
            limit=limit
        )

        return contributors

    def format_newsletter_markdown(self, newsletter: Dict) -> str:
        """
        Format newsletter as markdown for easy sharing.

        Args:
            newsletter: Newsletter dict from generate_newsletter()

        Returns:
            Formatted markdown string
        """
        md_parts = []

        # Header
        md_parts.append("# 📰 Workspace Newsletter")
        md_parts.append(f"\n**Period:** Last {newsletter['period']['days_back']} days")
        md_parts.append(f"**Generated:** {newsletter['generated_at']}\n")

        # Trending Topics
        md_parts.append("\n## 🔥 Trending Topics\n")
        if newsletter['trending_topics']:
            for i, topic in enumerate(newsletter['trending_topics'], 1):
                md_parts.append(f"### {i}. {topic['topic'].title()} ({topic['mention_count']} mentions)")
                if topic['example_messages']:
                    md_parts.append("\n**Example discussions:**")
                    for msg in topic['example_messages']:
                        md_parts.append(f"- *#{msg['channel']}* - {msg['user']}: \"{msg['text']}\"")
                md_parts.append("")
        else:
            md_parts.append("*No trending topics found for this period.*\n")

        # Most Reacted Messages
        md_parts.append("\n## ⭐ Most Reacted Messages\n")
        if newsletter['most_reacted']:
            for i, msg in enumerate(newsletter['most_reacted'], 1):
                md_parts.append(f"{i}. **{msg['reaction_count']} reactions** in #{msg['channel_name']}")
                md_parts.append(f"   *{msg['user_name']}:* \"{msg['text'][:150]}...\"")
                md_parts.append("")
        else:
            md_parts.append("*No reactions found for this period.*\n")

        # Active Channels
        md_parts.append("\n## 💬 Most Active Channels\n")
        if newsletter['active_channels']:
            for channel in newsletter['active_channels']:
                md_parts.append(f"- **#{channel['channel_name']}**: {channel['message_count']} messages")
        else:
            md_parts.append("*No channel activity found.*\n")

        # Top Contributors
        md_parts.append("\n## 👥 Top Contributors\n")
        if newsletter['top_contributors']:
            for i, user in enumerate(newsletter['top_contributors'], 1):
                md_parts.append(f"{i}. **{user['user_name']}**: {user['message_count']} messages")
        else:
            md_parts.append("*No contributor data available.*\n")

        md_parts.append("\n---")
        md_parts.append("*Generated by Slack Helper Bot*")

        return "\n".join(md_parts)

    def format_newsletter_text(self, newsletter: Dict) -> str:
        """
        Format newsletter as plain text.

        Args:
            newsletter: Newsletter dict from generate_newsletter()

        Returns:
            Formatted text string
        """
        lines = []

        # Header
        lines.append("=" * 70)
        lines.append("📰 WORKSPACE NEWSLETTER")
        lines.append("=" * 70)
        lines.append(f"Period: Last {newsletter['period']['days_back']} days")
        lines.append(f"Generated: {newsletter['generated_at']}")
        lines.append("")

        # Trending Topics
        lines.append("🔥 TRENDING TOPICS")
        lines.append("-" * 70)
        if newsletter['trending_topics']:
            for i, topic in enumerate(newsletter['trending_topics'], 1):
                lines.append(f"{i}. {topic['topic'].upper()} ({topic['mention_count']} mentions)")
                if topic['example_messages']:
                    for msg in topic['example_messages'][:1]:  # One example
                        lines.append(f"   → #{msg['channel']}: \"{msg['text'][:80]}...\"")
                lines.append("")
        else:
            lines.append("No trending topics found.")
            lines.append("")

        # Most Reacted Messages
        lines.append("⭐ MOST REACTED MESSAGES")
        lines.append("-" * 70)
        if newsletter['most_reacted']:
            for i, msg in enumerate(newsletter['most_reacted'][:5], 1):
                lines.append(f"{i}. {msg['reaction_count']} reactions - #{msg['channel_name']}")
                lines.append(f"   {msg['user_name']}: \"{msg['text'][:80]}...\"")
                lines.append("")
        else:
            lines.append("No reactions found.")
            lines.append("")

        # Active Channels
        lines.append("💬 MOST ACTIVE CHANNELS")
        lines.append("-" * 70)
        if newsletter['active_channels']:
            for channel in newsletter['active_channels'][:5]:
                lines.append(f"  #{channel['channel_name']}: {channel['message_count']} messages")
        else:
            lines.append("No channel activity found.")
        lines.append("")

        # Top Contributors
        lines.append("👥 TOP CONTRIBUTORS")
        lines.append("-" * 70)
        if newsletter['top_contributors']:
            for i, user in enumerate(newsletter['top_contributors'][:5], 1):
                lines.append(f"  {i}. {user['user_name']}: {user['message_count']} messages")
        else:
            lines.append("No contributor data available.")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)


if __name__ == "__main__":
    # Test the newsletter service
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Testing Newsletter Service...\n")

    newsletter_service = NewsletterService(workspace_id='W_DEFAULT')

    # Generate newsletter for last 7 days
    newsletter = newsletter_service.generate_newsletter(days_back=7)

    # Display as text
    print(newsletter_service.format_newsletter_text(newsletter))

    # Close database connections
    from src.db.connection import DatabaseConnection
    DatabaseConnection.close_all_connections()
