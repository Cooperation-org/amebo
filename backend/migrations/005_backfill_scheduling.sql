-- Migration 005: Backfill Scheduling and Job Tracking
-- Tables for automated backfill scheduling and job status tracking

-- ============================================================================
-- BACKFILL SCHEDULES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS backfill_schedules (
    schedule_id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,

    -- Schedule configuration
    schedule_type VARCHAR(50) NOT NULL DEFAULT 'cron', -- 'cron' or 'manual'
    cron_expression VARCHAR(100) NOT NULL, -- e.g., '0 2 * * *' (daily at 2 AM UTC)
    days_to_backfill INTEGER NOT NULL DEFAULT 7, -- How many days back to fetch
    include_all_channels BOOLEAN NOT NULL DEFAULT TRUE,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMP WITHOUT TIME ZONE,
    next_run_at TIMESTAMP WITHOUT TIME ZONE,

    -- Metadata
    created_by INTEGER REFERENCES platform_users(user_id),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_workspace_schedule UNIQUE (workspace_id),
    CONSTRAINT valid_cron_expression CHECK (cron_expression ~ '^[^\s]+(\s+[^\s]+){4}$')
);

-- Index for lookups
CREATE INDEX idx_backfill_schedules_org ON backfill_schedules(org_id);
CREATE INDEX idx_backfill_schedules_workspace ON backfill_schedules(workspace_id);
CREATE INDEX idx_backfill_schedules_active ON backfill_schedules(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- BACKFILL JOB RUNS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS backfill_job_runs (
    job_run_id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES backfill_schedules(schedule_id) ON DELETE SET NULL,

    -- Job type and status
    job_type VARCHAR(50) NOT NULL, -- 'scheduled' or 'manual'
    status VARCHAR(50) NOT NULL DEFAULT 'running', -- 'running', 'success', 'failed'

    -- Metrics
    messages_collected INTEGER DEFAULT 0,
    channels_processed INTEGER DEFAULT 0,

    -- Error tracking
    error_message TEXT,

    -- Timestamps
    started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITHOUT TIME ZONE,

    -- Constraints
    CONSTRAINT valid_job_type CHECK (job_type IN ('scheduled', 'manual')),
    CONSTRAINT valid_status CHECK (status IN ('running', 'success', 'failed', 'cancelled'))
);

-- Indexes for performance
CREATE INDEX idx_backfill_runs_org ON backfill_job_runs(org_id);
CREATE INDEX idx_backfill_runs_workspace ON backfill_job_runs(workspace_id);
CREATE INDEX idx_backfill_runs_schedule ON backfill_job_runs(schedule_id);
CREATE INDEX idx_backfill_runs_status ON backfill_job_runs(status);
CREATE INDEX idx_backfill_runs_started ON backfill_job_runs(started_at DESC);

-- ============================================================================
-- TRIGGER: Update updated_at timestamp
-- ============================================================================

CREATE OR REPLACE FUNCTION update_backfill_schedules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_backfill_schedules_updated_at
    BEFORE UPDATE ON backfill_schedules
    FOR EACH ROW
    EXECUTE FUNCTION update_backfill_schedules_updated_at();

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE backfill_schedules IS 'Automated backfill scheduling configuration per workspace';
COMMENT ON TABLE backfill_job_runs IS 'Execution history and status tracking for backfill jobs';

COMMENT ON COLUMN backfill_schedules.cron_expression IS 'Cron expression in UTC timezone (e.g., "0 2 * * *" = daily at 2 AM UTC)';
COMMENT ON COLUMN backfill_schedules.days_to_backfill IS 'Number of days to backfill on each run (default: 7)';
COMMENT ON COLUMN backfill_schedules.include_all_channels IS 'Whether to backfill all channels or only configured ones';

COMMENT ON COLUMN backfill_job_runs.job_type IS 'Whether job was triggered by schedule or manually';
COMMENT ON COLUMN backfill_job_runs.status IS 'Current status: running, success, failed, cancelled';
COMMENT ON COLUMN backfill_job_runs.messages_collected IS 'Total messages collected in this run';
COMMENT ON COLUMN backfill_job_runs.channels_processed IS 'Number of channels processed in this run';
