-- Migration 027: whiteboard_entries (the org whiteboard — an INPUT surface)
--
-- The whiteboard is a chatter log, not a durable record (Golda 2026-07-16):
-- people jot project talk as it happens ("got paid 800 on streetwell",
-- "deadline moved to friday"); amebo reads unprocessed entries and FILES the
-- facts where they belong (projects tracker, abra, Taiga, CRM), then stamps
-- processed_at + filed. Entries are append-only input; nothing else in the
-- system references them. This is transient in-flight state — the one kind
-- amebo is allowed to own (BOUNDARIES).

CREATE TABLE IF NOT EXISTS whiteboard_entries (
    id           BIGSERIAL PRIMARY KEY,
    org_id       INT NOT NULL,
    user_id      INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    author       TEXT NOT NULL DEFAULT '',          -- display name at write time
    text         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,                       -- NULL = amebo has not filed it yet
    filed        JSONB                              -- where the facts went, e.g.
                                                    -- [{"store":"projects","ref":"..."}]
);

CREATE INDEX IF NOT EXISTS idx_whiteboard_org_created
    ON whiteboard_entries(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_whiteboard_org_unprocessed
    ON whiteboard_entries(org_id) WHERE processed_at IS NULL;

COMMENT ON TABLE whiteboard_entries IS
    'Org whiteboard: append-only input log. Amebo files facts from entries into '
    'their proper homes and stamps processed_at/filed. Not a record of anything.';

-- ROLLBACK: DROP TABLE IF EXISTS whiteboard_entries;
