"""
Channel dispatch — routes InboundEnvelopes to the agent core and
delivers OutboundActions back through the right channel adapter.

This is the seam between channels and the QAService/ConversationManager.
It replaces the direct coupling between slack_commands.py and QAService.

The dispatch layer:
1. Receives an InboundEnvelope from any channel adapter
2. Calls QAService.answer_question with normalized args
3. Wraps the result in an OutboundAction
4. Returns it (the caller — channel adapter or route handler — delivers it)

This keeps the core completely channel-agnostic.
"""

import logging
from typing import Dict, Optional

from src.channels.contract import (
    InboundEnvelope, OutboundAction, ActionKind, MessageKind, Capability,
    ChannelAdapter,
)

logger = logging.getLogger(__name__)


async def handle_envelope(
    envelope: InboundEnvelope,
    adapter: Optional[ChannelAdapter] = None,
) -> OutboundAction:
    """
    Process an inbound message through the agent core and return an outbound action.

    This is the main entry point that all channels use.

    Args:
        envelope: Normalized inbound message from any channel
        adapter: The channel adapter (used to check capabilities and deliver)

    Returns:
        OutboundAction with the agent's response
    """
    from src.services.qa_service import QAService

    logger.info(
        f"Dispatch: {envelope.channel_type.value} "
        f"from={envelope.sender.display_name} "
        f"kind={envelope.kind.value} "
        f"thread={envelope.thread_ref}"
    )

    # Handle greetings (channel-agnostic)
    if _is_greeting(envelope.text):
        return _greeting_response(envelope)

    # Handle empty messages
    if not envelope.text.strip():
        return OutboundAction(
            kind=ActionKind.REPLY if envelope.thread_ref else ActionKind.SEND,
            text="Please provide a question.",
            thread_ref=envelope.thread_ref,
            metadata=envelope.metadata,
        )

    # Route to QAService
    try:
        qa_service = QAService(
            workspace_id=envelope.workspace_id,
            org_id=_resolve_org_id(envelope),
        )

        # Determine path: agentic (with thread) vs legacy (slash command)
        if envelope.thread_ref and envelope.kind != MessageKind.COMMAND:
            # Agentic path — full thread context
            result = qa_service.answer_question(
                question=envelope.text,
                thread_ref=envelope.source_ref,
                source_type=envelope.source_type,
                author_info=envelope.author_info,
                instance_slug=envelope.instance_slug,
            )
        else:
            # Legacy/stateless path — single question
            result = qa_service.answer_question(
                question=envelope.text,
                n_context_messages=10,
            )

        return _result_to_action(result, envelope, adapter)

    except Exception as e:
        logger.error(f"Dispatch error: {e}", exc_info=True)
        return OutboundAction(
            kind=ActionKind.REPLY if envelope.thread_ref else ActionKind.SEND,
            text=f"Sorry, I encountered an error: {str(e)}",
            thread_ref=envelope.thread_ref,
            metadata=envelope.metadata,
        )


def _is_greeting(text: str) -> bool:
    """Check if message is a simple greeting."""
    return text.strip().lower() in ('hi', 'hello', 'hey', 'sup', '')


def _greeting_response(envelope: InboundEnvelope) -> OutboundAction:
    """Build a greeting response."""
    name = envelope.sender.display_name
    return OutboundAction(
        kind=ActionKind.REPLY if envelope.thread_ref else ActionKind.SEND,
        text=(
            f"Hi {name}! Ask me anything about the team's work, projects, "
            f"or conversations."
        ),
        thread_ref=envelope.thread_ref,
        metadata=envelope.metadata,
    )


def _result_to_action(
    result: Dict,
    envelope: InboundEnvelope,
    adapter: Optional[ChannelAdapter] = None,
) -> OutboundAction:
    """Convert QAService result dict into an OutboundAction."""
    answer = result.get('answer', 'Sorry, I could not generate a response.')
    sources = result.get('sources', [])
    confidence = result.get('confidence', 50)

    # Determine action kind based on original message
    if envelope.kind == MessageKind.COMMAND:
        # Slash commands: check metadata for privacy preference
        is_private = envelope.metadata.get("private", True)
        kind = ActionKind.EPHEMERAL if is_private else ActionKind.SEND
    elif envelope.thread_ref:
        kind = ActionKind.REPLY
    else:
        kind = ActionKind.SEND

    # Build format hints (channel adapters interpret these natively)
    format_hints = {}
    if sources:
        format_hints["sources"] = sources
    if confidence:
        format_hints["confidence"] = confidence

    return OutboundAction(
        kind=kind,
        text=answer,
        thread_ref=envelope.thread_ref,
        recipient_id=envelope.sender.sender_id if kind == ActionKind.EPHEMERAL else None,
        format_hints=format_hints,
        metadata=envelope.metadata,
    )


def _resolve_org_id(envelope: InboundEnvelope) -> Optional[int]:
    """
    Resolve org_id from envelope context.
    For now, looks up from workspace_id. Could also come from instance config.
    """
    try:
        from src.db.connection import DatabaseConnection
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id FROM org_workspaces WHERE workspace_id = %s LIMIT 1",
                    (envelope.workspace_id,)
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)
    except Exception:
        return None
