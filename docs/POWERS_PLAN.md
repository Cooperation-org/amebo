# Powers Plan — Expanding Amebo's Tool Inventory

The biggest practical gap between amebo and frameworks like OpenClaw is **tool inventory**. Amebo currently has abra, odoo-cli, and mcp-taiga. To meaningfully pursue goals — outreach, research, content drafting, repo work — the claw needs more powers.

This doc plans how to add them without bloating the codebase or locking into a heavy framework.

## Principles

1. **Lightweight preferred.** Native Python tools (~30 lines each) for anything we use a lot, where the implementation is small.
2. **MCP for established servers.** When a mature MCP server already does the job well, integrate it instead of reimplementing.
3. **Per-instance opt-in.** Every tool is gated by `instance.config.allowed_tools` — no instance gets a tool it didn't declare.
4. **Cost ceiling per goal.** Each tool call records an estimated cost on its `goal_event.metadata`. Goals can hit a configurable budget and stop.
5. **Compose, don't adopt.** No LangChain. No OpenClaw runtime. Just tools.

## Tool catalog (target inventory)

Marked: **N** = native Python, **MCP** = MCP server, **B** = built-in Anthropic tool.

| Tool | Approach | Why |
|---|---|---|
| `web_search` | **B** | Anthropic's hosted web search. Zero implementation. |
| `http_fetch` | **N** | Read a URL the user referenced. `requests` + safety filter. ~30 LOC. |
| `email_read` | **N** | IMAP fetch for an org's inbox. Read-only. ~80 LOC. |
| `email_draft` | **N** | Compose an email; HITL approval before send. ~40 LOC. |
| `email_send` | **N** | After approval. ~30 LOC. |
| `calendar_check` | **N** | Google Calendar API or CalDAV. Availability lookup. ~60 LOC. |
| `github_repo` | **MCP** | Read repos, issues, PRs. Existing `@modelcontextprotocol/server-github`. |
| `filesystem` | **MCP** | Read/write files inside the org's git worktree. Existing `@modelcontextprotocol/server-filesystem`. |
| `slack_post` | **N** | Wrap existing Slack bot token. Send to a channel. ~40 LOC. |
| `slack_read_channel` | **N** | Use existing Slack ingestion pipeline. ~30 LOC. |
| `claude_code` | **N** | Spawn Claude Code in a worktree for coding subtasks (see `ORGS_GOALS_CLAW.md`). ~100 LOC + sandbox. |
| `abra_search` | **(existing)** | Already wired. |
| `odoo_cli` | **(existing)** | Already wired. |

That's ~10 new tools to add. Roughly 5 native + 2 MCP + 1 built-in + 1 "code agent" — manageable.

## Patterns

### Native tool pattern

The existing `tools/registry.py` defines tools as JSON Schema + a Python function. New tools follow the same shape:

```python
HTTP_FETCH = {
    "name": "http_fetch",
    "description": "Fetch the contents of a public URL. Read-only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url":     {"type": "string", "format": "uri"},
            "max_kb":  {"type": "integer", "default": 256},
        },
        "required": ["url"],
    },
}

def http_fetch(url: str, max_kb: int = 256, **_) -> str:
    # safety: reject internal IPs, redirect limits, content-type filter
    ...
    return text_or_error
```

Tool functions get a `**kwargs` to absorb unknown fields safely — easier to evolve schemas without breaking callers.

### MCP integration pattern

Amebo will treat each MCP server as a subprocess managed at startup. Per-instance config decides which servers are launched:

```json
{
  "config": {
    "allowed_tools": ["abra", "http_fetch", "github_repo", "filesystem"],
    "mcp_servers": {
      "github_repo": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN_REF": "vault://orgs/{org_id}/github"}
      },
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{worktree_path}"]
      }
    }
  }
}
```

A small `mcp_client.py` module:
- Reads `mcp_servers` from instance config.
- Launches each as a subprocess on dispatcher startup (lazy — only when first tool call needs it).
- Translates Claude's tool calls into MCP protocol messages.
- Serializes MCP responses back as tool results.

