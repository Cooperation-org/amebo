# Team Provisioning — one invite, accounts + roles across every connected tool

Status: design (2026-06-24). Author: Golda + Claude (AI-drafted, for review).

## Problem

Onboarding a team member today is manual, per-tool, and drifts. The CRM/Taiga
session on 2026-06-24 made the failure modes concrete:

- A person logs into a tool via LinkedTrust SSO and lands as a **stub with no
  role** (Odoo portal user; Taiga Stakeholder) — SSO authenticated them but
  granted nothing. They "can't see the right things."
- The **identity map is nowhere queryable**. "zakia = Taiga #344, Odoo contact
  8381" lived only in a person's head, then in an abra prose blob. Software
  can't read that transactionally, so every grant is hand-done.
- **Duplicate accounts** accumulate (one person, two Taiga users) because
  nothing reconciles desired state against live state.
- Access is granted with a **personal, expiring token**, not a service account.

## What this is (and is not)

A small, additive feature: a **system of record** for who is on a team and
which external-tool accounts they hold, plus a **gated invite actuator** that
provisions a member into every connected tool in one action, idempotently.

- It is **normal relational software**: constrained rows, explicit state, a
  reconcile loop. Not prose, not vectors.
- It is **configurable**: each org declares its own tools; adding a tool is a
  new adapter module + one row, mirroring how `src/tools/registry.py` grows.
- It does **not** merge or deactivate external accounts, and does **not** move
  task ownership between accounts. Duplicates are tolerated and flagged.

## Boundary note (amends `BOUNDARIES.md`)

`BOUNDARIES.md` says "amebo holds nothing about who the person is." Refine the
line — it was conflating two different things:

- **abra** = who-they-are-as-knowledge: meeting context, relationships,
  history. Semantic, fuzzy. Stays in abra.
- **amebo DB** = operational system-of-record: org membership, per-tool account
  links, invite lifecycle, provisioning state. Constrained, transactional.
  amebo is the *actor*; an actor needs a durable record of what it provisioned
  and the state of each invite. That record is amebo's, not abra's.

This is the one intentional revision to the prior model. Make it explicit so a
later session does not "fix" the roster back into an abra blob.

## Reuse — what already exists (do not rebuild)

| Need | Existing artifact |
|---|---|
| Roster / member identity | `platform_users` (org_id, email, full_name, role, `auth_provider`/`auth_provider_id`, is_active). LT SSO member = `auth_provider='linkedtrust'`, `auth_provider_id=<OIDC sub>`. password_hash already nullable (mig 011). |
| SSO invite link → IdP login → activate | `org_invites` (mig 018) + `auth_oauth/oidc_login.py` (`OidcIdentity.sub`). |
| Per-tool **secrets** | `org_credentials` (mig 010), Fernet-encrypted, read only via `CredentialResolver`. |
| Human approval on outbound actions | `DraftApprovalService.gate_or_execute` (mig 015 `pending_actions`). **Gating is default-DENY**: `gated_actions.is_gated()` returns `action_type not in FREE_ACTIONS`. `GATED_ACTIONS` is an inert audit set nothing reads — a new action name like `invite_member` is gated automatically, no code change. Do **not** add it to `FREE_ACTIONS`. |
| Tool registration pattern | `src/tools/registry.py` — eyes (read) vs hands (gated), additive. |
| Per-tool credential adapters | `src/credentials/adapters/` (`base.py`, `google_adapter.py`, ...). |

## New schema (migration `019_team_provisioning.sql`, additive)

