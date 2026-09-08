-- Migration 032: echo_entries — a person's own journal / to-do lines on a timeline.
--
-- "Echo" (golda 2026-09-08, after ECCO Pro): the simplest possible interface —
-- enter a line quickly, move it in time, give it a category, drill into it.
-- One row per line. A line belongs to ONE person (user_id), sits on ONE day
-- (on_date), may carry ONE category (free text the person chose), may sit
-- inside another line (parent_id: drill-down), and is done or not (done_at).
-- Org-scoped like everything in amebo, but the person is the owner: nobody
-- else in the org reads these.

CREATE TABLE IF NOT EXISTS echo_entries (
    id          BIGSERIAL PRIMARY KEY,
    org_id      INT NOT NULL,
    user_id     INT NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    parent_id   BIGINT REFERENCES echo_entries(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    category    TEXT,
    on_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    position    INT NOT NULL DEFAULT 0,
    done_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_echo_entries_user_date
    ON echo_entries(user_id, on_date, position, id);
CREATE INDEX IF NOT EXISTS idx_echo_entries_parent
    ON echo_entries(parent_id);

COMMENT ON TABLE echo_entries IS
    'Echo: one person''s journal/to-do lines on a timeline (day, category, parent for drill-down).';

-- ROLLBACK: DROP TABLE IF EXISTS echo_entries;
