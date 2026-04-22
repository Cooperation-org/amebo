-- Migration 008: Add org_id to instances table
-- Allows linking instances to organizations for service-to-service ownership.
-- Nullable because existing instances predate org assignment.

ALTER TABLE instances ADD COLUMN IF NOT EXISTS org_id INT REFERENCES organizations(org_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_instances_org_id ON instances(org_id);
