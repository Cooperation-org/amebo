# Channel Contract — Design & Migration Guide

## What This Is

A channel abstraction layer that decouples amebo's agent core from any
specific communication platform. The core never imports Slack SDK, never
formats mrkdwn, never calls `chat_postMessage`. It works with normalized
`InboundEnvelope` and `OutboundAction` types.

**Location:** `backend/src/channels/`

**Files:**
- `contract.py` — Types, enums, ChannelAdapter interface
- `slack_adapter.py` — Slack implementation (wraps existing services)
- `web_adapter.py` — Web/HTTP implementation (for dashboard chat)
- `dispatch.py` — Routes envelopes to QAService, returns actions

## Why

The existing code has Slack-specific logic woven through three places:
- `slack_commands.py` — handles slash commands, app mentions, formats responses
- `slack_bot_service.py` — alternative Bolt-based handler (partially overlapping)
- `chat.py` route — web chat endpoint, already somewhat channel-agnostic

Adding any new channel (CLI, WhatsApp, Discord) currently means duplicating
all the QAService wiring and response formatting. The contract eliminates that.

## Architecture

```
Channel (Slack, Web, CLI, ...)
    │
    ▼ produces
InboundEnvelope (normalized message)
    │
    ▼ passed to
dispatch.handle_envelope()
    │
    ▼ calls
QAService.answer_question() (unchanged)
    │
    ▼ returns
OutboundAction (what to say, how to say it)
    │
    ▼ delivered by
ChannelAdapter.send() (channel-native rendering)
```

The dispatch layer is thin. It normalizes the QAService result into an
OutboundAction and lets the channel adapter render it natively.

## Key Types

### InboundEnvelope

What the core receives from any channel. Key fields:

| Field | Purpose |
|-------|---------|
| `sender` | Who sent it (SenderIdentity with id, name, channel type) |
| `channel_type` | Which channel (slack, web, cli, ...) |
| `workspace_id` | Tenant isolation key |
| `text` | Clean message text (channel markup already resolved) |
| `kind` | What kind: text, command, reaction, thread_reply, system |
| `thread_ref` | Thread identity (Slack thread_ts, web session_id, CLI session) |
| `instance_slug` | Which amebo instance to route to |
| `metadata` | Channel-specific extras for logging only |

Properties `source_type`, `source_ref`, `author_info` provide backward
compatibility with ConversationManager's existing interface.

### OutboundAction

What the core wants the channel to do. Key fields:

| Field | Purpose |
|-------|---------|
| `kind` | What to do: reply, send, ephemeral, update, react, confirm |
| `text` | The content |
| `thread_ref` | Which thread to act in |
| `format_hints` | Rendering hints (sources, confidence, code blocks) |
| `confirm_prompt` | For CONFIRM actions: what we're asking about |

### ChannelAdapter

Interface that every channel implements:
- `capabilities()` — What the channel supports (threads, reactions, etc.)
- `send(action)` — Deliver an outbound action through native APIs
- `start()` / `stop()` — Lifecycle

### Capability

Declared by adapters so the core can check what's possible:
- THREADS, REACTIONS, EPHEMERAL, RICH_TEXT, EDIT_MESSAGE, BUTTONS, etc.

## Patterns Learned from OpenClaw

These patterns informed the design. OpenClaw's source is NOT a dependency
and is NOT available on the server. Everything useful is captured here.

### 1. Two-Face Commands

OpenClaw defines every command with both a **text face** and a **native face**:

```
CommandEntry:
  name: "model"                    # Internal name
  nativeName: "Model Selection"    # How Discord/WhatsApp renders it
  textAliases: ["/model", "!model"]  # Text command variants
  scope: "both"                    # Available in text and native
```

**What this means for amebo:** When we add commands (not just /ask, but things
like /status, /task, /contact), define them once in a registry with:
- A canonical name
- Text trigger(s) for channels that use text commands (Slack slash, CLI)
- Native rendering hints for channels that have their own command UI

The existing skills system (`prompts/skills/*.md` with trigger matching)
is already partway there — skills match on text patterns. The next step
is making skills also declare how they want to appear as native commands
in each channel.

### 2. Envelope Normalization

OpenClaw's inbound flow:
1. Channel receives native event (Discord interaction, Slack event, etc.)
2. Adapter resolves sender identity and session targets
3. Creates an `InboundEnvelope` with all context
4. Routes to agent core — which never sees raw platform payloads

**What we adopted:** `InboundEnvelope` in `contract.py`. The Slack adapter
resolves user IDs to names, strips bot mentions, extracts thread_ts — all
before the core sees it. The web adapter does the same from HTTP request fields.

### 3. Plugin SDK Boundary

OpenClaw is rigorous about what plugins can import:
- Plugins import ONLY from `plugin-sdk/` (the contract)
- Never from `src/` internals or from other plugins
- The SDK defines the entire surface area available to channels

**What this means for amebo:** Channel adapters should import ONLY from
`channels/contract.py`. They should NOT import from `services/`, `tools/`,
or `db/`. If an adapter needs something, it should be available through
the dispatch layer or through the contract types.

Current violations to fix during migration:
- `slack_commands.py` directly imports QAService
- `slack_commands.py` directly queries the database for org_id
- `chat.py` directly imports QAService and InstanceRepo

After migration, these callers go through `dispatch.handle_envelope()` instead.

### 4. Native Approval Rendering

OpenClaw's `approval-native-helpers.ts` pattern:
- The core decides "I need user confirmation for this action"
- It creates a CONFIRM action with the prompt and action description
- Each channel adapter renders the confirmation natively:
  - Discord: interactive buttons
  - Slack: interactive message with approve/deny
  - CLI: y/n prompt
  - Web: modal dialog

