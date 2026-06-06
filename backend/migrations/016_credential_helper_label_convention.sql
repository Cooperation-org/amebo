-- Migration 015: credential-helper label convention (two-authority seam)
--
-- STATUS: NOT APPLIED. This file documents and (optionally) optimises the
-- storage convention used by src/credentials/credential_helper.py. Apply
-- only after the OAuth/SSO owners confirm the convention (see
-- docs/CREDENTIAL_HELPER.md). It is fully additive and touches NO existing
-- column or row — it adds comments and one partial index.
--
-- WHY NO NEW TABLE
-- ----------------
-- The two-authority model (delegated person vs team service identity) is
-- expressed entirely within the existing `org_credentials` table from
-- migration 010, using the `label` column as an authority/owner namespace:
--
--     delegated person X   ->  label = 'user:<principal>'
--     team service identity ->  label = 'service'
--
-- This reuses the existing encryption (Fernet, AMEBO_CRED_KEY), pre-flight
-- refresh, revoke, and the (org_id, kind, label) UNIQUE key that already
-- guarantees per-team / per-principal isolation. A separate
-- `service_credentials` table would duplicate that machinery and create a
-- second place secrets could leak. The helper therefore stores nothing new
-- in the database; it consumes what the OAuth callback already writes via
-- CredentialResolver.store_new().
--
-- No plaintext secret is ever stored: `org_credentials.encrypted_value` is
-- a Fernet blob, inert without the key, and nothing in this migration adds
-- token data.

-- Document the convention on the existing column (idempotent).
COMMENT ON COLUMN org_credentials.label IS
    'Authority/owner namespace for the credential-helper two-authority seam: '
    '"service" = team''s own service identity (background claws); '
    '"user:<principal>" = a delegated person''s credential (live turns); '
    '"default" / other = legacy per-org credential. One org can hold many '
    'rows of the same kind under different labels; isolation is the '
    '(org_id, kind, label) UNIQUE key.';

-- Optional: speed up "list this team's service credentials" and
-- "list a principal's delegated credentials" lookups. Additive, safe to
-- skip. Partial index keeps it small (active rows only).
CREATE INDEX IF NOT EXISTS idx_org_credentials_label_active
    ON org_credentials (org_id, label, kind)
    WHERE revoked_at IS NULL;
