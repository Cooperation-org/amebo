-- Migration 014: mail poller state
-- Additive only. Bookkeeping for the email->CRM poller (idempotency + dead-letter).
-- Lives in the amebo DB; Odoo stays clean. Design: docs/email-poller-architecture.md
--
-- Rollback:
--   DROP TABLE IF EXISTS mail_dead_letter;
--   DROP TABLE IF EXISTS mail_seen;

-- Idempotency: Message-IDs we've already processed. Bounded by TTL purge
-- (poller deletes rows older than MAIL_POLLER_SEEN_TTL_DAYS) so a spammer can't
-- grow it without limit.
CREATE TABLE IF NOT EXISTS mail_seen (
    message_id  TEXT PRIMARY KEY,
    seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mail_seen_at ON mail_seen(seen_at);

-- Dead-letter: anything we did not file (security fail, no match, ambiguous,
-- error). Reviewed via CLI; never a silent drop.
CREATE TABLE IF NOT EXISTS mail_dead_letter (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id  TEXT,
    reason      TEXT NOT NULL,   -- sender_not_allowlisted | dkim_not_passed | no_match | ambiguous | auto_reply | error
    from_addr   TEXT,
    to_addrs    TEXT,
    subject     TEXT,
    tag         TEXT,            -- +crm | +project | ...
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mail_dead_letter_created ON mail_dead_letter(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mail_dead_letter_reason  ON mail_dead_letter(reason);

COMMENT ON TABLE mail_seen        IS 'Processed Message-IDs for poller idempotency. TTL-purged.';
COMMENT ON TABLE mail_dead_letter IS 'Emails the poller did not file, with reason. Reviewed via CLI.';
