# Amebo — Next Steps

> **Scope:** current feature priorities. The older rearchitect-branch roadmap is
> [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md) — kept for reference; the two should be
> reconciled when this work is picked up.

## 1. Per-Instance Tool Permissions

The `instances` table has a `config JSONB` column. Convention:

```json
{
  "allowed_tools": ["odoo-cli", "abra", "mcp-taiga"],
  "tool_config": {
    "odoo-cli": {"scope": "contacts,follow-ups,tags"},
    "abra": {"scope": "linkedtrust"}
  }
}
```

**Enforcement**: QA service checks `instance.config.allowed_tools` before invoking any CLI tool. Tools not in the list are never exposed to the model (not even mentioned in the system prompt). This prevents one instance from accessing another's CRM or task manager.

**WhatsCookin instance**: `allowed_tools: ["odoo-cli", "abra", "mcp-taiga"]`
**Default/other instances**: `allowed_tools: ["abra"]` (read-only knowledge search only)

### Implementation
- Add `get_allowed_tools(instance_id)` to `InstanceRepo`
- In `qa_service.py`, only include tool descriptions in the system prompt for allowed tools
- Tool execution layer validates against allowed list before running any subprocess

## 2. CLI Tool Integration (odoo-cli via Slack)

Wire `odoo-cli` as a tool that Claude can invoke when answering questions:

- User asks in Slack: "What contacts do we have at Mozilla?"
- Amebo recognizes this as a CRM query (via skills matching)
- If the instance has `odoo-cli` in `allowed_tools`, amebo runs `odoo-cli search contacts "Mozilla"` as a subprocess
- Result is included in the Claude API call as tool output
- Response goes back to Slack with CRM data

**Tools to integrate first:**
| Tool | Use case | Subprocess pattern |
|------|----------|-------------------|
| `odoo-cli` | Contact lookup, follow-ups, tags | `odoo-cli search contacts "query"` |
| `abra` | Knowledge base search | `abra search "query"`, `abra about name` |
| `mcp-taiga` | Task management | `mcp-taiga list`, `mcp-taiga create` |

### Implementation
- Define tool schemas (name, description, parameters) in a tools registry
- Use Claude's tool_use API: send tool definitions, get tool_use blocks back, execute, return results
- Subprocess execution with timeout (10s default), stdout capture, stderr logging
- Security: allowlist validation, no shell injection (use subprocess.run with list args, not shell=True)

## 3. CLI Shell (Claude Code-style REPL)

A terminal-based interactive shell for non-engineering work:

```
$ amebo
amebo> who did we meet last week about grants?
[searches abra, checks CRM, formats response]

amebo> add a follow-up for Sarah Chen next Tuesday
[runs odoo-cli to create follow-up]

amebo> what's the status of the claim lexicon project?
[searches abra projects, checks Taiga tasks]
```

**Key design points:**
- Same ConversationManager kernel (source_type='cli', source_ref=session_id)
- Same per-instance tool permissions
- readline/prompt_toolkit for input, streaming output
- Thread persists across the session, GC'd after 24h idle
- Instance selected by config file or `--instance` flag

## 4. Hub Web Interface Revival

Revive the hub project as a web frontend for amebo:

- Simple chat interface (like Claude.ai but for team knowledge)
- Thread persistence (source_type='web', source_ref=session_cookie)
- Instance selection per deployment
- ConversationManager handles all context management (the reason hub failed before was inefficient context — now solved)

## 5. Growth Engine Skills

Skills for nonprofits, organizers, activists, small businesses:

| Skill | Triggers | What it does |
|-------|----------|-------------|
| `outreach.md` | "who should we reach out to", "find contacts for" | Searches CRM + abra, suggests outreach targets |
| `follow-up.md` | "follow up with", "what's pending" | Checks CRM follow-ups, meeting notes |
| `grant-research.md` | "grants for", "funding for" | Searches knowledge base + web for relevant grants |
| `relationship-map.md` | "who knows", "connections to" | Maps relationships via abra bindings |
| `meeting-prep.md` | "meeting with X", "prep for" | Pulls all context about a person/org before a meeting |
| `campaign.md` | "campaign for", "organize around" | Helps plan outreach campaigns with contact segmentation |

## 6. Priority Order

1. **Per-instance tool permissions** — foundation for everything else
2. **odoo-cli integration** — immediate value for WhatsCookin Slack users
3. **abra + mcp-taiga integration** — complete the tool suite
4. **CLI shell** — power user interface
5. **Growth engine skills** — differentiated value
6. **Hub web interface** — broader accessibility
