"""
ChromaDB client for message content and vector storage.
"""

import os
import logging
from typing import List, Dict, Optional
import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class ChromaDBClient:
    """
    Manages ChromaDB collections for message content and embeddings.
    Uses collection-per-workspace strategy for data isolation.
    """

    def __init__(self, persist_directory: Optional[str] = None):
        """
        Initialize ChromaDB client.

        Args:
            persist_directory: Where to store ChromaDB data (defaults to ./chromadb_data)
        """
        self.persist_directory = persist_directory or os.getenv(
            'CHROMADB_PATH',
            './chromadb_data'
        )

        # Initialize ChromaDB with persistent storage
        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True  # For development
            )
        )

        logger.info(f"ChromaDB initialized at {self.persist_directory}")

    def get_or_create_collection(self, workspace_id: str):
        """
        Get or create a collection for a workspace.

        Args:
            workspace_id: Workspace ID

        Returns:
            ChromaDB collection
        """
        collection_name = f"workspace_{workspace_id}_messages"

        try:
            collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"workspace_id": workspace_id}
            )
            logger.info(f"Using collection: {collection_name}")
            return collection

        except Exception as e:
            logger.error(f"Failed to get/create collection {collection_name}: {e}")
            raise

    def add_message(
        self,
        workspace_id: str,
        message_id: int,
        slack_ts: str,
        message_text: str,
        metadata: Dict
    ) -> str:
        """
        Add a message to ChromaDB.

        Args:
            workspace_id: Workspace ID
            message_id: PostgreSQL message_id
            slack_ts: Slack timestamp
            message_text: Full message text
            metadata: Additional metadata (channel_id, user_id, timestamp, etc.)

        Returns:
            ChromaDB document ID
        """
        collection = self.get_or_create_collection(workspace_id)

        # ChromaDB document ID format: workspace_id_slack_ts
        doc_id = f"{workspace_id}_{slack_ts}"

        # Prepare metadata (all values must be strings, ints, or floats)
        chroma_metadata = {
            'message_id': str(message_id),
            'workspace_id': workspace_id,
            'channel_id': metadata.get('channel_id', ''),
            'user_id': metadata.get('user_id', ''),
            'timestamp': str(metadata.get('timestamp', '')),
            'thread_ts': metadata.get('thread_ts', ''),
            'message_type': metadata.get('message_type', 'regular'),
            'channel_name': metadata.get('channel_name', ''),
            'user_name': metadata.get('user_name', '')
        }

        try:
            collection.add(
                documents=[message_text],
                metadatas=[chroma_metadata],
                ids=[doc_id]
            )
            logger.debug(f"Added message {doc_id} to ChromaDB")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to add message {doc_id} to ChromaDB: {e}")
            raise

    def add_messages_batch(
        self,
        workspace_id: str,
        messages: List[Dict]
    ) -> List[str]:
        """
        Add multiple messages in batch (more efficient).

        Args:
            workspace_id: Workspace ID
            messages: List of message dicts with keys:
                      - message_id, slack_ts, text, metadata

        Returns:
            List of ChromaDB document IDs
        """
        if not messages:
            return []

        collection = self.get_or_create_collection(workspace_id)

        doc_ids = []
        documents = []
        metadatas = []

        for msg in messages:
            doc_id = f"{workspace_id}_{msg['slack_ts']}"
            doc_ids.append(doc_id)
            documents.append(msg['text'])

            chroma_metadata = {
                'message_id': str(msg['message_id']),
                'workspace_id': workspace_id,
                'channel_id': msg['metadata'].get('channel_id', ''),
                'user_id': msg['metadata'].get('user_id', ''),
                'timestamp': str(msg['metadata'].get('timestamp', '')),
                'thread_ts': msg['metadata'].get('thread_ts', ''),
                'message_type': msg['metadata'].get('message_type', 'regular'),
                'channel_name': msg['metadata'].get('channel_name', ''),
                'user_name': msg['metadata'].get('user_name', '')
            }
            metadatas.append(chroma_metadata)

        try:
            collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=doc_ids
            )
            logger.info(f"Added {len(doc_ids)} messages to ChromaDB in batch")
            return doc_ids

        except Exception as e:
            logger.error(f"Failed to add message batch to ChromaDB: {e}")
            raise

    def get_message(
        self,
        workspace_id: str,
        slack_ts: str
    ) -> Optional[Dict]:
        """
        Get a message by Slack timestamp.

        Args:
            workspace_id: Workspace ID
            slack_ts: Slack timestamp

        Returns:
            Dict with document, metadata or None
        """
        collection = self.get_or_create_collection(workspace_id)
        doc_id = f"{workspace_id}_{slack_ts}"

        try:
            result = collection.get(
                ids=[doc_id],
                include=['documents', 'metadatas']
            )

            if result['ids']:
                return {
                    'id': result['ids'][0],
                    'text': result['documents'][0],
                    'metadata': result['metadatas'][0]
                }
            return None

        except Exception as e:
            logger.error(f"Failed to get message {doc_id}: {e}")
            raise

    def search_messages(
        self,
        workspace_id: str,
        query_text: str,
        n_results: int = 10,
        where_filter: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Semantic search for messages.

        Args:
            workspace_id: Workspace ID (REQUIRED for security)
            query_text: Search query
            n_results: Number of results to return
            where_filter: Metadata filters (e.g., {'channel_id': 'C123'})

        Returns:
            List of matching messages with similarity scores
        """
        if not workspace_id:
            raise ValueError("workspace_id is REQUIRED for ChromaDB search")

        collection = self.get_or_create_collection(workspace_id)

        # SECURITY: ALWAYS filter by workspace_id, even though we have workspace-specific collections
        # This is defense-in-depth in case messages somehow end up in wrong collection
        if where_filter is None:
            where_filter = {}

        # Enforce workspace_id filter
        where_filter['workspace_id'] = workspace_id

        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter,
                include=['documents', 'metadatas', 'distances']
            )

            messages = []
            for i in range(len(results['ids'][0])):
                messages.append({
                    'id': results['ids'][0][i],
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i] if 'distances' in results else None
                })

            return messages

        except Exception as e:
            logger.error(f"Failed to search messages: {e}")
            raise

    def delete_message(
        self,
        workspace_id: str,
        slack_ts: str
    ):
        """
        Delete a message from ChromaDB.

        Args:
            workspace_id: Workspace ID
            slack_ts: Slack timestamp
        """
        collection = self.get_or_create_collection(workspace_id)
        doc_id = f"{workspace_id}_{slack_ts}"

        try:
            collection.delete(ids=[doc_id])
            logger.debug(f"Deleted message {doc_id} from ChromaDB")

        except Exception as e:
            logger.error(f"Failed to delete message {doc_id}: {e}")
            raise

    def delete_workspace(self, workspace_id: str):
        """
        Delete an entire workspace collection.

        Args:
            workspace_id: Workspace ID
        """
        collection_name = f"workspace_{workspace_id}_messages"

        try:
            self.client.delete_collection(name=collection_name)
            logger.info(f"Deleted collection: {collection_name}")

        except Exception as e:
            logger.error(f"Failed to delete collection {collection_name}: {e}")
            raise

    def get_collection_stats(self, workspace_id: str) -> Dict:
        """
        Get statistics about a workspace collection.

        Args:
            workspace_id: Workspace ID

        Returns:
            Dict with count, etc.
        """
        collection = self.get_or_create_collection(workspace_id)

        try:
            count = collection.count()
            return {
                'workspace_id': workspace_id,
                'collection_name': collection.name,
                'message_count': count
            }

        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            raise

    def list_collections(self) -> List[str]:
        """
        List all collections (workspaces).

        Returns:
            List of collection names
        """
        try:
            collections = self.client.list_collections()
            return [c.name for c in collections]

        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
            raise


if __name__ == "__main__":
    # Test ChromaDB client
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Testing ChromaDB client...\n")

    try:
        client = ChromaDBClient()

        # Test workspace
        workspace_id = "W_TEST123"

        # Add a test message
        print("1. Adding test message...")
        doc_id = client.add_message(
            workspace_id=workspace_id,
            message_id=1,
            slack_ts="1234567890.123456",
            message_text="This is a test message about deployment and authentication issues.",
            metadata={
                'channel_id': 'C123',
                'user_id': 'U456',
                'timestamp': '2025-10-30T12:00:00',
                'message_type': 'regular',
                'channel_name': 'engineering',
                'user_name': 'test_user'
            }
        )
        print(f"   Added message: {doc_id}\n")

        # Get the message
        print("2. Retrieving message...")
        message = client.get_message(workspace_id, "1234567890.123456")
        print(f"   Retrieved: {message['text'][:50]}...\n")

        # Search for messages
        print("3. Searching for 'deployment'...")
        results = client.search_messages(
            workspace_id=workspace_id,
            query_text="deployment problems",
            n_results=5
        )
        print(f"   Found {len(results)} results")
        if results:
            print(f"   Top result: {results[0]['text'][:50]}...\n")

        # Get stats
        print("4. Getting collection stats...")
        stats = client.get_collection_stats(workspace_id)
        print(f"   Collection: {stats['collection_name']}")
        print(f"   Messages: {stats['message_count']}\n")

        # Clean up
        print("5. Cleaning up test data...")
        client.delete_workspace(workspace_id)
        print("   Test workspace deleted\n")

        print("✅ All ChromaDB tests passed!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise
