-- Migration 019: team provisioning — roster's external-tool accounts + the
-- configurable per-org tool registry, plus invite-carried tool requests.
--
-- See docs/TEAM_PROVISIONING.md for the design.
--
-- IMPORTANT: additive. No existing table is dropped or rewritten. org_invites
-- gains three nullable/defaulted columns (its only consumers — team.py,
-- auth.py — name columns explicitly, so this is non-breaking).

-- ---------------------------------------------------------------------------
-- org_tools — the configurable tool registry (NON-secret config).
-- The secret for a tool is resolved via CredentialResolver(org, kind, label);
-- this table holds only how to reach the tool and how to provision into it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS org_tools (
    id            SERIAL PRIMARY KEY,
    org_id        INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    tool_key      TEXT NOT NULL,                       -- 'taiga' | 'odoo_crm' | 'slack'
    kind          TEXT NOT NULL,                       -- org_credentials.kind for the service creds
    cred_label    TEXT NOT NULL DEFAULT 'default',
    display_name  TEXT,
    base_url      TEXT,
    default_role  TEXT,                                -- 'Back', 'internal+sales', ...
    config        JSONB NOT NULL DEFAULT '{}',         -- adapter-specific extras (scope_filter, ...)
    enabled       BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (org_id, tool_key)
);

CREATE INDEX IF NOT EXISTS idx_org_tools_enabled
    ON org_tools (org_id) WHERE enabled = true;

COMMENT ON TABLE  org_tools IS
    'Per-org configurable tool connections (non-secret). Secret resolved via '
    'CredentialResolver(org_id, kind, cred_label). Adding a tool = new '
    'ProvisioningAdapter module + a row here.';
COMMENT ON COLUMN org_tools.default_role IS
    'Role to grant when an invite does not specify one for this tool.';

-- ---------------------------------------------------------------------------
-- member_tool_accounts — the identity map AS ROWS (replaces the abra blob).
-- One member's account in one external tool, plus the provisioning state.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS member_tool_accounts (
    id                SERIAL PRIMARY KEY,
    org_id            INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id           INT  REFERENCES platform_users(user_id) ON DELETE CASCADE, -- NULL: pre-login
    tool_key          TEXT NOT NULL,
    external_id       TEXT,                            -- e.g. Taiga user 344, Odoo user 28
    external_username TEXT,
    granted_role      TEXT,                            -- 'Back', 'internal+sales', ...
    state             TEXT NOT NULL DEFAULT 'pending', -- pending | linked | failed | skipped
    reason            TEXT,                            -- failure detail, e.g. 'not a valid contact'
    invite_id         INT REFERENCES org_invites(id) ON DELETE SET NULL, -- pre-login provenance
    last_synced_at    TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Idempotency. Postgres treats NULLs as distinct, so a plain
-- UNIQUE(org_id,user_id,tool_key) would not stop duplicate pre-login rows
-- (user_id NULL). Two partial unique indexes instead:
CREATE UNIQUE INDEX IF NOT EXISTS uq_mta_user        -- post-login: one row per member per tool
    ON member_tool_accounts (org_id, user_id, tool_key) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mta_extern      -- always: one row per external account
    ON member_tool_accounts (org_id, tool_key, external_id) WHERE external_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mta_state
    ON member_tool_accounts (org_id, state);

COMMENT ON TABLE member_tool_accounts IS
    'Identity map: a team member''s account in an external tool + provisioning '
    'state. Pre-login rows have user_id NULL (deduped by uq_mta_extern); '
    'activation backfills user_id from the consumed invite.';

-- ---------------------------------------------------------------------------
-- org_invites — carry the invitee email and which tools to provision.
-- ---------------------------------------------------------------------------
ALTER TABLE org_invites
    ADD COLUMN IF NOT EXISTS invitee_email   TEXT,
    ADD COLUMN IF NOT EXISTS invitee_name    TEXT,
    ADD COLUMN IF NOT EXISTS requested_tools JSONB NOT NULL DEFAULT '[]';
    -- requested_tools: [{"tool_key","role","scope"}]; [] = all enabled org_tools
    --                  at each tool's default_role.

COMMENT ON COLUMN org_invites.requested_tools IS
    'Tools to provision on activation. Empty array = all enabled org_tools at '
    'their default_role.';
