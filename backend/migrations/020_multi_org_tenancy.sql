-- Migration 020: multi-org tenancy foundations (WP1)
--
-- See /opt/shared/projects/plans/amebo/7-4-2026-amebo-architecture.md §2.2 and
-- the WP plan (WP1). Introduces the many-to-many tables that replace the
-- single-org columns platform_users.org_id and instances.org_id:
--   - a person is a member of N orgs           -> org_members
--   - an instance serves N orgs                -> instance_orgs
--
-- ADDITIVE + REVERSIBLE. No existing table is dropped or rewritten. Existing
-- single-org data is COPIED FORWARD into the new tables. The old columns are
-- RETAINED and still readable (deprecated, no longer the source of truth) so the
-- running instance keeps working until readers migrate. Rollback = drop the two
-- new tables (see the ROLLBACK block at the bottom); no data is stranded.

-- ---------------------------------------------------------------------------
-- org_members — a person's membership in an org. Many orgs per person.
-- Replaces the single platform_users.org_id. `source` records how the row
-- arrived; 'linkedclaims' is reserved for the future team-member-claim sync
-- (no claim integration in this migration).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS org_members (
    org_id     INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id    INT  NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'member',
    source     TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'linkedclaims'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (org_id, user_id),
    CONSTRAINT org_members_source_chk CHECK (source IN ('manual', 'linkedclaims'))
);

CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members (user_id);

COMMENT ON TABLE org_members IS
    'Membership: a platform_users person in an organization, many orgs per '
    'person. Source of truth for membership (replaces platform_users.org_id). '
    'source=manual|linkedclaims; linkedclaims reserved for the future claim sync.';

-- Data migration: every existing platform_users.org_id becomes a membership,
-- carrying the person''s current role. Idempotent.
INSERT INTO org_members (org_id, user_id, role, source)
SELECT org_id, user_id, COALESCE(NULLIF(role, ''), 'member'), 'manual'
FROM platform_users
WHERE org_id IS NOT NULL
ON CONFLICT (org_id, user_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- instance_orgs — which orgs an instance serves. Many orgs per instance.
-- Replaces the single instances.org_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS instance_orgs (
    instance_id INT NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    org_id      INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (instance_id, org_id)
);

CREATE INDEX IF NOT EXISTS idx_instance_orgs_org ON instance_orgs (org_id);

COMMENT ON TABLE instance_orgs IS
    'Which orgs an amebo instance serves. Many orgs per instance (replaces the '
    'single instances.org_id).';

-- Data migration: every existing instances.org_id becomes an instance_orgs row.
INSERT INTO instance_orgs (instance_id, org_id)
SELECT id, org_id FROM instances WHERE org_id IS NOT NULL
ON CONFLICT (instance_id, org_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Deprecation markers. The columns are RETAINED and still written for
-- back-compat (they are read widely today, and platform_users.org_id is NOT
-- NULL), but they are no longer the source of truth. New code reads org_members
-- / instance_orgs. Full removal of writes happens once all readers migrate.
-- ---------------------------------------------------------------------------
COMMENT ON COLUMN platform_users.org_id IS
    'DEPRECATED (mig 020): membership source of truth is org_members. Retained + '
    'still written for back-compat reads. Do not add new readers.';
COMMENT ON COLUMN instances.org_id IS
    'DEPRECATED (mig 020): an instance serves N orgs via instance_orgs. Retained + '
    'still written for back-compat reads. Do not add new readers.';

-- org_workspaces: a row means "this workspace's DEFAULT org for that org", NOT
-- exclusive ownership. The existing UNIQUE(org_id, workspace_id) already lets a
-- single workspace map to multiple orgs (a shared workspace), so no schema
-- change is needed here — only the clarified meaning.
COMMENT ON TABLE org_workspaces IS
    'Org<->Slack-workspace link. A row = that workspace''s default-org hint for '
    'the org, NOT exclusive ownership; a workspace may map to several orgs.';

-- ---------------------------------------------------------------------------
-- Transitional sync triggers. While the old single-org columns are still
-- written (they are read widely, and platform_users.org_id is NOT NULL), keep
-- the new source-of-truth tables in sync from ONE place instead of editing
-- every raw-SQL writer (6 platform_users insert sites, incl. SSO). Same pattern
-- as the existing update_updated_at_column triggers. These are transitional and
-- get dropped at the WP17 cutover once writers target org_members/instance_orgs
-- directly. Idempotent (CREATE OR REPLACE + DROP TRIGGER IF EXISTS).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION mirror_platform_user_membership()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.org_id IS NOT NULL THEN
        INSERT INTO org_members (org_id, user_id, role, source)
        VALUES (NEW.org_id, NEW.user_id, COALESCE(NULLIF(NEW.role, ''), 'member'), 'manual')
        ON CONFLICT (org_id, user_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_platform_users_membership ON platform_users;
CREATE TRIGGER trg_platform_users_membership
    AFTER INSERT OR UPDATE OF org_id ON platform_users
    FOR EACH ROW EXECUTE FUNCTION mirror_platform_user_membership();

CREATE OR REPLACE FUNCTION mirror_instance_org()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.org_id IS NOT NULL THEN
        INSERT INTO instance_orgs (instance_id, org_id)
        VALUES (NEW.id, NEW.org_id)
        ON CONFLICT (instance_id, org_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_instances_org ON instances;
CREATE TRIGGER trg_instances_org
    AFTER INSERT OR UPDATE OF org_id ON instances
    FOR EACH ROW EXECUTE FUNCTION mirror_instance_org();

-- ===========================================================================
-- ROLLBACK (mig 020) — additive, so reversal is a clean drop:
--   DROP TRIGGER IF EXISTS trg_platform_users_membership ON platform_users;
--   DROP TRIGGER IF EXISTS trg_instances_org ON instances;
--   DROP FUNCTION IF EXISTS mirror_platform_user_membership();
--   DROP FUNCTION IF EXISTS mirror_instance_org();
--   DROP TABLE IF EXISTS instance_orgs;
--   DROP TABLE IF EXISTS org_members;
--   COMMENT ON COLUMN platform_users.org_id IS NULL;
--   COMMENT ON COLUMN instances.org_id IS NULL;
--   COMMENT ON TABLE  org_workspaces IS NULL;
-- The retained org_id columns still hold every value, so no data is lost.
-- ===========================================================================