This isolates MCP plumbing to one file. The rest of amebo doesn't know whether a tool is native or MCP — it just calls `execute_tool(name, input)`.

### Credential management

This is the biggest UX cliff in any agent product. Most amebo users are NOT on the shell — community organizers, activists, nonprofit staff. If credentials require copy-pasting a token from a developer console, most users will quit at that step. Designing this well is the difference between an org using amebo and not.

#### Which tools actually need per-org credentials

Not all of them. Map first:

| Tool | Needs per-org creds? | Notes |
|---|---|---|
| `web_search` (Anthropic built-in) | NO | Uses amebo's API key. |
| `http_fetch` | NO | Public URLs only. |
| `claude_code` subagent | NO | Uses amebo's Anthropic key, with a per-org cost meter. |
| `filesystem` (in a worktree) | NO | Filesystem permissions of the amebo process. |
| `abra_search` | NO | Scoped by `org_id` at query time. |
| `slack_post` / `slack_read` | YES | Per-org Slack bot install. |
| `email_*` | YES | Per-org mailbox. |
| `calendar_check` | YES | Per-org calendar account. |
| `github_repo` | YES | Per-org installation. |
| `odoo_cli` | YES (or shared for WhatsCookin) | Per-org CRM. |

About half need credentials. Worth being precise: a tool that doesn't need credentials shouldn't go through the credential flow at all.

#### Principles

1. **OAuth wherever possible.** Click "Connect Slack" / "Connect Google" / "Connect GitHub" in the web UI — never copy-paste a token. Slack, Google, GitHub, Microsoft all have mature OAuth. Most other major SaaS does too.
2. **Org admin manages credentials, not every member.** A "Connections" page on the org settings UI. Members can request new integrations; admins approve and connect. Most users never see a credential.
3. **Scoped tokens, least privilege.** When connecting GitHub, request `repo:read` on the specific repo, not full account. Each tool's docs declare its required scope.
4. **Envelope encryption at rest.** Vault key in env var, never in DB. Per-credential metadata only (kind, expires_at, last_used_at) is unencrypted.
5. **Visible revocation.** Org admin sees a "Connections" list with last-used timestamp and one-click disconnect. Disconnecting in amebo also revokes on the provider where the API supports it.
6. **Audit credential use** — `goal_events.metadata` records *which credential kind* was used (e.g. `{credential: "slack"}`), never the value. So you can answer "what did the claw use my Gmail token for in the last week?" by querying events.
7. **App install = credential.** When amebo is installed into a Slack workspace as a bot, that install IS the credential exchange. No separate "give me a token" step. Same model for GitHub App.
8. **Paste-token is a fallback, not a default.** Behind an "Advanced" expander. For obscure SaaS without OAuth, or self-hosted services. Most users should never see it.
9. **No credentials in goal config, ever.** Goals reference *credential kinds* (`{"send_via": "email"}`), never values. The credential is looked up at dispatch time from the org's vault.

#### Concrete flow (best case)

1. Org admin lands on `/settings/connections` in the amebo web UI.
2. Sees a list: "Slack — connected ✓", "Gmail — not connected", "GitHub — not connected".
3. Clicks "Connect Gmail" → redirects to Google OAuth → grants scopes → redirects back.
4. amebo stores the refreshed token, encrypted, in `org_credentials`.
5. From that moment, any tool that needs `kind = "gmail"` for that org can use it; goals reference it indirectly.
6. Admin can see "last used 3 hours ago by goal: outreach to Rackdog" and revoke if anything looks off.

#### Schema sketch

```sql
CREATE TABLE org_credentials (
    id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                  -- 'slack' | 'gmail' | 'github' | ...
    label TEXT,                          -- user-facing name ("Marketing Gmail")
    encrypted_value BYTEA NOT NULL,      -- Fernet-encrypted blob (token + refresh + scopes)
    expires_at TIMESTAMPTZ,
    granted_scopes TEXT[],
    connected_by_user_id INT REFERENCES platform_users(user_id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    UNIQUE (org_id, kind, label)         -- multiple Gmails per org possible
);
```

Multiple credentials of the same kind per org (e.g. two different Gmail mailboxes) supported via `label`. Goals can target a specific label or use the org default.

