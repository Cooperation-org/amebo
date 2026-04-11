"""
Channel contract — the boundary between communication channels and amebo's core.

Every channel (Slack, web, CLI, WhatsApp, Discord, etc.) must translate its
native events into these types before handing off to the agent core.
The core never imports channel-specific libraries.

Design influenced by openclaw's channel plugin SDK pattern:
- Channels are plugins that implement a contract
- All inbound messages become InboundEnvelope
- All outbound actions become OutboundAction
- Native features (reactions, buttons, threads) are expressed as capabilities

See docs/CHANNEL_CONTRACT.md for full design rationale.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ChannelType(str, Enum):
    """Known channel types. Extensible — new channels add a value here."""
    SLACK = "slack"
    WEB = "web"
    CLI = "cli"
    # Future: whatsapp, discord, signal, email, etc.


class MessageKind(str, Enum):
    """What kind of inbound message this is."""
    TEXT = "text"              # Regular message
    COMMAND = "command"        # Slash command or equivalent
    REACTION = "reaction"     # Emoji reaction
    THREAD_REPLY = "thread_reply"  # Reply in an existing thread
    SYSTEM = "system"         # Channel events (join, leave, topic change)


class ActionKind(str, Enum):
    """What the agent wants the channel to do."""
    REPLY = "reply"                    # Reply in thread/conversation
    SEND = "send"                      # New message to channel/user
    EPHEMERAL = "ephemeral"            # Visible only to one user
    UPDATE = "update"                  # Edit a previous message
    REACT = "react"                    # Add reaction
    CONFIRM = "confirm"                # Ask for confirmation before action
    TYPING = "typing"                  # Show typing indicator


class Capability(str, Enum):
    """
    What a channel can do. Adapters declare these so the core knows
    what's possible without trying and failing.

    Pattern from openclaw: channels contribute capability declarations
    at registration time, not at message time.
    """
    THREADS = "threads"                # Supports threaded replies
    REACTIONS = "reactions"            # Supports emoji reactions
    EPHEMERAL = "ephemeral"            # Supports user-only messages
    RICH_TEXT = "rich_text"            # Supports formatting (bold, links, etc.)
    EDIT_MESSAGE = "edit_message"      # Can edit previously sent messages
    BUTTONS = "buttons"                # Supports interactive buttons
    FILE_UPLOAD = "file_upload"        # Can send files/attachments
    TYPING_INDICATOR = "typing"        # Can show typing status


# ---------------------------------------------------------------------------
# Inbound: channel -> core
# ---------------------------------------------------------------------------

@dataclass
class SenderIdentity:
    """
    Who sent the message. Channel-agnostic identity.

    The channel adapter resolves native IDs (Slack user_id, web session, etc.)
    into this common shape. The core uses sender_id for thread tracking and
    display_name for prompts.
    """
    sender_id: str                  # Unique within channel (e.g., Slack user_id, session_id)
    display_name: str               # Human-readable name
    channel_type: ChannelType       # Which channel they're on
    raw_id: Optional[str] = None    # Original platform ID if different from sender_id
    metadata: Dict[str, Any] = field(default_factory=dict)  # Channel-specific extras


@dataclass
class InboundEnvelope:
    """
    A normalized inbound message from any channel.

    This is what the agent core receives. The channel adapter is responsible
    for constructing this from native events.

    Design principle (from openclaw): the envelope carries enough context
    for the core to do its job, but nothing channel-specific leaks through.
    Channel-specific data goes in metadata for logging/debugging only.

    Key fields:
    - thread_ref: The thread identity. For Slack this is thread_ts.
      For web this is session_id. For CLI this could be a session UUID.
      The core uses this as the ConversationManager's source_ref.
    - workspace_id: Tenant isolation key. Required.
    - text: The actual message content, already cleaned of channel markup.
      (e.g., Slack mentions <@U123> already resolved to @username)
    """
    # Identity
    sender: SenderIdentity
    channel_type: ChannelType
    workspace_id: str

    # Content
    text: str
    kind: MessageKind = MessageKind.TEXT

    # Threading
    thread_ref: Optional[str] = None      # Thread identity (creates new if None)
    reply_to_ref: Optional[str] = None    # Specific message being replied to

    # Context
    channel_name: Optional[str] = None    # e.g., #general, "DM", "web-chat"
    timestamp: Optional[datetime] = None
    instance_slug: Optional[str] = None   # Which amebo instance to route to

    # Channel-native extras (for logging, not for core logic)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def source_type(self) -> str:
        """For ConversationManager compatibility."""
        return self.channel_type.value

    @property
    def source_ref(self) -> str:
        """For ConversationManager compatibility. Falls back to a generated ID."""
        if self.thread_ref:
            return self.thread_ref
        # No thread context — generate one from sender + timestamp
        import uuid
        return str(uuid.uuid4())

    @property
    def author_info(self) -> str:
        """For ConversationManager compatibility."""
        return f"{self.channel_type.value}:{self.sender.sender_id}"


# ---------------------------------------------------------------------------
# Outbound: core -> channel
# ---------------------------------------------------------------------------

@dataclass
class OutboundAction:
    """
    An action the agent wants to perform through a channel.

    The core constructs these. The channel adapter translates them into
    native API calls (Slack blocks, web JSON responses, CLI stdout, etc.).

    Design principle (from openclaw's native approval rendering):
    the core expresses *intent* ("confirm this action"), the channel
    adapter renders it natively (Slack buttons, CLI y/n prompt, web modal).
    """
    kind: ActionKind
    text: str                              # The content to send
    thread_ref: Optional[str] = None       # Which thread to act in
    target_message_ref: Optional[str] = None  # For UPDATE/REACT: which message
    recipient_id: Optional[str] = None     # For EPHEMERAL/SEND: who to send to
    channel_name: Optional[str] = None     # Where to send (if not replying)

    # For CONFIRM actions
    confirm_prompt: Optional[str] = None   # What are we confirming?
    confirm_action: Optional[str] = None   # Description of what happens on yes

    # Formatting hints (channel adapters interpret these natively)
    format_hints: Dict[str, Any] = field(default_factory=dict)
    # Examples:
    #   {"sources": [...], "confidence": 85}  -> channel renders source footer
    #   {"blocks": [...]}                     -> Slack-specific block override
    #   {"code": True}                        -> render as code block

    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Channel adapter interface
# ---------------------------------------------------------------------------

class ChannelAdapter:
    """
    Base interface for channel adapters.

    Each channel (Slack, web, CLI) implements this. The core calls
    send() to dispatch outbound actions. Inbound flow is channel-specific
    (Slack uses Socket Mode events, web uses HTTP, CLI uses stdin) but
    always produces InboundEnvelope instances.

    Pattern from openclaw: the adapter boundary is strict.
    Adapters import from this contract module. They never import from
    services/, tools/, or other adapters. The core never imports from adapters.

    Lifecycle:
    1. Adapter is created with channel-specific credentials/config
    2. Adapter declares its capabilities
    3. Adapter starts listening (channel-specific)
    4. Inbound events -> InboundEnvelope -> core handles -> OutboundAction
    5. Adapter.send(action) -> native API call
    """

    channel_type: ChannelType

    def capabilities(self) -> List[Capability]:
        """
        Declare what this channel supports.

        The core checks capabilities before constructing actions.
        e.g., won't send EPHEMERAL if channel doesn't support it.
        """
        raise NotImplementedError

    async def send(self, action: OutboundAction) -> Optional[str]:
        """
        Execute an outbound action through this channel.

        Returns a message reference (e.g., Slack ts) if applicable,
        for use in future UPDATE or REACT actions.
        """
        raise NotImplementedError

    async def start(self):
        """Start listening for inbound events. Channel-specific."""
        raise NotImplementedError

    async def stop(self):
        """Graceful shutdown."""
        raise NotImplementedError
