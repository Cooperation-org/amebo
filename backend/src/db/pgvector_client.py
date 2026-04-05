"""
pgvector client for message content and vector storage.
Drop-in replacement for chromadb_client.py — same method signatures,
but stores vectors in PostgreSQL with pgvector extension.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from src.db.connection import DatabaseConnection
from src.db.embedding import embed_text, embed_texts, EMBEDDING_DIM

logger = logging.getLogger(__name__)


class PgvectorClient:
    """
    Manages message vectors in PostgreSQL with pgvector.
    Replaces ChromaDBClient with same interface.
    """

    def __init__(self):
        DatabaseConnection.initialize_pool()
        logger.info("PgvectorClient initialized")

    def add_message(
        self,
        workspace_id: str,
        message_id: int,
        slack_ts: str,
        message_text: str,
        metadata: Dict
    ) -> str:
        """
        Add a message with its embedding to pgvector.

        Returns:
            Document ID string (workspace_id_slack_ts)
        """
        doc_id = f"{workspace_id}_{slack_ts}"
        embedding = embed_text(message_text)

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO message_vectors
                        (workspace_id, message_id, content, embedding,
                         channel_id, channel_name, user_id, user_name, slack_ts)
                    VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, slack_ts)
                    DO UPDATE SET content = EXCLUDED.content,
                                  embedding = EXCLUDED.embedding,
                                  channel_name = EXCLUDED.channel_name,
                                  user_name = EXCLUDED.user_name
                """, (
                    workspace_id, message_id, message_text, embedding,
                    metadata.get('channel_id', ''),
                    metadata.get('channel_name', ''),
                    metadata.get('user_id', ''),
                    metadata.get('user_name', ''),
                    slack_ts
                ))
                conn.commit()
            logger.debug(f"Added message {doc_id} to pgvector")
            return doc_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add message {doc_id}: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def add_messages_batch(
        self,
        workspace_id: str,
        messages: List[Dict]
    ) -> List[str]:
        """
        Add multiple messages in batch. Generates embeddings in one call.

        Args:
            workspace_id: Workspace ID
            messages: List of dicts with keys: message_id, slack_ts, text, metadata

        Returns:
            List of document ID strings
        """
        if not messages:
            return []

        # Batch embed all texts
        texts = [msg['text'] for msg in messages]
        embeddings = embed_texts(texts)

        doc_ids = []
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                for msg, embedding in zip(messages, embeddings):
                    doc_id = f"{workspace_id}_{msg['slack_ts']}"
                    doc_ids.append(doc_id)
                    metadata = msg.get('metadata', {})

                    cur.execute("""
                        INSERT INTO message_vectors
                            (workspace_id, message_id, content, embedding,
                             channel_id, channel_name, user_id, user_name, slack_ts)
                        VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s)
                        ON CONFLICT (workspace_id, slack_ts)
                        DO UPDATE SET content = EXCLUDED.content,
                                      embedding = EXCLUDED.embedding,
                                      channel_name = EXCLUDED.channel_name,
                                      user_name = EXCLUDED.user_name
                    """, (
                        workspace_id,
                        msg.get('message_id'),
                        msg['text'],
                        embedding,
                        metadata.get('channel_id', ''),
                        metadata.get('channel_name', ''),
                        metadata.get('user_id', ''),
                        metadata.get('user_name', ''),
                        msg['slack_ts']
                    ))

                conn.commit()
            logger.info(f"Added {len(doc_ids)} messages to pgvector in batch")
            return doc_ids
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add message batch: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def get_message(
        self,
        workspace_id: str,
        slack_ts: str
    ) -> Optional[Dict]:
        """
        Get a message by workspace + slack timestamp.

        Returns:
            Dict with text, metadata — or None
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT content, channel_id, channel_name,
                           user_id, user_name, slack_ts
                    FROM message_vectors
                    WHERE workspace_id = %s AND slack_ts = %s
                """, (workspace_id, slack_ts))
                row = cur.fetchone()

            if row:
                return {
                    'id': f"{workspace_id}_{slack_ts}",
                    'text': row[0],
                    'metadata': {
                        'workspace_id': workspace_id,
                        'channel_id': row[1],
                        'channel_name': row[2],
                        'user_id': row[3],
                        'user_name': row[4],
                        'timestamp': row[5]
                    }
                }
            return None
        finally:
            DatabaseConnection.return_connection(conn)

    def search_messages(
        self,
        workspace_id: str,
        query_text: str,
        n_results: int = 10,
        where_filter: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Semantic search for messages using cosine similarity.

        Args:
            workspace_id: Workspace ID (REQUIRED)
            query_text: Search query
            n_results: Number of results
            where_filter: Optional metadata filters. Supports:
                          {'channel_name': 'general'}
                          {'channel_id': 'C123'}
                          {'$or': [{'channel_name': 'general'}, ...]}

        Returns:
            List of messages with similarity scores (compatible with ChromaDB format)
        """
        if not workspace_id:
            raise ValueError("workspace_id is REQUIRED for search")

        query_embedding = embed_text(query_text)

        # Build WHERE clause
        conditions = ["workspace_id = %s"]
        params = [workspace_id]

        if where_filter:
            filter_sql, filter_params = self._build_filter(where_filter)
            if filter_sql:
                conditions.append(filter_sql)
                params.extend(filter_params)

        where_clause = " AND ".join(conditions)

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                # params order: embedding (SELECT), workspace_id + filters (WHERE), embedding (ORDER), limit
                query_params = [query_embedding] + params + [query_embedding, n_results]
                cur.execute(f"""
                    SELECT content, channel_id, channel_name,
                           user_id, user_name, slack_ts, message_id,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM message_vectors
                    WHERE {where_clause}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, query_params)

                results = []
                for row in cur.fetchall():
                    results.append({
                        'id': f"{workspace_id}_{row[5]}",
                        'text': row[0],
                        'metadata': {
                            'workspace_id': workspace_id,
                            'channel_id': row[1],
                            'channel_name': row[2],
                            'user_id': row[3],
                            'user_name': row[4],
                            'timestamp': row[5],
                            'message_id': str(row[6]) if row[6] else ''
                        },
                        'distance': 1 - row[7] if row[7] is not None else None
                    })

                return results
        finally:
            DatabaseConnection.return_connection(conn)

    def _build_filter(self, where_filter: Dict):
        """
        Convert ChromaDB-style filter dict to SQL WHERE clause.
        Supports: simple key=value, $or, $and operators.
        """
        if not where_filter:
            return None, []

        # Handle $or
        if '$or' in where_filter:
            parts = []
            params = []
            for sub in where_filter['$or']:
                sql, p = self._build_filter(sub)
                if sql:
                    parts.append(sql)
                    params.extend(p)
            if parts:
                return f"({' OR '.join(parts)})", params
            return None, []

        # Handle $and
        if '$and' in where_filter:
            parts = []
            params = []
            for sub in where_filter['$and']:
                sql, p = self._build_filter(sub)
                if sql:
                    parts.append(sql)
                    params.extend(p)
            if parts:
                return f"({' AND '.join(parts)})", params
            return None, []

        # Simple key=value (only allow known columns to prevent injection)
        allowed_columns = {'channel_id', 'channel_name', 'user_id', 'user_name', 'workspace_id'}
        parts = []
        params = []
        for key, value in where_filter.items():
            if key in allowed_columns:
                parts.append(f"{key} = %s")
                params.append(value)

        if parts:
            return " AND ".join(parts), params
        return None, []

    def delete_message(self, workspace_id: str, slack_ts: str):
        """Delete a message from pgvector."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM message_vectors WHERE workspace_id = %s AND slack_ts = %s",
                    (workspace_id, slack_ts)
                )
                conn.commit()
            logger.debug(f"Deleted message {workspace_id}_{slack_ts}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete message: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def delete_workspace(self, workspace_id: str):
        """Delete all vectors for a workspace."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM message_vectors WHERE workspace_id = %s",
                    (workspace_id,)
                )
                conn.commit()
            logger.info(f"Deleted all vectors for workspace {workspace_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete workspace vectors: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def get_collection_stats(self, workspace_id: str) -> Dict:
        """Get statistics about a workspace's vectors."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM message_vectors WHERE workspace_id = %s",
                    (workspace_id,)
                )
                count = cur.fetchone()[0]
            return {
                'workspace_id': workspace_id,
                'collection_name': f"workspace_{workspace_id}_messages",
                'message_count': count
            }
        finally:
            DatabaseConnection.return_connection(conn)

    # --- Document chunk methods (used by document_service) ---

    def add_document_chunks(
        self,
        workspace_id: str,
        document_id: int,
        chunks: List[str],
        filename: str,
        org_id: int
    ):
        """
        Store document chunks as vectors. Replaces ChromaDB collection.upsert()
        for document indexing.
        """
        if not chunks:
            return

        embeddings = embed_texts(chunks)

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    cur.execute("""
                        INSERT INTO message_vectors
                            (workspace_id, content, embedding,
                             channel_name, user_name, slack_ts)
                        VALUES (%s, %s, %s::vector, %s, %s, %s)
                        ON CONFLICT (workspace_id, slack_ts)
                        DO UPDATE SET content = EXCLUDED.content,
                                      embedding = EXCLUDED.embedding
                    """, (
                        workspace_id or f"org_{org_id}",
                        chunk,
                        embedding,
                        f"doc:{filename}",
                        f"document:{document_id}",
                        f"doc_{document_id}_chunk_{i}"
                    ))
                conn.commit()
            logger.info(f"Stored {len(chunks)} chunks for document {document_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store document chunks: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def delete_document_chunks(self, document_id: int):
        """Delete all chunks for a document."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM message_vectors WHERE slack_ts LIKE %s",
                    (f"doc_{document_id}_chunk_%",)
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete document chunks: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)
