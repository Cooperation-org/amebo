-- Migration 026: threads.user_id (per-user chat list)
--
-- The dashboard chat-list sidebar shows a user their OWN web conversations.
-- Web threads had no owner column (author lived only, unreliably, in turn
-- metadata). Stamp the authenticated user on web thread creation so the list +
-- resume can be scoped to them (privacy: never show one member's chat to
-- another). Additive + reversible; NULL = unattributed (older web threads,
-- Slack/email threads — those are scoped by workspace/channel, not this column).

ALTER TABLE threads
    ADD COLUMN IF NOT EXISTS user_id INT REFERENCES platform_users(user_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_threads_user_source ON threads(user_id, source_type, last_active_at DESC);

COMMENT ON COLUMN threads.user_id IS
    'The platform user who owns this thread (stamped for web chats). NULL for '
    'threads that predate this column or are scoped some other way (Slack/email).';

-- ROLLBACK: ALTER TABLE threads DROP COLUMN IF EXISTS user_id;
