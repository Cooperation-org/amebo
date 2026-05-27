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

#### Concrete flow (best case — admin already in the web UI)

1. Org admin lands on `/settings/connections` in the amebo web UI.
2. Sees a list: "Slack — connected ✓", "Gmail — not connected", "GitHub — not connected".
3. Clicks "Connect Gmail" → redirects to Google OAuth → grants scopes → redirects back.
4. amebo stores the refreshed token, encrypted, in `org_credentials`.
5. From that moment, any tool that needs `kind = "gmail"` for that org can use it; goals reference it indirectly.
6. Admin can see "last used 3 hours ago by goal: outreach to Rackdog" and revoke if anything looks off.

#### The real common case — user is in chat, not in a browser

Most amebo users live in Slack / email / Signal / web chat, not the settings UI. Asking them to "go log into the web app" mid-conversation is the failure mode that kills chat-agent products. The flow has to start where the user is.

**Pattern: amebo sends back an OAuth link through the channel the user is on.**

Example, user in Slack:

> **User:** post our values statement to LinkedIn
> **amebo:** I can do that, but I don't have LinkedIn access for this org yet. To connect it, click here (admin only, expires in 15 min): `https://amebo.linkedtrust.us/connect/<one-time-token>`. After you connect, send the message again and I'll post it.

Same intent over email — same flow, plain hyperlink instead of a button. Same over Signal — short link (we own a URL shortener). The channel adapter formats the message; the underlying flow is identical.

**Mechanics:**

1. **Tool call detects missing credential.** Tool function calls `credentials.client(org_id, kind="linkedin")`, which raises `CredentialMissing(kind="linkedin")` because no row exists or the row is revoked.
2. **Dispatcher catches it and produces a connect URL.** A `ConnectLinkBuilder` mints a signed, single-use, time-limited URL embedding:
   - `org_id`
   - `kind` (linkedin)
   - `reply_to` (channel + thread reference to notify on completion)
   - `requested_by` (user id of the asker; if they aren't admin, the link is still good for forwarding to admin)
   - `expires_at` (15 min default)
3. **Reply goes back through the same channel adapter** that received the original message. No assumption about web UI.
4. **User clicks the link.** Browser hits `/connect/<token>` on amebo's web frontend. The endpoint:
   - Validates token (signature + not-expired + not-already-used).
   - Verifies the user has admin role on `org_id` (login-required at this point).
   - Redirects to the provider's OAuth consent screen with the right scopes.
5. **Provider redirects back to `/connect/callback`.** amebo stores the credential, marks the connect link "consumed".
6. **amebo notifies the original channel/thread**: "LinkedIn is connected. You can re-send your message."
7. **(Optional) auto-resume:** if the original request was wrapped in a goal, the goal's status moves from `pending` → ready-for-tick, and the next scheduler tick re-runs it. For ad-hoc chat requests, we don't auto-resume — re-asking is fine.

#### Goal-side: "blocked on credential"

When the claw is pursuing a goal autonomously (not in response to a live chat turn) and hits a missing credential, the flow is different — there's no user in the chat to click the link at that moment.

1. Goal moves to a new pseudo-status (`blocked_on_credential`) — or stays `active` with an event `blocked_on_credential:<kind>`.
2. amebo notifies `goal.notify_channel` (or the org admin default) with the same kind of connect link.
3. After connection, the goal auto-resumes on the next tick.

For v1 we encode this as a `goal_events` row with action `blocked_on_credential:<kind>` and metadata containing the link's short_code. The status stays `active` (since we don't have a `blocked` state in the enum); the scheduler checks for an unblocked credential before dispatching. Cleaner than adding a new status; revisit if it gets gnarly.

#### Connect-link schema

```sql
CREATE TABLE connect_links (
    short_code TEXT PRIMARY KEY,           -- random url-safe 16 chars
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                    -- 'gmail', 'linkedin', etc.
    reply_channel TEXT,                    -- 'slack:Cxxx:thread_ts' / 'email:user@example.com'
    requested_by_user_id INT,              -- platform_users(user_id) if known
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_by_user_id INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_connect_links_org ON connect_links(org_id);
```

Single-use, time-limited. After consumption the row stays for audit but cannot be reused.

#### Channel adapters know how to render the link

Each channel adapter has a `render_connect_prompt(kind, url, why)` method:

- **Slack**: posts a block with a "Connect <provider>" button.
- **Email**: a plain paragraph with the link inline.
- **Signal/SMS**: short link (preferred), short message.
- **Web chat**: inline link with a tiny call-to-action.

This keeps the credential flow channel-agnostic at the core, channel-specific at the edge — same shape as the rest of amebo's channels/I/O model.

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

