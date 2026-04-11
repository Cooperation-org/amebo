# Next Steps — Rearchitect Branch

Work continues on the Ubuntu server. All design docs and code are on the
`rearchitect` branch. Pull before starting.

## Context

We are building a community assistant (amebo) that helps non-engineers
work cooperatively through tools they already use (Slack, web, future channels).
The architecture draws patterns from Claude Code (tool harness, agentic loop,
context management) and openclaw (channel normalization, native rendering).

### What exists now (rearchitect branch)

- **Channel contract** (`backend/src/channels/`) — InboundEnvelope, OutboundAction,
  ChannelAdapter interface, Slack and Web adapters, dispatch layer.
  Design doc: `docs/CHANNEL_CONTRACT.md`

- **Tool registry** (`backend/src/tools/registry.py`) — Tools as dataclasses with
  `is_read_only`, `needs_confirmation`, `category`. Self-registering.
  Same external API — QAService callers unchanged.

- **abra-lib** (`abra` repo, `lib/`) — PyPI package extracting abra's core API.
  AbraStore with injection for connections, embeddings, tenancy, PII, search ranking.
  Design doc: `docs/ABRA_INTEGRATION.md`

- **Conversation manager** (`backend/src/services/conversation_manager.py`) —
  Thread-based state, compaction, prompt caching. Already channel-agnostic.

- **QAService** (`backend/src/services/qa_service.py`) — Agentic loop with tool
  use. Unchanged by this work — the new layers sit in front of it.

### Key design docs (read these first on the server)

- `docs/CHANNEL_CONTRACT.md` — channel layer design, openclaw patterns, migration steps with before/after code
- `docs/ABRA_INTEGRATION.md` — how amebo consumes abra-lib, AmeboStore subclass, migration steps
- `abra` repo `lib/README.md` — abra-lib usage and override examples

## Next Steps

### 1. Wire Slack through channel contract

**Where:** `backend/src/services/slack_commands.py`
**What:** Replace direct QAService calls with adapter + dispatch.
**How:** See Phase 2 in `docs/CHANNEL_CONTRACT.md` — has before/after code.
**Test:** Bot mention in Slack should work identically.

### 2. Wire web chat through channel contract

**Where:** `backend/src/api/routes/chat.py`
**What:** Replace direct QAService call with WebAdapter + dispatch.
**How:** See Phase 3 in `docs/CHANNEL_CONTRACT.md`.
**Test:** Web chat should work identically.

### 3. Install abra-lib and replace binding_repo.py

**Where:** `backend/src/db/repositories/binding_repo.py`, `backend/src/services/binding_service.py`
**What:** `pip install -e /opt/shared/repos/abra/lib` (or from PyPI once published).
  Create `AmeboStore(AbraStore)` subclass with project doc boosting.
  Update `binding_service.py` to use `AmeboStore` instead of `BindingRepo`.
  Delete `binding_repo.py`.
**How:** See `docs/ABRA_INTEGRATION.md` — has the full AmeboStore code.
**Test:** `/ask` queries, `lookup_contact` tool, `search_knowledge_base` tool.

### 4. Pass abra store in tool execution context

**Where:** `backend/src/tools/registry.py`, `backend/src/services/qa_service.py`
**What:** Add `store` to the context dict passed to `tool.execute()`.
  Any tool can then do `context["store"].bindings_for("peter")`.
**Why:** Tools like odoo_cli and mcp_taiga can resolve pet names before querying external systems.

### 5. Hot tags in system prompt

**Where:** `backend/src/services/conversation_manager.py`
**What:** Pre-fetch hot-tagged names' bindings and include them in the system prompt.
  The assistant proactively knows about priority items without being asked.
**Why:** This is where "shared vision and values" lives — hot tags reflect what matters now.

### 6. Move response formatting into channel adapters

**Where:** `backend/src/services/qa_service.py` lines 811-815, `backend/src/channels/slack_adapter.py`
**What:** Remove Slack-specific formatting (mrkdwn, emoji stripping, `**` → `*`)
  from QAService. Let the channel adapter handle it via `format_hints`.
**Why:** QAService should return clean text. Channel-native rendering is the adapter's job.

### 7. Publish abra-lib to PyPI (when ready)

**Where:** `abra` repo `lib/`
**What:** `python -m build && twine upload dist/*`
**When:** After testing the integration on the server with `pip install -e`.

## Not Yet / Future

- **CLI adapter** — third channel for terminal use. Low effort once contract is wired.
- **Skills as commands** — skills declaring native command representations per channel.
- **Confirmation flow** — tools with `needs_confirmation=True` sending CONFIRM actions
  through the channel contract before executing.
- **Role-based tool access** — using `is_read_only` to filter tools by user role.
