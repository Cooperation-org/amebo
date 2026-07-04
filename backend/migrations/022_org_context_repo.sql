-- Migration 022: organizations.context_repo (WP3)
--
-- The pointer to an org's context repo (arch §2.1/§2.2), where its org.yaml
-- manifest + guidance live. ConnectionResolver (connections.py) reads the
-- manifest from this path/clone. Additive + reversible; nullable (orgs without
-- a context repo yet resolve no manifest-backed tools -> ToolNotConfigured).

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS context_repo TEXT;

COMMENT ON COLUMN organizations.context_repo IS
    'Path or clone URL of the org''s context repo (arch §2.1). Its org.yaml '
    'root manifest declares the org''s tool connections. NULL = not yet '
    'provisioned; manifest-backed tools then raise ToolNotConfigured.';

-- ROLLBACK: ALTER TABLE organizations DROP COLUMN IF EXISTS context_repo;