```sql
-- 1. org_tools — the configurable tool registry (NON-secret config).
--    The secret for a tool is resolved via CredentialResolver(org, kind, label).
CREATE TABLE IF NOT EXISTS org_tools (
    id            SERIAL PRIMARY KEY,
    org_id        INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    tool_key      TEXT NOT NULL,             -- 'taiga' | 'odoo_crm' | 'slack'
    kind          TEXT NOT NULL,             -- org_credentials.kind for the service creds
    cred_label    TEXT NOT NULL DEFAULT 'default',
    display_name  TEXT,
    base_url      TEXT,
    default_role  TEXT,                      -- explicit column (NOT buried in config): 'Back', 'internal+sales'
    config        JSONB NOT NULL DEFAULT '{}',  -- adapter-specific extras (scope_filter, ...)
    enabled       BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (org_id, tool_key)
);

-- 2. member_tool_accounts — the identity map AS ROWS (replaces the abra blob).
CREATE TABLE IF NOT EXISTS member_tool_accounts (
    id                SERIAL PRIMARY KEY,
    org_id            INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id           INT  REFERENCES platform_users(user_id) ON DELETE CASCADE, -- nullable: pre-login provisioning
    tool_key          TEXT NOT NULL,
    external_id        TEXT,                  -- e.g. Taiga user 344, Odoo user 28
    external_username  TEXT,
    granted_role       TEXT,                  -- 'Back', 'internal+sales', ...
    state             TEXT NOT NULL DEFAULT 'pending', -- pending | linked | failed | skipped
    reason            TEXT,                   -- failure detail, e.g. 'not a valid contact'
    invite_id         INT REFERENCES org_invites(id) ON DELETE SET NULL, -- pre-login provenance
    last_synced_at    TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
-- Idempotency keys. Postgres treats NULLs as distinct, so a plain
-- UNIQUE(org_id,user_id,tool_key) would NOT stop duplicate pre-login rows
-- (user_id NULL). Use two partial unique indexes instead:
CREATE UNIQUE INDEX IF NOT EXISTS uq_mta_user   -- after login: one row per member per tool
    ON member_tool_accounts (org_id, user_id, tool_key) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mta_extern  -- always: one row per external account
    ON member_tool_accounts (org_id, tool_key, external_id) WHERE external_id IS NOT NULL;
-- Pre-login rows (user_id NULL, external_id known) are deduped by uq_mta_extern;
-- on activation the row's user_id is backfilled from the consumed invite.

-- 3. Extend org_invites to carry email + which tools to provision.
ALTER TABLE org_invites
    ADD COLUMN IF NOT EXISTS invitee_email   TEXT,
    ADD COLUMN IF NOT EXISTS invitee_name    TEXT,
    ADD COLUMN IF NOT EXISTS requested_tools JSONB NOT NULL DEFAULT '[]';
    -- requested_tools: [{tool_key, role, scope}] ; [] = all enabled org_tools at default role
```

## The adapter contract (configurable tools)

**This is a NEW protocol, distinct from the existing credential `Adapter`**
(`src/credentials/adapters/base.py`, which is OAuth-token plumbing:
`kind`/`refresh`/`build_authorize_url`/`exchange_code`). A `ProvisioningAdapter`
shares no base class or registry with it — it *consumes* `CredentialResolver`
to fetch the service secret, then acts. One module per tool under
`src/tools/provisioning/`, in the additive style of `registry.py`. Each
implements:

```python
class ProvisioningAdapter(Protocol):
    tool_key: str
    def ensure_account(self, member: Member, conn: ToolConn) -> ExternalAccount: ...
    def set_membership(self, member, scope, role, conn) -> None: ...   # idempotent
    def verify(self, member, conn) -> LiveState: ...                   # read-back
    def revoke(self, member, scope, conn) -> None: ...                 # gated, optional
```

- **taiga** — wraps the proven REST flow (POST `/memberships`, role with
  `modify_us`+`add_us`, verify by re-reading membership; absorbs the "valid
  contact" 400 and the invite-email-500). Service creds, not a personal token.
- **odoo_crm** — wraps `odoo-cli` / XML-RPC: `ensure_account` finds/creates the
  user; `set_membership` sets Internal User + Sales/User (the portal-stub fix).
- **slack** (later) — invite to workspace + channels.

Tool quirks live **inside** the adapter; the actuator and reconciler never see
them.

**Service credentials are static tokens, not OAuth.** A Taiga owner token / Odoo
admin login don't fit the OAuth `Adapter.refresh()` shape, and
`CredentialResolver.get()` calls `get_adapter(kind)` on its refresh path — an
unknown `kind` raises `LookupError`. So for each new `kind` (`taiga`, `odoo`)
register a trivial **static-token credential adapter** whose `refresh()` is a
no-op, and store the secret with `expires_at = NULL` (never hits the refresh
path). This keeps `CredentialResolver` the sole secret path without it
exploding on a non-OAuth kind.

## The invite flow (one gated actuator: `invite_member`)

**What registering the new gated tool actually requires** (verified against the
codebase): (a) define the `Tool` and `register_tool(...)` in `registry.py`;
(b) build the side effect through `gated_actuators._route_through_gate(
action_type="invite_member", ...)`, exactly like `taiga_create_task` — gating is
then automatic (default-deny); (c) **`register_executor("invite_member", ...)`
in `action_executors.py`** so the *approved* `pending_action` has something to
run later — this is mandatory and easy to forget; (d) add `invite_member` to the
instance's `allowed_tools` (it is in neither `DEFAULT_TOOLS` nor any allowlist by
default). No change to `gated_actions.py`.

