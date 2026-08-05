-- Migration 030: work_list_marks (pin and bury — the person overruling the rank)
--
-- The list shows at most twenty rows (LIST_MAX). That cap is what makes these
-- two gestures necessary: ranking can otherwise drop something the reader
-- decided matters, which breaks the rule that the UX respects the user's
-- intention. Golda 2026-08-05: "either it should always be in the top twenty
-- list, or right now it shouldn't be, but maybe in the future it might again."
--
--   pinned  — always shown, above the cap, never re-ranked out.
--   buried  — not in the top list right now. NOT deleted and NOT forever: it
--             stays visible in its own bucket and comes back on its own when a
--             deadline arrives, or the moment the person unburies it.
--
-- A mark is a fact about a PERSON and a SUBJECT, and nothing else. It says
-- nothing about the task, so Taiga and the CRM never hear about it — this is
-- amebo's own in-flight state, the one kind amebo is allowed to own
-- (docs/BOUNDARIES.md). The subject is amebo's URI ('taiga:board#34',
-- 'crm:lead/46', 'goal:...'), which is why the mark can live here at all.
--
-- Keyed by the person's amebo login email, the same key the identity maps use
-- (services/viewer_identity.py), so a mark survives anything but a change of
-- login. One mark per person per subject: pinning something buried replaces the
-- burial rather than leaving the two to contradict each other.

CREATE TABLE IF NOT EXISTS work_list_marks (
    id         BIGSERIAL PRIMARY KEY,
    org_id     INT NOT NULL,
    person     TEXT NOT NULL,                        -- amebo login email, lowercased
    subject    TEXT NOT NULL,                        -- 'taiga:board#34', 'crm:lead/46', ...
    state      TEXT NOT NULL CHECK (state IN ('pinned', 'buried')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, person, subject)
);

CREATE INDEX IF NOT EXISTS idx_work_list_marks_person
    ON work_list_marks(org_id, person);

COMMENT ON TABLE work_list_marks IS
    'Pin and bury: one person''s override of where a work-list subject sits. '
    'Amebo in-flight state only — never mirrored into Taiga or the CRM.';

-- ROLLBACK: DROP TABLE IF EXISTS work_list_marks;
