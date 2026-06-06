-- Migration 015: pending_actions — the draft-approval gate
-- Additive only. No changes to existing tables. See docs/DRAFT_APPROVAL_GATE.md
-- for design rationale and the dispatcher integration point.
--
-- Purpose: a background claw must never take an irreversible OUTBOUND or
-- DESTRUCTIVE action (send a Slack message, send email, write to CRM/Taiga,
-- open/merge a PR) without a human approving first. Read-only / internal
-- actions are NOT gated and never land here. When the gate intercepts a
-- gated action it records it as a 'pending' row; a human approves or rejects;
-- only then does the caller/executor actually perform it.
--
-- Org scoping mirrors `goals`: org_id is the isolation authority (the goals
-- API enforces every operation against the authenticated client's org_id).
-- instance_id is recorded for provenance when an instance acted, but is not
-- the isolation key.
--
-- Rollback:
--   DROP TABLE IF EXISTS pending_actions;

CREATE TABLE IF NOT EXISTS pending_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    instance_id     INT  REFERENCES instances(id) ON DELETE SET NULL,
    goal_id         UUID REFERENCES goals(id) ON DELETE SET NULL,
    action_type     TEXT NOT NULL,            -- e.g. 'slack_post', 'send_email', 'odoo_cli', 'open_pr'
    target          TEXT,                     -- channel / recipient / system the action hits
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- the exact args the executor will use
    preview         TEXT,                     -- human-readable summary of what will happen
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed')),
    acting_identity TEXT NOT NULL,            -- person author URI, or 'amebo:<team>' for autonomous
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approver        TEXT,                     -- who approved/rejected (set on decision)
    decision_reason TEXT,                     -- e.g. rejection reason
    decided_at      TIMESTAMPTZ,
    executed_at     TIMESTAMPTZ,
    error           TEXT                      -- populated when status = 'failed'
);

CREATE INDEX IF NOT EXISTS idx_pending_actions_status      ON pending_actions(status);
CREATE INDEX IF NOT EXISTS idx_pending_actions_instance    ON pending_actions(instance_id);
CREATE INDEX IF NOT EXISTS idx_pending_actions_org         ON pending_actions(org_id);
CREATE INDEX IF NOT EXISTS idx_pending_actions_org_status  ON pending_actions(org_id, status);
-- Fast "what is waiting for me to approve" lookups per org.
CREATE INDEX IF NOT EXISTS idx_pending_actions_org_pending ON pending_actions(org_id, requested_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pending_actions_goal        ON pending_actions(goal_id);

COMMENT ON TABLE  pending_actions IS 'Draft-approval gate: outbound/destructive claw actions awaiting human approval before execution.';
COMMENT ON COLUMN pending_actions.org_id          IS 'Isolation authority. Every API operation is scoped to the caller org_id, mirroring goals.';
COMMENT ON COLUMN pending_actions.instance_id     IS 'Which amebo instance proposed the action, if any. Provenance only, not the isolation key.';
COMMENT ON COLUMN pending_actions.goal_id         IS 'The goal this action was proposed in service of, if any. SET NULL if the goal is deleted.';
COMMENT ON COLUMN pending_actions.action_type     IS 'Stable action identifier; classified by src/services/gated_actions.py into GATED vs FREE.';
COMMENT ON COLUMN pending_actions.payload         IS 'The exact arguments the executor will use when the action is approved and run.';
COMMENT ON COLUMN pending_actions.preview         IS 'Human-readable one-line summary of what will happen on approval.';
COMMENT ON COLUMN pending_actions.acting_identity IS 'Author of the action: a person author URI, or amebo:<team> for autonomous claw activity.';
COMMENT ON COLUMN pending_actions.status          IS 'pending → approved → executed (or failed); pending → rejected. Terminal: executed, rejected, failed.';
