"""
Hybrid query service for PostgreSQL + ChromaDB.
Provides high-level query methods for features like newsletter, PR review, Q&A.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from src.db.connection import DatabaseConnection
from src.db.chromadb_client import ChromaDBClient
from psycopg2 import extras

logger = logging.getLogger(__name__)


class QueryService:
    """
    High-level query service that abstracts PostgreSQL + ChromaDB.
    """

    def __init__(self, workspace_id: str):
        """
        Initialize query service.

        Args:
            workspace_id: Workspace ID (REQUIRED for security/isolation)

        Raises:
            ValueError: If workspace_id is None or empty
        """
        if not workspace_id:
            raise ValueError(
                "workspace_id is REQUIRED for query service. "
                "This ensures workspace data isolation for security."
            )

        self.workspace_id = workspace_id
        self.chromadb = ChromaDBClient()
        DatabaseConnection.initialize_pool()

    def get_most_reacted_messages(
        self,
        days_back: int = 7,
        limit: int = 10,
        channel_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Get most reacted messages with full content.

        Args:
            days_back: Look back N days
            limit: Number of results
            channel_id: Optional channel filter

        Returns:
            List of dicts with message content, reactions, metadata
        """
        conn = DatabaseConnection.get_connection()
        try:
            query = """
                SELECT
                    m.message_id,
                    m.slack_ts,
                    m.channel_id,
                    m.channel_name,
                    m.user_name,
                    m.permalink,
                    m.created_at,
                    m.chromadb_id,
                    COUNT(r.reaction_id) as reaction_count,
                    ARRAY_AGG(DISTINCT r.reaction_name) as reaction_types
                FROM message_metadata m
                INNER JOIN reactions r ON m.message_id = r.message_id
                WHERE m.workspace_id = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.deleted_at IS NULL
            """
            params = [self.workspace_id, days_back]

            if channel_id:
                query += " AND m.channel_id = %s"
                params.append(channel_id)

            query += """
                GROUP BY m.message_id, m.slack_ts, m.channel_id, m.channel_name,
                         m.user_name, m.permalink, m.created_at, m.chromadb_id
                ORDER BY reaction_count DESC
                LIMIT %s
            """
            params.append(limit)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                results = cur.fetchall()

            # Enrich with message content from ChromaDB
            enriched = []
            for msg in results:
                # Get full message text from ChromaDB
                chroma_msg = self.chromadb.get_message(
                    self.workspace_id,
                    msg['slack_ts']
                )

                enriched.append({
                    'message_id': msg['message_id'],
                    'text': chroma_msg['text'] if chroma_msg else '[Message not found]',
                    'channel_name': msg['channel_name'],
                    'user_name': msg['user_name'],
                    'permalink': msg['permalink'],
                    'created_at': msg['created_at'],
                    'reaction_count': msg['reaction_count'],
                    'reaction_types': msg['reaction_types'],
                    'metadata': {
                        'channel_name': msg['channel_name'],
                        'user_name': msg['user_name']
                    }
                })

            return enriched

        finally:
            DatabaseConnection.return_connection(conn)

    def semantic_search(
        self,
        query: str,
        n_results: int = 10,
        channel_filter: Optional[str] = None,
        days_back: Optional[int] = None
    ) -> List[Dict]:
        """
        Semantic search across messages with optional filters.

        Args:
            query: Search query text
            n_results: Number of results
            channel_filter: Optional channel name filter
            days_back: Optional time filter (last N days)

        Returns:
            List of messages with similarity scores
        """
        # Build ChromaDB filter
        where_filter = {}

        if channel_filter:
            where_filter['channel_name'] = channel_filter

        # Search in ChromaDB
        results = self.chromadb.search_messages(
            workspace_id=self.workspace_id,
            query_text=query,
            n_results=n_results,
            where_filter=where_filter if where_filter else None
        )

        # Filter by date if needed (post-process since ChromaDB doesn't have date filtering)
        if days_back:
            cutoff = datetime.now() - timedelta(days=days_back)
            results = [
                r for r in results
                if self._parse_timestamp(r['metadata'].get('timestamp', '')) > cutoff
            ]

        return results

    def get_pr_discussions(
        self,
        pr_url: str,
        include_similar: bool = True
    ) -> Dict:
        """
        Find all discussions about a specific PR.

        Args:
            pr_url: GitHub PR URL
            include_similar: Also find semantically similar discussions

        Returns:
            Dict with direct mentions and similar discussions
        """
        conn = DatabaseConnection.get_connection()
        try:
            # 1. Find messages with direct PR link (PostgreSQL)
            query = """
                SELECT DISTINCT
                    m.message_id,
                    m.slack_ts,
                    m.channel_name,
                    m.user_name,
                    m.created_at,
                    m.permalink
                FROM message_metadata m
                INNER JOIN links l ON m.message_id = l.message_id
                WHERE m.workspace_id = %s
                  AND l.url = %s
                  AND m.deleted_at IS NULL
                ORDER BY m.created_at DESC
            """

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (self.workspace_id, pr_url))
                direct_mentions = cur.fetchall()

            # Enrich with message content
            enriched_mentions = []
            for msg in direct_mentions:
                chroma_msg = self.chromadb.get_message(
                    self.workspace_id,
                    msg['slack_ts']
                )
                enriched_mentions.append({
                    **dict(msg),
                    'text': chroma_msg['text'] if chroma_msg else ''
                })

            result = {
                'pr_url': pr_url,
                'direct_mentions': enriched_mentions,
                'mention_count': len(enriched_mentions)
            }

            # 2. Find similar discussions (ChromaDB semantic search)
            if include_similar and enriched_mentions:
                # Use first mention as seed for similarity search
                seed_text = enriched_mentions[0]['text']
                similar = self.chromadb.search_messages(
                    workspace_id=self.workspace_id,
                    query_text=seed_text,
                    n_results=10
                )

                # Filter out the direct mentions
                mentioned_ts = {m['slack_ts'] for m in enriched_mentions}
                similar_filtered = [
                    s for s in similar
                    if s['id'].split('_')[-1] not in mentioned_ts
                ]

                result['similar_discussions'] = similar_filtered[:5]

            return result

        finally:
            DatabaseConnection.return_connection(conn)

    def get_channel_activity_summary(
        self,
        days_back: int = 30
    ) -> List[Dict]:
        """
        Get activity summary for all channels.

        Args:
            days_back: Look back N days

        Returns:
            List of channel summaries
        """
        conn = DatabaseConnection.get_connection()
        try:
            query = """
                SELECT
                    m.channel_id,
                    m.channel_name,
                    COUNT(m.message_id) as message_count,
                    COUNT(DISTINCT m.user_id) as active_users,
                    SUM(CASE WHEN r.reaction_id IS NOT NULL THEN 1 ELSE 0 END) as messages_with_reactions,
                    COUNT(r.reaction_id) as total_reactions,
                    SUM(m.link_count) as total_links,
                    MAX(m.created_at) as last_activity
                FROM message_metadata m
                LEFT JOIN reactions r ON m.message_id = r.message_id
                WHERE m.workspace_id = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.deleted_at IS NULL
                GROUP BY m.channel_id, m.channel_name
                ORDER BY message_count DESC
            """

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (self.workspace_id, days_back))
                return cur.fetchall()

        finally:
            DatabaseConnection.return_connection(conn)

    def get_trending_topics(
        self,
        days_back: int = 7,
        n_topics: int = 5
    ) -> List[Dict]:
        """
        Discover trending topics using semantic clustering.

        Args:
            days_back: Look back N days
            n_topics: Number of topics to return

        Returns:
            List of topic clusters with sample messages
        """
        # Get recent high-engagement messages
        top_messages = self.get_most_reacted_messages(
            days_back=days_back,
            limit=50
        )

        if not top_messages:
            return []

        # Simple topic extraction: use message text as topics
        # In production, you'd use proper topic modeling or LLM summarization
        topics = []
        for msg in top_messages[:n_topics]:
            topic = {
                'sample_text': msg['text'][:200] + '...',
                'channel': msg['channel'],
                'engagement': msg['reaction_count'],
                'created_at': msg['created_at']
            }
            topics.append(topic)

        return topics

    def find_expert_on_topic(
        self,
        topic: str,
        n_results: int = 5
    ) -> List[Dict]:
        """
        Find users who frequently discuss a topic.

        Args:
            topic: Topic to search for
            n_results: Number of experts to return

        Returns:
            List of users with message counts
        """
        # Semantic search for topic
        messages = self.semantic_search(topic, n_results=100)

        # Count messages per user
        user_counts = {}
        for msg in messages:
            user = msg['metadata'].get('user_name', 'Unknown')
            if user not in user_counts:
                user_counts[user] = {
                    'user_name': user,
                    'message_count': 0,
                    'sample_messages': []
                }
            user_counts[user]['message_count'] += 1
            if len(user_counts[user]['sample_messages']) < 3:
                user_counts[user]['sample_messages'].append(msg['text'][:100])

        # Sort by message count
        experts = sorted(
            user_counts.values(),
            key=lambda x: x['message_count'],
            reverse=True
        )

        return experts[:n_results]

    def get_user_stats(self, user_id: str) -> Dict:
        """
        Get comprehensive stats for a user.

        Args:
            user_id: Slack user ID

        Returns:
            Dict with user statistics
        """
        conn = DatabaseConnection.get_connection()
        try:
            query = """
                SELECT
                    u.user_name,
                    u.real_name,
                    u.title,
                    COUNT(m.message_id) as total_messages,
                    COUNT(DISTINCT m.channel_id) as channels_active,
                    SUM(CASE WHEN r.reaction_id IS NOT NULL THEN 1 ELSE 0 END) as messages_with_reactions,
                    COUNT(r.reaction_id) as reactions_received,
                    MAX(m.created_at) as last_message_at
                FROM users u
                LEFT JOIN message_metadata m ON u.user_id = m.user_id AND u.workspace_id = m.workspace_id
                LEFT JOIN reactions r ON m.message_id = r.message_id
                WHERE u.workspace_id = %s AND u.user_id = %s
                GROUP BY u.user_name, u.real_name, u.title
            """

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (self.workspace_id, user_id))
                return cur.fetchone()

        finally:
            DatabaseConnection.return_connection(conn)

    def get_recent_messages(
        self,
        days_back: int = 7,
        limit: int = 100,
        channel_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Get recent messages with their full content.

        Args:
            days_back: Look back N days
            limit: Number of messages to return
            channel_filter: Optional channel name filter

        Returns:
            List of message dicts with text and metadata
        """
        conn = DatabaseConnection.get_connection()
        try:
            query = """
                SELECT
                    m.message_id,
                    m.slack_ts,
                    m.channel_id,
                    m.channel_name,
                    m.user_id,
                    m.user_name,
                    m.created_at,
                    m.chromadb_id
                FROM message_metadata m
                WHERE m.workspace_id = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.deleted_at IS NULL
            """
            params = [self.workspace_id, days_back]

            if channel_filter:
                query += " AND m.channel_name = %s"
                params.append(channel_filter)

            query += " ORDER BY m.created_at DESC LIMIT %s"
            params.append(limit)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, params)
                results = cur.fetchall()

            # Enrich with message content from ChromaDB
            enriched = []
            for msg in results:
                chroma_msg = self.chromadb.get_message(
                    self.workspace_id,
                    msg['slack_ts']
                )

                if chroma_msg:
                    enriched.append({
                        'message_id': msg['message_id'],
                        'text': chroma_msg['text'],
                        'metadata': chroma_msg['metadata'],
                        'slack_ts': msg['slack_ts'],
                        'created_at': msg['created_at']
                    })

            return enriched

        finally:
            DatabaseConnection.return_connection(conn)

    def get_channel_activity(
        self,
        days_back: int = 7
    ) -> List[Dict]:
        """
        Get channel activity metrics.

        Args:
            days_back: Look back N days

        Returns:
            List of channel dicts with message counts
        """
        conn = DatabaseConnection.get_connection()
        try:
            query = """
                SELECT
                    m.channel_id,
                    m.channel_name,
                    COUNT(m.message_id) as message_count,
                    COUNT(DISTINCT m.user_id) as active_users,
                    MAX(m.created_at) as last_activity
                FROM message_metadata m
                WHERE m.workspace_id = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.deleted_at IS NULL
                GROUP BY m.channel_id, m.channel_name
                ORDER BY message_count DESC
            """

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (self.workspace_id, days_back))
                return cur.fetchall()

        finally:
            DatabaseConnection.return_connection(conn)

    def get_top_contributors(
        self,
        days_back: int = 7,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get most active contributors by message count.

        Args:
            days_back: Look back N days
            limit: Number of contributors to return

        Returns:
            List of user dicts with message counts
        """
        conn = DatabaseConnection.get_connection()
        try:
            query = """
                SELECT
                    m.user_id,
                    m.user_name,
                    COUNT(m.message_id) as message_count,
                    COUNT(DISTINCT m.channel_id) as channels_active,
                    MAX(m.created_at) as last_message_at
                FROM message_metadata m
                WHERE m.workspace_id = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.deleted_at IS NULL
                  AND m.user_id IS NOT NULL
                GROUP BY m.user_id, m.user_name
                ORDER BY message_count DESC
                LIMIT %s
            """

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (self.workspace_id, days_back, limit))
                return cur.fetchall()

        finally:
            DatabaseConnection.return_connection(conn)

    def _parse_timestamp(self, ts_string: str) -> datetime:
        """Parse Slack timestamp string."""
        try:
            return datetime.fromtimestamp(float(ts_string))
        except:
            return datetime.min


