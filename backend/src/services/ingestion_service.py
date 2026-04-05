"""
Source-agnostic content ingestion.

Any source (Slack, documents, Discord, email, manual) calls ingest_content()
to store content as a vector and optionally create bindings.
"""

import logging
from typing import List, Dict, Optional
from src.db.pgvector_client import PgvectorClient
from src.db.repositories.binding_repo import BindingRepo

logger = logging.getLogger(__name__)


def ingest_content(
    org_id: int,
    workspace_id: str,
    content: str,
    metadata: Dict,
    bindings: Optional[List[Dict]] = None
) -> str:
    """
    Store content as a vector and optionally create bindings.

    Args:
        org_id: Organization ID
        workspace_id: Workspace ID
        content: The text content to store
        metadata: Source metadata. Expected keys:
            - source_type: 'slack', 'document', 'discord', 'email', 'manual'
            - author: who created the content
            - channel: where it came from (channel name, email thread, etc.)
            - timestamp: when it was created (slack_ts or ISO string)
            - message_id: optional DB message ID
        bindings: Optional list of pre-extracted bindings to create. Each dict:
            - scope, name, relationship, target_type, target_ref
            - qualifier (optional), permanence (optional)

    Returns:
        Document ID string
    """
    pgvector = PgvectorClient()

    # Derive a unique ID for this content
    ts = metadata.get('timestamp', '')
    source_type = metadata.get('source_type', 'unknown')
    content_id = f"{source_type}_{ts}" if ts else f"{source_type}_{hash(content) % 10**8}"

    # Store the vector
    doc_id = pgvector.add_message(
        workspace_id=workspace_id,
        message_id=metadata.get('message_id'),
        slack_ts=content_id,
        message_text=content,
        metadata={
            'channel_id': metadata.get('channel_id', ''),
            'channel_name': metadata.get('channel', ''),
            'user_id': metadata.get('author_id', ''),
            'user_name': metadata.get('author', ''),
            'timestamp': ts
        }
    )

    # Create bindings if provided
    if bindings and org_id:
        try:
            repo = BindingRepo(org_id)
            for b in bindings:
                repo.create_binding(
                    scope=b['scope'],
                    name=b['name'],
                    relationship=b['relationship'],
                    target_type=b['target_type'],
                    target_ref=b['target_ref'],
                    qualifier=b.get('qualifier'),
                    permanence=b.get('permanence', 'CURRENT'),
                    workspace_id=workspace_id
                )
            logger.info(f"Created {len(bindings)} bindings for {doc_id}")
        except Exception as e:
            logger.warning(f"Failed to create bindings for {doc_id}: {e}")

    logger.info(f"Ingested content: {doc_id} ({source_type}, {len(content)} chars)")
    return doc_id
