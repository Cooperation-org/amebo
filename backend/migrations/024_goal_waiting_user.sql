-- Migration 024: goal status 'waiting_user' (WP12)
--
-- A goal can pause to ASK a human and resume on their reply (arch §8.2):
--   active -> waiting_user (question_asked) -> pending (user_answered) -> active …
-- The scheduler only dispatches pending+active, so waiting_user is skipped
-- automatically. Additive: widen the status CHECK. Reversible.

ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_status_check;
ALTER TABLE goals ADD CONSTRAINT goals_status_check
    CHECK (status IN ('pending','active','completed','failed','paused','waiting_user'));

-- ROLLBACK (no waiting_user rows must exist):
--   ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_status_check;
--   ALTER TABLE goals ADD CONSTRAINT goals_status_check
--     CHECK (status IN ('pending','active','completed','failed','paused'));
