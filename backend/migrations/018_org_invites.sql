-- SSO invite links: an owner mints a one-time link; the invitee clicks it,
-- logs in via the LinkedTrust IdP, and is activated into the org on callback.
-- The link carries a random token; only its hash is stored.

CREATE TABLE IF NOT EXISTS org_invites (
    id                   SERIAL PRIMARY KEY,
    token_hash           TEXT        NOT NULL UNIQUE,
    org_id               INTEGER     NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    role                 TEXT        NOT NULL DEFAULT 'member',
    created_by_user_id   INTEGER,
    expires_at           TIMESTAMPTZ NOT NULL,
    consumed_at          TIMESTAMPTZ,
    consumed_by_user_id  INTEGER,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup of a live (unconsumed) invite by its token hash.
CREATE INDEX IF NOT EXISTS idx_org_invites_live
    ON org_invites (token_hash) WHERE consumed_at IS NULL;