#### Encapsulation contract

Tool code MUST NOT know about token storage, refresh, encryption, or provider differences. Every tool that needs a credential interacts only with this surface:

```python
# In a tool implementation:
with credentials.client(org_id=ctx["org_id"], kind="gmail") as client:
    result = client.get("/users/me/messages")
```

That's it. The `client` is a thin wrapper around `requests.Session` that:
- Looks up the credential by `(org_id, kind)`.
- Refreshes pre-flight if needed.
- Adds the right auth header for the provider.
- Catches 401 once, refreshes, retries once.
- Records audit metadata (kind used, refreshes triggered).

What's hidden behind that one-liner:
- The `org_credentials` table — tool code never sees raw SQL or rows.
- Encryption/decryption — only the resolver touches `encrypted_value`.
- Provider-specific refresh logic — adapters in `tools/credentials/adapters/`.
- Token expiry math, locking, retry logic.
- Where the master key lives, how it's rotated.

If a future change moves credentials to KMS, or switches encryption library, or migrates to per-region storage — none of that touches tool code. Encapsulation is the only way this stays maintainable across many tools.

The CredentialResolver and the credentials module are the ONLY places allowed to:
- SELECT from / INSERT into `org_credentials`
- Read the encryption key
- Call provider refresh endpoints
- Decide how long a token is "valid for"

#### Token refresh — must be invisible to users

Token expiry is the #2 UX cliff after initial connection. A user who clicks "Connect Gmail" and then sees "your Gmail connection expired, please reconnect" three weeks later is an angry user. Goal: **users never see token refresh, ever, until a refresh token itself dies (rare).**

Design:

1. **Centralized `CredentialResolver`.** Tools never read tokens from the DB directly. They call `creds = CredentialResolver(org_id, kind).get()` which always returns a *valid* access token. The resolver handles refresh transparently.

2. **Pre-flight refresh.** When `get()` is called, the resolver checks `expires_at < now + buffer` (buffer = 5 minutes). If so, it refreshes BEFORE returning the token. The tool call never hits a 401 due to expiry.

3. **Lazy fallback on 401.** Tool calls wrap API requests in a helper that catches 401 once, calls `CredentialResolver.force_refresh()`, retries once. Catches the case where the server-side token was revoked between pre-flight and call, or where `expires_at` was wrong.

4. **DB-level lock during refresh.** When two goals fire concurrently and both see an expired token, only one refreshes. Use `SELECT ... FOR UPDATE` on `org_credentials.id` during the refresh transaction. The other waits and gets the freshly-refreshed token.

5. **Per-provider refresh adapter.** Each OAuth provider's refresh flow lives in `tools/credentials/adapters/{google,slack,github,microsoft}.py`. The resolver dispatches by `kind`. Adapter contract is tiny: `def refresh(stored: dict) -> RefreshedTokens`.

6. **Background pre-emptive refresh** (optional but recommended): a scheduler tick scans for credentials with `expires_at < now + 1 hour` and refreshes them ahead of time. Spreads load and means most `get()` calls don't hit the refresh path at all.

7. **Refresh-token-expired surface.** When the refresh token itself is dead (Google: 6mo inactivity; user revoked at provider; admin de-installed the app), the resolver:
   - Marks the credential `revoked_at = NOW()`.
   - Emits a notification to the org admin (`channel = admin_default`).
   - Returns a typed error from the tool call so the dispatcher records `failed: credential_expired` rather than `failed: 401`.
   - The Connections UI shows the credential as "Reconnect needed" with one click.

8. **Refresh never blocks a goal.** Goals shouldn't fail just because a token is about to expire mid-dispatch. The resolver's pre-flight ensures the token is fresh for the whole dispatch window. If refresh fails entirely, the goal fails with a clear reason and the admin gets pinged.

9. **Audit refreshes.** Each refresh writes to a `credential_events` table (or extends `goal_events` with credential context): `kind=google, action=refresh, status=ok`. Helps debug "why does my Gmail keep disconnecting?" complaints.

#### Open questions

- **Which encryption library.** Python's `cryptography.fernet` is the lightweight default; AWS KMS / GCP KMS for production rotation. For VM 200's scale, Fernet with a key in env is fine for now.
- **Per-tool scope verification.** Should amebo check that the stored token actually has the scope the tool needs before calling? Probably yes — surface a "reconnect this credential with broader scope" message in the UI rather than failing mid-goal.
- **Refresh during long-running goals.** A goal that runs for 30 minutes could outlive the access token. Either always re-resolve before each tool call (slight overhead) or hold the resolver instance and let it refresh inline. The lazy-401 fallback covers both cases.

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
