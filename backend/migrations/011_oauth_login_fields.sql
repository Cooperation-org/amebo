-- Migration 011: platform_users fields for OAuth login
--
-- Adds the columns needed to support social login (Google first, more later).
-- Existing password rows are unaffected — password_hash is loosened from
-- NOT NULL to NULL-able so OAuth-only users don't need a fake password.
--
-- Additive + one column relaxation. Live process keeps running fine.

ALTER TABLE platform_users
    ALTER COLUMN password_hash DROP NOT NULL;

ALTER TABLE platform_users
    ADD COLUMN IF NOT EXISTS auth_provider      TEXT,  -- 'password' | 'google' | 'bluesky' | ...
    ADD COLUMN IF NOT EXISTS auth_provider_id   TEXT,  -- provider's stable user id (Google sub, ATProto did)
    ADD COLUMN IF NOT EXISTS avatar_url         TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_users_provider
    ON platform_users (auth_provider, auth_provider_id)
    WHERE auth_provider IS NOT NULL AND auth_provider_id IS NOT NULL;

COMMENT ON COLUMN platform_users.auth_provider IS
    'How the user authenticates: password, google, bluesky, github. NULL = legacy password row.';
COMMENT ON COLUMN platform_users.auth_provider_id IS
    'Stable identifier from the provider (Google sub claim, ATProto did, GitHub user id).';

-- Backfill: any row with a non-null password_hash and no auth_provider is a password user.
UPDATE platform_users
SET auth_provider = 'password'
WHERE auth_provider IS NULL AND password_hash IS NOT NULL;
