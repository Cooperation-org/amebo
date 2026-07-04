-- Migration 025: goal_events.parent_event_id (WP19 — attribution chain)
--
-- Link an event to the dispatch/parent event that caused it, so a goal's history
-- reads as a tree (which tool calls belong to which dispatch), per the SDK-
-- patterns design. Additive + reversible; NULL = top-level.

ALTER TABLE goal_events
    ADD COLUMN IF NOT EXISTS parent_event_id UUID REFERENCES goal_events(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_goal_events_parent ON goal_events(parent_event_id);

COMMENT ON COLUMN goal_events.parent_event_id IS
    'The event that caused this one (e.g. the dispatch a tool_call belongs to). '
    'NULL = top-level. Forms the attribution chain (WP19).';

-- ROLLBACK: ALTER TABLE goal_events DROP COLUMN IF EXISTS parent_event_id;
