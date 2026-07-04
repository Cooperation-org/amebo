-- Migration 021: recognition + venue routing state for OrgContext (WP2)
--
-- See arch §2.2, §3 (recognition vs attribution), §4.2 (resolution chain).
-- Three additive tables the per-action org resolver needs:
--   - person_identities : recognition — "who is talking to me?" maps a channel
--                         / OIDC identity to a person (platform_users). Amebo's
--                         own auth state. NEVER inferred from message content.
--   - channel_defaults  : a venue's default-org hint (workspace+channel -> org).
--   - conversation_org_pins : the org pinned to a thread; transient, GC'd with
--                         thread decay.
--
-- ADDITIVE + REVERSIBLE. Nothing reads these yet (the resolver lands next in
-- WP2). "Person" is platform_users (org-neutral after mig 020); person_id here
-- is platform_users.user_id.

-- ---------------------------------------------------------------------------
-- person_identities — recognition. One external identity (a Slack user in a
-- workspace, or an OIDC subject at an issuer) mapped to a person. Rows are
-- created by provisioning or an admin-gated linking flow (arch §3, §12.3),
-- never inferred from what someone says.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_identities (
    id          SERIAL PRIMARY KEY,
    user_id     INT  NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,                    -- 'oidc' | 'slack' | ...
    context_ref TEXT NOT NULL DEFAULT '',         -- slack: team_id; oidc: issuer
    external_id TEXT NOT NULL,                     -- slack: Uxxxx; oidc: sub
    verified    BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, context_ref, external_id)
);

CREATE INDEX IF NOT EXISTS idx_person_identities_user ON person_identities (user_id);

COMMENT ON TABLE person_identities IS
    'Recognition (arch §3): an external channel/OIDC identity -> a person '
    '(platform_users). Amebo auth state. Created by provisioning/admin linking, '
    'NEVER inferred from message content. UNIQUE(provider, context_ref, '
    'external_id): slack=(slack, team_id, Uxxxx); oidc=(oidc, issuer, sub).';

-- ---------------------------------------------------------------------------
-- channel_defaults — a venue's default-org hint. Resolution step 6 (arch §4.2)
-- consults this before falling back to workspaces.default_org_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_defaults (
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    channel_id   TEXT NOT NULL,
    org_id       INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (workspace_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_defaults_org ON channel_defaults (org_id);

COMMENT ON TABLE channel_defaults IS
    'Venue default-org hint: (workspace, channel) -> org. A hint consulted '
    'during per-action org resolution (arch §4.2 step 6), not exclusive '
    'ownership.';

-- ---------------------------------------------------------------------------
-- conversation_org_pins — the org pinned to a thread by explicit targeting or
-- a resolved question. Transient; decays with the thread (arch §2.2, §4.2).
-- thread_ref is the source-agnostic thread key (slack thread_ts, web session,
-- email thread id), matching threads.source_ref usage.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_org_pins (
    thread_ref TEXT PRIMARY KEY,
    org_id     INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    pinned_by  INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    pinned_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_org_pins_org ON conversation_org_pins (org_id);

COMMENT ON TABLE conversation_org_pins IS
    'Org pinned to a conversation thread (explicit targeting / resolved '
    'question). Transient — GC''d with thread decay. thread_ref = source-'
    'agnostic thread key.';

-- ---------------------------------------------------------------------------
-- organizations.aliases — the org's alternate names for explicit-targeting
-- match in resolution (arch §2.2, §4.2 step 4: "file this under raise the
-- voices" / "for rtv:"). Mirrored from the org.yaml manifest on read (WP3);
-- seeded directly until then. slug + name are already matchable columns.
-- ---------------------------------------------------------------------------
ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS aliases JSONB NOT NULL DEFAULT '[]';

COMMENT ON COLUMN organizations.aliases IS
    'Alternate names for explicit-targeting match during org resolution '
    '(arch §4.2). JSON array of strings; mirrored from the org.yaml manifest.';

-- ===========================================================================
-- ROLLBACK (mig 021) — additive, clean drop:
--   DROP TABLE IF EXISTS conversation_org_pins;
--   DROP TABLE IF EXISTS channel_defaults;
--   DROP TABLE IF EXISTS person_identities;
--   ALTER TABLE organizations DROP COLUMN IF EXISTS aliases;
-- ===========================================================================
