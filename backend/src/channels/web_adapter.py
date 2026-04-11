"""
Web channel adapter — translates between HTTP chat API and the channel contract.

The web adapter is the simplest: inbound comes from the FastAPI chat route
as already-clean text, outbound is just a return value (no push needed).
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, List

from src.channels.contract import (
    ChannelAdapter, ChannelType, Capability,
    InboundEnvelope, OutboundAction, ActionKind, MessageKind,
    SenderIdentity,
)

logger = logging.getLogger(__name__)


class WebAdapter(ChannelAdapter):
    """
    Web channel adapter.

    Simpler than Slack: no push, no threads (session_id serves as thread),
    no reactions. Responses are returned synchronously from the API handler.
    """

    channel_type = ChannelType.WEB

    def capabilities(self) -> List[Capability]:
        return [
            Capability.RICH_TEXT,
        ]

    def envelope_from_request(
        self,
        message: str,
        session_id: Optional[str] = None,
        instance_slug: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> InboundEnvelope:
        """
        Convert a web chat API request into an InboundEnvelope.

        Called from the chat.py route handler.
        """
        sid = session_id or str(uuid.uuid4())

        sender = SenderIdentity(
            sender_id=user_id or f"web-{sid[:8]}",
            display_name="Web User",
            channel_type=ChannelType.WEB,
        )

        workspace_id = f"web-{instance_slug}" if instance_slug else "web-default"

        return InboundEnvelope(
            sender=sender,
            channel_type=ChannelType.WEB,
            workspace_id=workspace_id,
            text=message,
            kind=MessageKind.TEXT,
            thread_ref=sid,
            instance_slug=instance_slug,
            timestamp=datetime.now(),
        )

    async def send(self, action: OutboundAction) -> Optional[str]:
        """
        Web adapter doesn't push. Responses are returned from the API handler.
        This is a no-op; the dispatch layer returns the action text directly.
        """
        return None

    async def start(self):
        pass

    async def stop(self):
        pass