if __name__ == "__main__":
    # Test the query service
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Testing Query Service...\n")

    service = QueryService(workspace_id='W_DEFAULT')

    # Test 1: Most reacted messages
    print("1. Most reacted messages (last 7 days):")
    top_messages = service.get_most_reacted_messages(days_back=7, limit=5)
    for i, msg in enumerate(top_messages, 1):
        print(f"   {i}. [{msg['channel']}] {msg['text'][:60]}...")
        print(f"      Reactions: {msg['reaction_count']} - {msg['reaction_types']}")
    print()

    # Test 2: Semantic search
    print("2. Semantic search for 'hackathon project':")
    results = service.semantic_search('hackathon project', n_results=3)
    for i, msg in enumerate(results, 1):
        print(f"   {i}. {msg['text'][:80]}...")
        print(f"      Channel: {msg['metadata']['channel_name']}")
    print()

    # Test 3: Channel activity
    print("3. Channel activity (last 30 days):")
    activity = service.get_channel_activity_summary(days_back=30)
    for channel in activity:
        print(f"   #{channel['channel_name']}: {channel['message_count']} messages, "
              f"{channel['active_users']} users, {channel['total_reactions']} reactions")
    print()

    # Test 4: Trending topics
    print("4. Trending topics:")
    topics = service.get_trending_topics(days_back=7, n_topics=3)
    for i, topic in enumerate(topics, 1):
        print(f"   {i}. {topic['sample_text'][:80]}...")
        print(f"      Engagement: {topic['engagement']} reactions")
    print()

    print("✅ Query service tests complete!")

    DatabaseConnection.close_all_connections()
