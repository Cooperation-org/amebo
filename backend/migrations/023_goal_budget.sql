-- Migration 023: per-goal budget (WP16)
--
-- A goal can carry a budget cap so a runaway pursuit pauses instead of
-- iterating forever (arch §8.3). JSONB: {max_dispatches, max_tokens}. NULL = no
-- per-goal cap (falls back to the instance config default). Additive + reversible.

ALTER TABLE goals
    ADD COLUMN IF NOT EXISTS budget JSONB;

COMMENT ON COLUMN goals.budget IS
    'Per-goal budget cap (WP16): {"max_dispatches": N, "max_tokens": N}. NULL = '
    'no per-goal cap (instance config default applies). Exhaustion -> paused + '
    'one notification.';

-- ROLLBACK: ALTER TABLE goals DROP COLUMN IF EXISTS budget;