Context: the actuator reads `org_id` from `context["org_id"]` (set by
`execute_tool`; `_org_id(context)` refuses without it). The invitee email,
role, and `requested_tools` come from the **tool_input**, not from a row — the
`org_invites` row is *written* as step 2, not read at draft time.

Steps, each idempotent and individually recorded:

1. Upsert `platform_users` row (status invited; `auth_provider='linkedtrust'`
   once known).
2. Mint an `org_invites` link (existing flow, now carrying `invitee_email` +
   `requested_tools`) → invitee logs in via LT IdP → activation callback fills
   `auth_provider_id` from `OidcIdentity.sub` and backfills `user_id` on the
   pre-login `member_tool_accounts` rows.
3. For each enabled `org_tools` (or `requested_tools`, defaulting to all enabled
   at each tool's `default_role`): adapter `ensure_account` + `set_membership`;
   write a `member_tool_accounts` row with `state` and `reason`.
4. **Reconcile on first login** — re-run `verify`/`set_membership` so the role
   is set, not just SSO. This is the structural fix for the portal-stub gap.

Robustness properties:

- **Idempotent** — re-running converges; existing membership → no-op.
- **Read-back verified** — every external write confirmed against live state
  (never trust the POST status alone).
- **Resumable / partial-failure-safe** — a tool that fails leaves a `failed`
  row with a reason and does not block the others (myee's "valid contact"
  becomes a retryable row, not a silent miss).
- **Desired-state reconciler** — the roster is desired state; a periodic job
  drives each tool to it and surfaces drift (duplicate/extra accounts).

Surfaces (both call the same actuator):

- CLI: `amebo invite <email> --role dev [--tools taiga,odoo_crm]`
- Admin UI: an invite form listing the org's enabled tools.

## Out of scope (explicit)

- Merging two external accounts into one, or reassigning task ownership between
  them (Taiga has no native merge; would be invasive). Reconciler picks one
  canonical external account per member; duplicates are flagged, never merged
  or deactivated.
- Deactivating any account.

## Build order

1. Migration `019` (after `018`; `member_tool_accounts` uniqueness via the two
   partial indexes above) + seed `org_tools` (taiga, odoo_crm) and
   `member_tool_accounts` from the 16 confirmed mappings of 2026-06-24.
2. Static-token credential adapters for kinds `taiga`, `odoo` (no-op `refresh()`),
   so `CredentialResolver` serves their service secrets; store with
   `expires_at=NULL`.
3. Taiga + Odoo `ProvisioningAdapter`s wrapping the already-proven flows.
4. Gated `invite_member`: `register_tool` + `_route_through_gate` +
   **`register_executor`** + add to `allowed_tools`; `amebo invite` CLI verb.
5. Reconcile job + drift report.
6. Admin UI invite form.
7. Amend `BOUNDARIES.md` with the abra-vs-amebo line above.

Note: the base `schema_auth.sql` DDL still declares `password_hash NOT NULL`;
migration 011 relaxes it. The SSO-member-needs-no-password property holds only
post-011 — don't "re-fix" the base file.

## Prerequisite

Per-tool **service** credentials in `org_credentials` (an Odoo admin user, a
Taiga owner token) — never a personal expiring token. This is also the durable
fix for "make the token last longer."