**What we adopted:** `ActionKind.CONFIRM` in the outbound contract. The
`confirm_prompt` and `confirm_action` fields carry the intent. Each adapter
renders it appropriately. The Slack adapter currently renders as text; future
work can add Slack Block Kit interactive buttons.

This matters for the tool permission model: when Claude wants to create a
Taiga task or update a CRM contact, amebo should ask the user first. The
confirmation flow needs to feel native to wherever they are.

### 5. Capability Declaration

OpenClaw channels declare capabilities at registration time. The gateway
checks capabilities before routing certain action types. e.g., it won't
try to send buttons to a channel that doesn't support them.

**What we adopted:** `Capability` enum and `ChannelAdapter.capabilities()`.
The dispatch layer can check `Capability.EPHEMERAL in adapter.capabilities()`
before trying to send an ephemeral message, falling back to a regular
reply if not supported.

### 6. Session Target Resolution

OpenClaw resolves "where should the response go?" as a separate step from
"what is the response?" — the `resolveNativeCommandSessionTargets()` function
maps native commands to the right session/thread.

**What this means for amebo:** The `thread_ref` in InboundEnvelope already
handles this. For Slack, it's thread_ts. For web, it's session_id. For CLI,
it'll be a session UUID. The ConversationManager uses `source_type + source_ref`
which maps directly to `envelope.source_type + envelope.source_ref`.

## Migration Plan

### Phase 1: Contract + Adapters (DONE - local)

✅ `contract.py` — types and interface
✅ `slack_adapter.py` — Slack envelope construction and outbound delivery
✅ `web_adapter.py` — Web envelope construction
✅ `dispatch.py` — Routes envelopes to QAService

### Phase 2: Wire Slack through contract (server)

Update `slack_commands.py` to use the adapter and dispatch:

```python
# BEFORE (current):
async def process_events(client, req):
    event = req.payload["event"]
    if event["type"] == "app_mention":
        user_id = event["user"]
        text = event["text"]
        # ... 30 lines of Slack-specific handling ...
        qa_service = QAService(workspace_id=WORKSPACE_ID)
        result = qa_service.answer_question(...)
        await web_client.chat_postMessage(...)

# AFTER (with contract):
async def process_events(client, req):
    event = req.payload["event"]
    if event["type"] == "app_mention":
        adapter = SlackAdapter(BOT_TOKEN, WORKSPACE_ID)
        envelope = await adapter.envelope_from_mention(event)
        action = await handle_envelope(envelope, adapter)
        await adapter.send(action)
```

The QAService, ConversationManager, and tool registry are UNCHANGED.
Only the wiring at the edges changes.

**Files to modify on server:**
- `slack_commands.py` — Replace process_events, handle_ask, handle_app_mention
  with adapter + dispatch calls
- `chat.py` — Replace direct QAService call with WebAdapter + dispatch
- `main.py` — No changes needed yet (adapter wraps, doesn't replace Socket Mode)

### Phase 3: Wire web chat through contract (server)

Update `chat.py` route to use WebAdapter:

```python
# BEFORE:
qa_service = QAService(workspace_id=workspace_id, org_id=...)
result = qa_service.answer_question(...)
return ChatResponse(reply=result['answer'], ...)

# AFTER:
adapter = WebAdapter()
envelope = adapter.envelope_from_request(req.message, req.session_id, req.instance_slug)
action = await handle_envelope(envelope, adapter)
return ChatResponse(reply=action.text, session_id=envelope.source_ref, ...)
```

### Phase 4: CLI adapter (future)

When the CLI shell is built, it'll be a third adapter:
- `cli_adapter.py` — reads from stdin, writes to stdout
- Declares capabilities: RICH_TEXT (terminal formatting), no THREADS
- Thread ref is a session UUID for the CLI session
- CONFIRM actions render as y/n prompts

### Phase 5: Response formatting cleanup (future)

Currently, Slack formatting (mrkdwn, emoji stripping, `**` -> `*` conversion)
happens in THREE places:
- `qa_service.py` lines 811-815 (in the agentic path)
- `slack_commands.py` (in handle_ask)
- `slack_adapter.py` (in _format_for_slack)

After full migration, ALL channel-specific formatting lives ONLY in adapters.
The QAService returns clean text; the adapter formats it for the channel.

## Testing

The contract types are pure Python dataclasses — no external dependencies.
You can test the dispatch flow with mock envelopes:

```python
from src.channels.contract import InboundEnvelope, ChannelType, MessageKind, SenderIdentity
from src.channels.dispatch import handle_envelope

envelope = InboundEnvelope(
    sender=SenderIdentity("test-user", "Test", ChannelType.WEB),
    channel_type=ChannelType.WEB,
    workspace_id="test-workspace",
    text="What projects are we working on?",
    kind=MessageKind.TEXT,
    thread_ref="test-session-1",
)

action = await handle_envelope(envelope)
print(action.text)  # The agent's response
print(action.kind)  # ActionKind.REPLY
```

The Slack adapter requires a live Slack connection to test send().
The envelope_from_* methods can be tested with mock event dicts.

## What NOT to Do

- Do NOT import channel adapters from the core (services/, tools/, db/)
- Do NOT put channel-specific formatting in QAService or dispatch
- Do NOT add openclaw as a dependency — patterns are captured here
- Do NOT build a plugin system — adapters are just Python modules
- Do NOT change QAService or ConversationManager in Phase 2-3 — only the wiring
