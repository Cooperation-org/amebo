-- Migration 006: Settings & Credential Encryption
-- Add org_settings table for AI configuration
-- Add encrypted credential columns to installations table
-- Add migration path from plaintext to encrypted credentials

-- ============================================================================
-- ORG SETTINGS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_settings (
    org_id INTEGER PRIMARY KEY REFERENCES organizations(org_id) ON DELETE CASCADE,

    -- AI Configuration
    ai_tone VARCHAR(50) DEFAULT 'professional' CHECK (ai_tone IN ('professional', 'casual', 'technical')),
    ai_response_length VARCHAR(50) DEFAULT 'balanced' CHECK (ai_response_length IN ('concise', 'balanced', 'detailed')),
    confidence_threshold INTEGER DEFAULT 40 CHECK (confidence_threshold >= 0 AND confidence_threshold <= 100),
    custom_system_prompt TEXT,

    -- Backfill Settings
    backfill_schedule VARCHAR(50) DEFAULT '0 2 * * *', -- Daily at 2 AM UTC
    backfill_days_back INTEGER DEFAULT 90 CHECK (backfill_days_back >= 1 AND backfill_days_back <= 365),
    auto_backfill_enabled BOOLEAN DEFAULT TRUE,

    -- Feature Flags
    slack_commands_enabled BOOLEAN DEFAULT TRUE,
    web_qa_enabled BOOLEAN DEFAULT TRUE,
    document_upload_enabled BOOLEAN DEFAULT TRUE,

    -- Notification Settings
    email_notifications_enabled BOOLEAN DEFAULT TRUE,
    notify_on_failed_backfill BOOLEAN DEFAULT TRUE,
    weekly_digest_enabled BOOLEAN DEFAULT FALSE,

    -- Data Retention
    message_retention_days INTEGER DEFAULT 365 CHECK (message_retention_days >= 30),

    -- Timestamps
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index for lookups
CREATE INDEX idx_org_settings_org ON org_settings(org_id);

-- ============================================================================
-- UPDATE INSTALLATIONS TABLE - Add Encrypted Columns
-- ============================================================================

-- Add encrypted credential columns (will coexist with plaintext during migration)
ALTER TABLE installations
    ADD COLUMN IF NOT EXISTS bot_token_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS app_token_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS signing_secret_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS encryption_version INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS credentials_encrypted BOOLEAN DEFAULT FALSE;

-- Add bot user ID for reference
ALTER TABLE installations
    ADD COLUMN IF NOT EXISTS bot_user_id VARCHAR(20);

-- Add credential validation tracking
ALTER TABLE installations
    ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS is_valid BOOLEAN DEFAULT TRUE;

-- Index for encrypted credential lookups
CREATE INDEX IF NOT EXISTS idx_installations_encrypted ON installations(credentials_encrypted);

-- ============================================================================
-- TRIGGER: Update updated_at timestamp for org_settings
-- ============================================================================

CREATE OR REPLACE FUNCTION update_org_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_org_settings_updated_at
    BEFORE UPDATE ON org_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_org_settings_updated_at();

-- ============================================================================
-- DEFAULT SETTINGS FOR EXISTING ORGANIZATIONS
-- ============================================================================

-- Create default settings for all existing organizations
INSERT INTO org_settings (org_id)
SELECT org_id FROM organizations
ON CONFLICT (org_id) DO NOTHING;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE org_settings IS 'Organization-level configuration for AI behavior, backfills, and features';
COMMENT ON TABLE installations IS 'Slack workspace installations with encrypted credentials';

COMMENT ON COLUMN org_settings.ai_tone IS 'AI response tone: professional, casual, or technical';
COMMENT ON COLUMN org_settings.ai_response_length IS 'AI response verbosity: concise, balanced, or detailed';
COMMENT ON COLUMN org_settings.confidence_threshold IS 'Minimum confidence (0-100) to return an answer';
COMMENT ON COLUMN org_settings.custom_system_prompt IS 'Custom instructions for AI behavior';

COMMENT ON COLUMN org_settings.backfill_schedule IS 'Cron expression for automated backfills (e.g., "0 2 * * *")';
COMMENT ON COLUMN org_settings.backfill_days_back IS 'Number of days to backfill (1-365)';
COMMENT ON COLUMN org_settings.auto_backfill_enabled IS 'Whether to run automated backfills';

COMMENT ON COLUMN org_settings.message_retention_days IS 'Number of days to retain messages before auto-deletion';

COMMENT ON COLUMN installations.bot_token_encrypted IS 'Encrypted Slack bot token (Fernet encrypted)';
COMMENT ON COLUMN installations.app_token_encrypted IS 'Encrypted Slack app token (Fernet encrypted)';
COMMENT ON COLUMN installations.signing_secret_encrypted IS 'Encrypted Slack signing secret (Fernet encrypted)';
COMMENT ON COLUMN installations.credentials_encrypted IS 'TRUE if using encrypted columns, FALSE if using plaintext';
COMMENT ON COLUMN installations.encryption_version IS 'Encryption scheme version for key rotation';
COMMENT ON COLUMN installations.bot_user_id IS 'Slack bot user ID (e.g., U01234ABCDE)';
COMMENT ON COLUMN installations.is_valid IS 'Whether credentials are currently valid';
COMMENT ON COLUMN installations.last_verified_at IS 'Last time credentials were verified against Slack API';

-- ============================================================================
-- MIGRATION NOTES
-- ============================================================================

/*
MIGRATION PATH FROM PLAINTEXT TO ENCRYPTED:

1. This migration adds encrypted columns but keeps plaintext columns
2. Both column sets will coexist during transition
3. Application will:
   - Read from encrypted columns if credentials_encrypted = TRUE
   - Read from plaintext columns if credentials_encrypted = FALSE
   - Gradually migrate credentials using encryption utility

To encrypt existing credentials:
   UPDATE installations
   SET
       bot_token_encrypted = encrypt_function(bot_token),
       app_token_encrypted = encrypt_function(app_token),
       signing_secret_encrypted = encrypt_function(signing_secret),
       credentials_encrypted = TRUE
   WHERE credentials_encrypted = FALSE;

After all credentials are encrypted, plaintext columns can be dropped in a future migration.

SECURITY NOTES:
- Use ENCRYPTION_KEY environment variable (never commit to code)
- Rotate encryption keys periodically
- Encrypted columns use Fernet symmetric encryption
- Backup database before running encryption migration
*/
