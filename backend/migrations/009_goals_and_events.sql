-- Migration 009: Goals and goal_events
-- Adds the Goal/Claw subsystem. Additive only — no changes to existing tables.
-- See docs/ORGS_GOALS_CLAW.md for design rationale.

-- Goals are per-org intentions amebo can pursue in claw mode.
-- Vision/values/semantic context for an org are NOT stored here — they live
-- in abra as hot-tagged content blobs (queried at runtime when dispatching).

CREATE TABLE IF NOT EXISTS goals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          INT  NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    target_criteria JSONB,                    -- structured "done" definition
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'active', 'completed', 'failed', 'paused')),
    trigger_config  JSONB,                    -- {type: cron|event|manual, ...}
    notify_channel  TEXT,                     -- where to post results (e.g. "slack:#goals")
    created_by_user_id  INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    assigned_to_user_id INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_goals_org           ON goals(org_id);
CREATE INDEX IF NOT EXISTS idx_goals_org_status    ON goals(org_id, status);
CREATE INDEX IF NOT EXISTS idx_goals_pending       ON goals(org_id, status) WHERE status = 'pending';

COMMENT ON TABLE  goals IS 'Per-org goals the claw can pursue. Semantic context (vision/values) lives in abra.';
COMMENT ON COLUMN goals.trigger_config  IS 'JSON: {"type":"cron","expression":"..."} | {"type":"event","event":"..."} | {"type":"manual"}';
COMMENT ON COLUMN goals.notify_channel  IS 'Destination for completion notification, e.g. "slack:#channel" or "email:user@example.com"';
COMMENT ON COLUMN goals.target_criteria IS 'JSON describing what "done" looks like. Interpreted by dispatcher when evaluating completion.';

-- Audit trail. Every state transition + every claw action writes an event.
-- Any user in the org can read these to interrogate goal progress.

CREATE TABLE IF NOT EXISTS goal_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id         UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    step_index      INT  NOT NULL,
    actor_user_id   INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'claw', 'system')),
    action          TEXT NOT NULL,            -- 'created' | 'activated' | 'tool_call:<name>' | 'completed' | 'failed' | 'paused' | 'resumed'
    result_summary  TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_goal_events_goal ON goal_events(goal_id, step_index);
CREATE INDEX IF NOT EXISTS idx_goal_events_time ON goal_events(goal_id, created_at);

COMMENT ON TABLE  goal_events IS 'Append-only audit trail for goals. Step_index orders events within a goal lifetime.';
COMMENT ON COLUMN goal_events.actor_type IS 'Who acted: user (human), claw (autonomous amebo), system (scheduler/migration)';
COMMENT ON COLUMN goal_events.action     IS 'Stable action identifier. Free-form for tool_call:<toolname>, fixed for lifecycle transitions.';
