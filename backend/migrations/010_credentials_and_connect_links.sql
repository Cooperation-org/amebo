-- Migration 010: org_credentials + connect_links
--
-- Adds encrypted credential storage for per-org OAuth tokens, plus the
-- one-time signed connect_links table that drives the chat-initiated
-- OAuth flow.
--
-- See docs/POWERS_PLAN.md for the design.
--
-- IMPORTANT: This migration is additive. No existing tables are touched.
-- Encryption is handled in application code (Fernet); the database stores
-- only opaque BYTEA blobs. Without the encryption key, the blobs are
-- inert.

-- ---------------------------------------------------------------------------
-- org_credentials
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS org_credentials (
    id                  SERIAL PRIMARY KEY,
    org_id              INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    kind                TEXT NOT NULL,                 -- 'gmail' | 'slack' | 'github' | 'linkedin' | ...
    label               TEXT NOT NULL DEFAULT 'default', -- per-org sub-label so an org can have multiple of a kind
    encrypted_value     BYTEA NOT NULL,                 -- Fernet-encrypted JSON: {access_token, refresh_token, ...}
    granted_scopes      TEXT[] DEFAULT '{}',
    expires_at          TIMESTAMPTZ,                    -- access-token expiry; refresh handles renewal
    connected_by_user_id INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    last_used_at        TIMESTAMPTZ,
    revoked_at          TIMESTAMPTZ,                     -- nullable: still active when NULL
    UNIQUE (org_id, kind, label)
);

CREATE INDEX IF NOT EXISTS idx_org_credentials_org_kind
    ON org_credentials(org_id, kind);

CREATE INDEX IF NOT EXISTS idx_org_credentials_active
    ON org_credentials(org_id, kind)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_org_credentials_expiring
    ON org_credentials(expires_at)
    WHERE revoked_at IS NULL AND expires_at IS NOT NULL;

COMMENT ON TABLE  org_credentials IS
    'Per-org OAuth credentials. encrypted_value is Fernet-encrypted JSON. '
    'Tool code MUST go through CredentialResolver, never read this table directly.';
COMMENT ON COLUMN org_credentials.kind  IS
    'Stable identifier for the provider type (gmail, slack, github, ...).';
COMMENT ON COLUMN org_credentials.label IS
    'Sub-label so one org can have several credentials of the same kind '
    '(e.g. two Gmails). Default "default".';
COMMENT ON COLUMN org_credentials.granted_scopes IS
    'Scopes the user actually granted, NOT scopes we requested. Use this to '
    'detect "needs reconnect with broader scope" before failing mid-goal.';

-- ---------------------------------------------------------------------------
-- connect_links
-- ---------------------------------------------------------------------------
--
-- Minted when a chat surface needs the user to authorize a new credential.
-- Single-use and time-limited.

CREATE TABLE IF NOT EXISTS connect_links (
    short_code            TEXT PRIMARY KEY,             -- url-safe 16+ chars
    org_id                INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    kind                  TEXT NOT NULL,
    label                 TEXT NOT NULL DEFAULT 'default',
    requested_scopes      TEXT[] DEFAULT '{}',
    reply_channel         TEXT,                          -- 'slack:Cxxx:thread_ts' | 'email:addr' | 'web:session_id'
    requested_by_user_id  INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    expires_at            TIMESTAMPTZ NOT NULL,
    consumed_at           TIMESTAMPTZ,
    consumed_by_user_id   INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_connect_links_org
    ON connect_links(org_id);

CREATE INDEX IF NOT EXISTS idx_connect_links_active
    ON connect_links(expires_at)
    WHERE consumed_at IS NULL;

COMMENT ON TABLE connect_links IS
    'Single-use, time-limited OAuth connect tokens. Sent through whatever '
    'channel the user is on so OAuth can be started from chat, not just from '
    'the web UI.';
COMMENT ON COLUMN connect_links.reply_channel IS
    'Where to send the "connected" notification after OAuth completes. '
    'Format: "<channel-type>:<channel-ref>" — slack:Cxxx:thread_ts, '
    'email:address, web:session_id, etc. Channel adapters interpret.';
