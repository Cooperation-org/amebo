-- Migration 017: Thread retention marker for State Decay + Per-Store GC
-- Additive only. Adds one nullable column to `threads`. No existing data is
-- changed; existing rows get retained_until = NULL (the default), which means
-- "not explicitly kept" — i.e. the normal decay policy applies.
--
-- DESIGN NOTE (Amebo BOUNDARIES, 2026-06-06):
--   Amebo holds as little state as it can. Its working state decays unless
--   Amebo judges there is a reason to keep something. When the retention
--   judgment (see services/state_decay/judgment.py) decides a thread is worth
--   keeping past its normal TTL, it stamps `retained_until` with a future
--   timestamp. The thread store's GC policy treats a thread as "kept" while
--   `retained_until > NOW()` and will not expire it. A NULL value means no
--   explicit retention decision — the thread decays on the ordinary stale
--   window (last_active_at based).
--
-- Why a dedicated column rather than reusing an existing field:
--   - last_active_at drives the TTL window; overloading it to also mean
--     "keep this" would conflate "recently touched" with "deliberately kept".
--   - summary/summary_through_turn_id are about compaction, not retention.
--   A separate nullable timestamp keeps the two concerns independent and lets
--   a retention decision outlive activity (a quiet-but-important thread).
--
-- NOT APPLIED automatically. This file is committed for review; apply it
-- through the normal migration process against the amebo DB when ready.

ALTER TABLE threads
    ADD COLUMN IF NOT EXISTS retained_until TIMESTAMPTZ;

COMMENT ON COLUMN threads.retained_until IS
    'State-decay retention marker. When > NOW(), the thread is "kept" and the '
    'thread-store GC will not expire it regardless of last_active_at. NULL '
    'means no explicit retention decision (normal decay applies). Set by the '
    'retention-judgment hook in services/state_decay/judgment.py.';

-- Partial index: GC only ever cares about rows that are currently retained,
-- which is the small minority. Keeps the "is this kept?" check cheap.
CREATE INDEX IF NOT EXISTS idx_threads_retained_until
    ON threads(retained_until)
    WHERE retained_until IS NOT NULL;
