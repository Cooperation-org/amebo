-- Migration 013: Coding-agent orchestration
-- Additive only — no changes to existing tables.
-- Adds the coding-agent orchestration subsystem on top of the existing
-- source-agnostic `threads` model (see schema.sql). Design rationale:
-- /opt/shared/projects/Active/amebo/coding-agent-orchestration.md
--
-- Rollback:
--   DROP TABLE IF EXISTS coding_jobs;
--   DROP TABLE IF EXISTS coding_sessions;

-- One coding session per intention thread. Maps a thread to a Claude Agent SDK
-- session (transcript) plus the model and isolated git worktree chosen for it.
-- The model is chosen when the thread opens and kept stable for prompt-cache
-- continuity.
CREATE TABLE IF NOT EXISTS coding_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id       INT  NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    instance_id     INT  REFERENCES instances(id) ON DELETE SET NULL,
    sdk_session_id  TEXT,                       -- Claude Agent SDK session id (NULL until first run)
    model           TEXT NOT NULL,              -- chosen at thread start; stable for cache continuity
    repo_url        TEXT,                       -- repository the session works in (NULL = none yet)
    worktree_path   TEXT,                       -- isolated git worktree for this session
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'idle', 'completed', 'failed', 'archived')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (thread_id)
);

CREATE INDEX IF NOT EXISTS idx_coding_sessions_thread   ON coding_sessions(thread_id);
CREATE INDEX IF NOT EXISTS idx_coding_sessions_instance ON coding_sessions(instance_id);
CREATE INDEX IF NOT EXISTS idx_coding_sessions_status   ON coding_sessions(status);

-- Work queue: one row per inbound message to process for a session. Per-session
-- ordering via seq. Serialization (at most one job per session in flight) is
-- enforced at claim time with a Postgres advisory lock keyed on the session id,
-- so concurrent inputs to one thread cannot race the same worker.
CREATE TABLE IF NOT EXISTS coding_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES coding_sessions(id) ON DELETE CASCADE,
    seq           BIGINT NOT NULL,            -- per-session monotonic order
    prompt        TEXT NOT NULL,              -- the instruction/message to act on
    payload       JSONB DEFAULT '{}',         -- author, attachments, channel hints
    status        TEXT NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'running', 'done', 'error', 'cancelled')),
    result        TEXT,
    error         TEXT,
    attempts      INT NOT NULL DEFAULT 0,
    enqueued_at   TIMESTAMPTZ DEFAULT NOW(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    UNIQUE (session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_coding_jobs_session_seq ON coding_jobs(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_coding_jobs_queued      ON coding_jobs(session_id, seq) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_coding_jobs_running     ON coding_jobs(session_id)       WHERE status = 'running';

COMMENT ON TABLE coding_sessions IS 'One coding-agent session per intention thread; maps thread -> Claude Agent SDK session, model, worktree.';
COMMENT ON TABLE coding_jobs     IS 'Serialized per-session work queue. Ordering by seq; at most one job per session in flight (advisory lock at claim time).';
