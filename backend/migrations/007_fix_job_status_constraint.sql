-- Migration 007: Fix backfill_job_runs status constraint
-- Add 'skipped' to the valid status values

-- Drop the old constraint
ALTER TABLE backfill_job_runs
DROP CONSTRAINT IF EXISTS valid_status;

-- Add the new constraint with 'skipped' included
ALTER TABLE backfill_job_runs
ADD CONSTRAINT valid_status
CHECK (status IN ('running', 'success', 'failed', 'cancelled', 'skipped'));

-- Update comment
COMMENT ON COLUMN backfill_job_runs.status IS 'Current status: running, success, failed, cancelled, skipped';
