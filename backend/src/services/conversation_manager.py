"""
Conversation Manager - Multi-turn conversation context tracking
Stores and retrieves conversation history for thread-aware responses
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Manages conversation history for multi-turn interactions

    Features:
    - Store user questions and bot responses
    - Retrieve thread history for context
    - Build prompts with conversation context
    - Limit context window to prevent token overflow
    """

    def __init__(self, workspace_id: str):
        """
        Initialize conversation manager

        Args:
            workspace_id: Workspace ID for data isolation
        """
        self.workspace_id = workspace_id
        self.max_history_turns = 10  # Keep last 10 turns (20 messages)

    def add_to_history(
        self,
        thread_ts: str,
        channel_id: str,
        role: str,
        content: str
    ) -> bool:
        """
        Add a message to conversation history

        Args:
            thread_ts: Thread timestamp (conversation ID)
            channel_id: Channel where conversation happened
            role: 'user' or 'assistant'
            content: Message content

        Returns:
            True if successful, False otherwise
        """
        if role not in ['user', 'assistant']:
            logger.error(f"Invalid role: {role}. Must be 'user' or 'assistant'")
            return False

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_history (
                        workspace_id, thread_ts, channel_id, role, content, created_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (self.workspace_id, thread_ts, channel_id, role, content)
                )
                conn.commit()
                logger.debug(f"Stored {role} message in thread {thread_ts}")
                return True

        except Exception as e:
            logger.error(f"Failed to store conversation history: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            DatabaseConnection.return_connection(conn)

    def get_thread_history(
        self,
        thread_ts: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        Retrieve conversation history for a thread

        Args:
            thread_ts: Thread timestamp to retrieve
            limit: Maximum number of messages to retrieve (default: max_history_turns * 2)

        Returns:
            List of messages in chronological order, each with 'role' and 'content'
        """
        if limit is None:
            limit = self.max_history_turns * 2  # 2 messages per turn (user + assistant)

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content, created_at
                    FROM conversation_history
                    WHERE workspace_id = %s AND thread_ts = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (self.workspace_id, thread_ts, limit)
                )

                rows = cur.fetchall()
                history = [
                    {
                        'role': row[0],
                        'content': row[1],
                        'timestamp': row[2].isoformat() if row[2] else None
                    }
                    for row in rows
                ]

                logger.debug(f"Retrieved {len(history)} messages from thread {thread_ts}")
                return history

        except Exception as e:
            logger.error(f"Failed to retrieve conversation history: {e}", exc_info=True)
            return []
        finally:
            DatabaseConnection.return_connection(conn)

    def build_context_prompt(
        self,
        thread_ts: str,
        new_question: str
    ) -> str:
        """
        Build a context-aware prompt including conversation history

        Args:
            thread_ts: Thread timestamp
            new_question: New question from user

        Returns:
            Formatted prompt with conversation context
        """
        history = self.get_thread_history(thread_ts)

        if not history:
            # No previous context, return just the question
            return new_question

        # Build context string
        context_parts = ["Previous conversation:"]

        for msg in history:
            role_label = "User" if msg['role'] == 'user' else "Assistant"
            context_parts.append(f"{role_label}: {msg['content']}")

        context_parts.append(f"\nNew question: {new_question}")

        return "\n".join(context_parts)

    def clear_thread_history(self, thread_ts: str) -> bool:
        """
        Clear conversation history for a thread

        Args:
            thread_ts: Thread timestamp to clear

        Returns:
            True if successful, False otherwise
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM conversation_history
                    WHERE workspace_id = %s AND thread_ts = %s
                    """,
                    (self.workspace_id, thread_ts)
                )
                deleted_count = cur.rowcount
                conn.commit()
                logger.info(f"Cleared {deleted_count} messages from thread {thread_ts}")
                return True

        except Exception as e:
            logger.error(f"Failed to clear conversation history: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            DatabaseConnection.return_connection(conn)

    def get_recent_conversations(
        self,
        channel_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get recent conversations (thread summaries)

        Args:
            channel_id: Optional channel filter
            limit: Number of recent threads to return

        Returns:
            List of thread summaries with metadata
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                if channel_id:
                    cur.execute(
                        """
                        SELECT DISTINCT thread_ts, channel_id, MAX(created_at) as last_updated
                        FROM conversation_history
                        WHERE workspace_id = %s AND channel_id = %s
                        GROUP BY thread_ts, channel_id
                        ORDER BY last_updated DESC
                        LIMIT %s
                        """,
                        (self.workspace_id, channel_id, limit)
                    )
                else:
                    cur.execute(
                        """
                        SELECT DISTINCT thread_ts, channel_id, MAX(created_at) as last_updated
                        FROM conversation_history
                        WHERE workspace_id = %s
                        GROUP BY thread_ts, channel_id
                        ORDER BY last_updated DESC
                        LIMIT %s
                        """,
                        (self.workspace_id, limit)
                    )

                rows = cur.fetchall()
                conversations = [
                    {
                        'thread_ts': row[0],
                        'channel_id': row[1],
                        'last_updated': row[2].isoformat() if row[2] else None
                    }
                    for row in rows
                ]

                return conversations

        except Exception as e:
            logger.error(f"Failed to get recent conversations: {e}", exc_info=True)
            return []
        finally:
            DatabaseConnection.return_connection(conn)