#### What we should NOT do

- **Per-user credentials managed in the chat UI.** A claw acts for the org, not for a chatting user. Asking users to paste their personal tokens into a chat thread is both insecure and confusing.
- **Plain-text storage anywhere.** Even briefly. Even in logs.
- **Shared credentials across orgs.** Each org's GitHub token must be isolated. The lookup is always keyed by `org_id`.
- **Trusting the model to handle credentials.** The model never sees raw tokens. The tool implementation fetches the credential, makes the API call, returns only the result.

#### Open questions

- **Which encryption library.** Python's `cryptography.fernet` is the lightweight default; AWS KMS / GCP KMS for production rotation. For VM 200's scale, Fernet with a key in env is fine for now.
- **Token refresh strategy.** Per-kind logic (Google refresh tokens, GitHub App tokens, Slack refresh tokens) — each provider differs. Wrap in a `CredentialResolver` so the tool code stays clean.
- **Per-tool scope verification.** Should amebo check that the stored token actually has the scope the tool needs before calling? Probably yes — surface a "reconnect this credential with broader scope" message in the UI rather than failing mid-goal.

## Order of work (recommended)

Phased so each step is independently shippable.

### Phase A: built-in + lightweight (no new infra)

1. Enable Anthropic's built-in `web_search` tool in the dispatcher's tool list.
2. Implement `http_fetch` (native).
3. Add `cost_estimate_usd` field to `goal_events.metadata`; record per call.

### Phase B: org credentials infra

4. Migration: `org_credentials` table — `(org_id, kind, encrypted_value, created_at)`.
5. CRUD route `/api/orgs/{id}/credentials/` (admin-only).
6. Credential lookup helper in `tools/credentials.py`.

### Phase C: comm tools

7. `email_read`, `email_draft`, `email_send` — with HITL flow for send (draft → approval → send is a 3-step state machine on the email itself, similar to goal lifecycle).
8. `slack_post`, `slack_read_channel` — wrap existing Slack plumbing.
9. `calendar_check` — Google Calendar or CalDAV.

### Phase D: MCP integration

10. Implement `mcp_client.py` — generic MCP subprocess manager.
11. Wire `github_repo` MCP server (read first, write gated by approval).
12. Wire `filesystem` MCP server, scoped to per-dispatch worktree.

### Phase E: code-touching

13. Implement `claude_code` tool (spawns Claude Code subagent in a worktree — see `ORGS_GOALS_CLAW.md` for the full pattern).
14. Add per-goal cost ceiling enforcement before dispatching `claude_code`.

## Security gates

- **No tool without `allowed_tools` opt-in** — instance config must explicitly list each tool.
- **No write/send/push without HITL flag** — email send, GitHub push, file write outside the worktree all require `goal.config.auto_approve_writes = true` (default: false).
- **Internal-network filter on `http_fetch`** — reject `10.0.0.0/8`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`, `192.168.0.0/16`.
- **Cost ceiling per goal** — config field, e.g. `goal.config.max_cost_usd = 0.50`. Dispatcher stops the loop when reached.
- **Audit every tool call** — `goal_events` already records `tool_call:<name>`. Extend to include input hash + cost estimate.

## Open questions

1. **MCP server lifecycle.** One process per (instance, server) is simple but RAM-heavy with many instances. Pooled servers per server-type might scale better but complicates credential isolation.
2. **Drafting vs sending for nontechnical orgs.** Per the amebo-summary, drafts should be reviewed before sending by default. Does that gate live on each tool, or as a global instance flag? Probably the latter — a `human_in_the_loop: true` on the instance applies to all write tools.
3. **MCP server versioning.** Pinning `npx @latest` is fragile in production. Pin specific versions in the config; bump on review.

## Scope guardrails

This is **not v1.x of the goals subsystem.** Goals v1 ships first (the current PR). The powers plan is a follow-on body of work, sequenced so each phase is independent and shippable.

Net target: ~10 new tools, organized so the claw can credibly pursue real goals — outreach, research, communications, coding subtasks — without amebo becoming a framework itself.
