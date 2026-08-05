-- Migration 031: org_statements (mission, vision, values, OKRs — what an org
-- is aiming at, in its own words)
--
-- Golda 2026-08-05: "these are important Concepts to have but people are not
-- going to be entering those in a database ... they're going to evolve
-- organically, they're going to come from meeting transcripts and texts and
-- documents". And: "Mission Vision those kind of things should probably live
-- in a document that has a pointer to it ... the way we know to use it is by
-- the semantics of the thing pointing to it."
--
-- So this table is NOT a mission statement. It is the POINTER, and the pointer
-- carries the meaning. `name` is the relation ('mission', 'values', 'Q3 OKRs')
-- in the team's own word, not a fixed vocabulary — a team with "operating
-- principles" writes that and it works. Nothing parses the document.
--
-- Before this, the goal dispatcher guessed: it ran a vector search for the
-- literal words "vision" and "values" against abra and hoped. That is not
-- editable by the people it affects, and there was no page where they could
-- see what was steering their own prioritization. Both are fixed here.
--
-- Where the words live:
--   body     — held here, because someone pasted them. Verbatim, always.
--   pointer  — held elsewhere and read at use time (a URL, a file in the org's
--              context repo, a name in abra). One of the two, never both.
--
-- BOUNDARIES: a pointer is a reference, which is amebo's whole job (I1). A
-- pasted body is the one case amebo holds words, and it holds them exactly as
-- typed — the words are the team's, so amebo may not rewrite them. Anything
-- amebo proposes has accepted_at NULL and does nothing until a human accepts.

CREATE TABLE IF NOT EXISTS org_statements (
    id          BIGSERIAL PRIMARY KEY,
    org_id      INT NOT NULL,
    holder      TEXT NOT NULL DEFAULT 'org',      -- 'org' today; 'project:<slug>',
                                                  -- 'person:<login>' when a project
                                                  -- or a person holds its own
    name        TEXT NOT NULL,                    -- the relation, their word
    body        TEXT,                             -- their words, verbatim
    pointer     TEXT,                             -- URI when the words live elsewhere
    source      TEXT NOT NULL DEFAULT '',         -- where it came from, their words
                                                  -- ("photo of the whiteboard, 4 aug")
    informs_priority BOOLEAN NOT NULL DEFAULT FALSE,
    written_by  TEXT NOT NULL DEFAULT '',         -- amebo login, or 'claw' for a proposal
    accepted_at TIMESTAMPTZ,                      -- NULL = proposed, not live
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Words or a pointer to words. A row that is neither says nothing.
    CONSTRAINT org_statements_has_words
        CHECK ((body IS NOT NULL AND btrim(body) <> '') <> (pointer IS NOT NULL AND btrim(pointer) <> ''))
);

-- The read the dispatcher does on every run: what steers this org right now.
CREATE INDEX IF NOT EXISTS idx_org_statements_live
    ON org_statements(org_id, holder)
    WHERE accepted_at IS NOT NULL AND informs_priority;

CREATE INDEX IF NOT EXISTS idx_org_statements_org
    ON org_statements(org_id, created_at DESC);

COMMENT ON TABLE org_statements IS
    'Mission/vision/values/OKRs as named pointers or pasted words. The name is '
    'the relation and carries the meaning; nothing parses the document. Rows '
    'with informs_priority feed goal pursuit. Never rewritten by amebo.';

COMMENT ON COLUMN org_statements.name IS
    'The relation, in the team''s own word: mission, vision, values, strategy, '
    'Q3 OKRs, operating principles. Deliberately not an enum.';

COMMENT ON COLUMN org_statements.accepted_at IS
    'NULL = proposed and inert. A human accepting is what makes it live; that '
    'is the only ceremony in the whole subsystem.';

-- ROLLBACK: DROP TABLE IF EXISTS org_statements;
