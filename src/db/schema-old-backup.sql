-- Slack Helper Bot - Database Schema
-- Phase 1: Comprehensive Data Collection
-- PostgreSQL 14+

-- ============================================================================
-- CORE DATA TABLES
-- ============================================================================

-- 1. MESSAGES: Central storage for all Slack messages
CREATE TABLE IF NOT EXISTS messages (
    message_id SERIAL PRIMARY KEY,
    slack_ts VARCHAR(20) UNIQUE NOT NULL,
    channel_id VARCHAR(20) NOT NULL,
    channel_name VARCHAR(255),
    user_id VARCHAR(20) NOT NULL,
    user_name VARCHAR(255),
    message_text TEXT,
    message_type VARCHAR(50) DEFAULT 'regular', -- 'regular', 'thread_reply', 'bot_message', 'file_share'
    thread_ts VARCHAR(20), -- Parent thread timestamp if reply
    reply_count INT DEFAULT 0,
    reply_users_count INT DEFAULT 0,
    attachments JSONB, -- Files, images, link previews
    mentions JSONB, -- User/channel mentions
    blocks JSONB, -- Slack's structured message blocks (rich formatting)
    permalink TEXT,
    is_pinned BOOLEAN DEFAULT false,
    edited_at TIMESTAMP,
    deleted_at TIMESTAMP, -- Soft delete
    created_at TIMESTAMP NOT NULL,
    raw_data JSONB -- Complete Slack event payload
);

-- Message indexes
CREATE INDEX idx_messages_channel_time ON messages(channel_id, created_at DESC);
CREATE INDEX idx_messages_thread ON messages(thread_ts) WHERE thread_ts IS NOT NULL;
CREATE INDEX idx_messages_user ON messages(user_id, created_at DESC);
CREATE INDEX idx_messages_search ON messages USING GIN(to_tsvector('english', message_text));
CREATE INDEX idx_messages_slack_ts ON messages(slack_ts);
CREATE INDEX idx_messages_deleted ON messages(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_messages_pinned ON messages(is_pinned) WHERE is_pinned = true;
CREATE INDEX idx_messages_type ON messages(message_type);

-- ============================================================================

-- 2. REACTIONS: Normalized reaction tracking
CREATE TABLE IF NOT EXISTS reactions (
    reaction_id SERIAL PRIMARY KEY,
    message_id INT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    user_id VARCHAR(20) NOT NULL,
    user_name VARCHAR(255),
    reaction_name VARCHAR(100) NOT NULL, -- 'thumbsup', 'heart', 'fire', etc.
    reacted_at TIMESTAMP DEFAULT NOW()
);

-- Reaction indexes
CREATE INDEX idx_reactions_message ON reactions(message_id);
CREATE INDEX idx_reactions_user ON reactions(user_id);
CREATE INDEX idx_reactions_name ON reactions(reaction_name);
CREATE UNIQUE INDEX idx_reactions_unique ON reactions(message_id, user_id, reaction_name);

-- View for reaction counts (convenient for queries)
CREATE OR REPLACE VIEW reaction_counts AS
SELECT
    message_id,
    reaction_name,
    COUNT(*) as count,
    ARRAY_AGG(user_id) as users
FROM reactions
GROUP BY message_id, reaction_name;

-- ============================================================================

-- 3. CHANNELS: Channel metadata and sync configuration
CREATE TABLE IF NOT EXISTS channels (
    channel_id VARCHAR(20) PRIMARY KEY,
    channel_name VARCHAR(255) NOT NULL,
    is_private BOOLEAN DEFAULT false,
    is_archived BOOLEAN DEFAULT false,
    is_general BOOLEAN DEFAULT false,
    purpose TEXT,
    topic TEXT,
    member_count INT,
    creator_id VARCHAR(20),
    last_message_ts VARCHAR(20),
    created_at TIMESTAMP,
    last_sync TIMESTAMP,
    sync_enabled BOOLEAN DEFAULT true
);

CREATE INDEX idx_channels_sync ON channels(sync_enabled, last_sync);
CREATE INDEX idx_channels_archived ON channels(is_archived) WHERE is_archived = false;
CREATE INDEX idx_channels_name ON channels(channel_name);

-- ============================================================================

-- 4. USERS: User profiles and metadata
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(20) PRIMARY KEY,
    user_name VARCHAR(255),
    real_name VARCHAR(255),
    display_name VARCHAR(255),
    email VARCHAR(255),
    title VARCHAR(255),
    department VARCHAR(255),
    team_id VARCHAR(20),
    is_bot BOOLEAN DEFAULT false,
    is_admin BOOLEAN DEFAULT false,
    is_owner BOOLEAN DEFAULT false,
    is_restricted BOOLEAN DEFAULT false, -- Guest user
    timezone VARCHAR(50),
    avatar_url TEXT,
    status_text VARCHAR(255),
    status_emoji VARCHAR(50),
    last_seen TIMESTAMP,
    joined_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_users_name ON users(user_name);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_is_bot ON users(is_bot) WHERE is_bot = false;
CREATE INDEX idx_users_team ON users(team_id);

-- ============================================================================

-- 5. THREAD_PARTICIPANTS: Track who contributed to which threads
CREATE TABLE IF NOT EXISTS thread_participants (
    participant_id SERIAL PRIMARY KEY,
    thread_ts VARCHAR(20) NOT NULL, -- The parent message timestamp
    channel_id VARCHAR(20) NOT NULL,
    user_id VARCHAR(20) NOT NULL,
    message_count INT DEFAULT 0, -- How many replies this user made
    first_reply_at TIMESTAMP,
    last_reply_at TIMESTAMP,
    UNIQUE(thread_ts, user_id)
);

CREATE INDEX idx_thread_participants_thread ON thread_participants(thread_ts);
CREATE INDEX idx_thread_participants_user ON thread_participants(user_id);
CREATE INDEX idx_thread_participants_channel ON thread_participants(channel_id);

-- ============================================================================

-- 6. LINKS: Extracted URLs for quick access to PRs, docs, issues
CREATE TABLE IF NOT EXISTS links (
    link_id SERIAL PRIMARY KEY,
    message_id INT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    link_type VARCHAR(50), -- 'github_pr', 'github_issue', 'jira', 'docs', 'confluence', 'notion', 'other'
    domain VARCHAR(255),
    title TEXT, -- Extracted from preview
    description TEXT, -- Link preview description
    extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_links_type ON links(link_type);
CREATE INDEX idx_links_message ON links(message_id);
CREATE INDEX idx_links_domain ON links(domain);
CREATE INDEX idx_links_url_hash ON links(MD5(url)); -- Fast duplicate detection

-- ============================================================================

-- 7. FILES: File uploads and document tracking
CREATE TABLE IF NOT EXISTS files (
    file_id SERIAL PRIMARY KEY,
    slack_file_id VARCHAR(50) UNIQUE NOT NULL,
    message_id INT REFERENCES messages(message_id) ON DELETE SET NULL,
    file_name VARCHAR(500),
    file_type VARCHAR(50), -- pdf, docx, png, etc.
    file_size BIGINT,
    mime_type VARCHAR(100),
    url_private TEXT, -- Slack's private download URL
    url_private_download TEXT, -- Direct download URL
    permalink TEXT,
    local_path TEXT, -- Where we stored it locally/S3
    content TEXT, -- Extracted text (populated in Phase 2)
    uploaded_by VARCHAR(20) REFERENCES users(user_id),
    uploaded_at TIMESTAMP,
    downloaded_at TIMESTAMP,
    parsed_at TIMESTAMP
);

CREATE INDEX idx_files_message ON files(message_id);
CREATE INDEX idx_files_type ON files(file_type);
CREATE INDEX idx_files_uploader ON files(uploaded_by);
CREATE INDEX idx_files_slack_id ON files(slack_file_id);

-- ============================================================================

-- 8. BOOKMARKS: User-saved messages (Slack's bookmark feature)
CREATE TABLE IF NOT EXISTS bookmarks (
    bookmark_id SERIAL PRIMARY KEY,
    channel_id VARCHAR(20) NOT NULL,
    slack_bookmark_id VARCHAR(50) UNIQUE,
    title VARCHAR(500),
    link TEXT,
    emoji VARCHAR(50),
    created_by VARCHAR(20) REFERENCES users(user_id),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    position INT -- Display order in channel
);

CREATE INDEX idx_bookmarks_channel ON bookmarks(channel_id);
CREATE INDEX idx_bookmarks_creator ON bookmarks(created_by);

-- ============================================================================

-- 9. WORKSPACE: Organization/workspace metadata
CREATE TABLE IF NOT EXISTS workspace (
    workspace_id VARCHAR(20) PRIMARY KEY,
    team_name VARCHAR(255) NOT NULL,
    team_domain VARCHAR(255), -- yourcompany.slack.com
    email_domain VARCHAR(255),
    icon_url TEXT,
    plan VARCHAR(50), -- 'free', 'pro', 'business', 'enterprise'
    created_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================

-- 10. TEAMS: Sub-teams within workspace (Enterprise Grid)
CREATE TABLE IF NOT EXISTS teams (
    team_id VARCHAR(20) PRIMARY KEY,
    workspace_id VARCHAR(20) REFERENCES workspace(workspace_id),
    team_name VARCHAR(255) NOT NULL,
    team_domain VARCHAR(255),
    icon_url TEXT,
    created_at TIMESTAMP
);

CREATE INDEX idx_teams_workspace ON teams(workspace_id);

-- ============================================================================
-- OPERATIONAL TABLES
-- ============================================================================

-- 11. SYNC_STATUS: Track sync progress per channel
CREATE TABLE IF NOT EXISTS sync_status (
    sync_id SERIAL PRIMARY KEY,
    channel_id VARCHAR(20) NOT NULL REFERENCES channels(channel_id),
    last_message_ts VARCHAR(20), -- Most recent message synced
    oldest_message_ts VARCHAR(20), -- Oldest message synced (for backfill)
    messages_synced INT DEFAULT 0,
    total_messages INT, -- Estimated from Slack API
    sync_started_at TIMESTAMP,
    sync_completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed', 'paused'
    error_message TEXT,
    sync_type VARCHAR(20) -- 'backfill', 'incremental', 'realtime'
);

CREATE INDEX idx_sync_status_channel ON sync_status(channel_id);
CREATE INDEX idx_sync_status_status ON sync_status(status);
CREATE UNIQUE INDEX idx_sync_status_active ON sync_status(channel_id, status)
    WHERE status IN ('running', 'pending');

-- ============================================================================

-- 12. PROCESSING_QUEUE: Async job tracking
CREATE TABLE IF NOT EXISTS processing_queue (
    queue_id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(message_id) ON DELETE CASCADE,
    process_type VARCHAR(50) NOT NULL, -- 'embedding', 'summarization', 'link_extraction', 'file_download', 'file_parse'
    priority INT DEFAULT 5, -- 1 (high) to 10 (low)
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    last_error TEXT,
    metadata JSONB, -- Additional job-specific data
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_processing_queue_status ON processing_queue(status, priority);
CREATE INDEX idx_processing_queue_type ON processing_queue(process_type, status);
CREATE INDEX idx_processing_queue_message ON processing_queue(message_id);

-- ============================================================================

-- 13. BOT_CONFIG: Runtime configuration
CREATE TABLE IF NOT EXISTS bot_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Default configurations
INSERT INTO bot_config (config_key, config_value, description) VALUES
('sync_frequency_minutes', '5', 'How often to run incremental sync'),
('backfill_days', '90', 'How far back to sync on first run'),
('max_messages_per_batch', '100', 'Messages to fetch per API call'),
('excluded_channels', '[]', 'Channel IDs or names to skip'),
('file_download_enabled', 'true', 'Whether to download file contents'),
('max_file_size_mb', '50', 'Maximum file size to download')
ON CONFLICT (config_key) DO NOTHING;

-- ============================================================================
-- PHASE 2 PREPARATION (Not implemented yet)
-- ============================================================================

-- 14. MESSAGE_EMBEDDINGS: Vector embeddings for semantic search
-- NOTE: Requires pgvector extension
-- Uncomment when ready for Phase 2:

/*
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS message_embeddings (
    embedding_id SERIAL PRIMARY KEY,
    message_id INT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    embedding_vector VECTOR(1536), -- OpenAI ada-002: 1536 dimensions
    embedding_model VARCHAR(50) NOT NULL, -- 'text-embedding-ada-002', 'all-MiniLM-L6-v2', etc.
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(message_id, embedding_model)
);

CREATE INDEX idx_embeddings_message ON message_embeddings(message_id);
-- Vector similarity index (add after populating data):
-- CREATE INDEX idx_embeddings_vector ON message_embeddings
--   USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100);
*/

-- ============================================================================
-- USEFUL VIEWS
-- ============================================================================

-- Most active threads
CREATE OR REPLACE VIEW active_threads AS
SELECT
    m.thread_ts,
    m.channel_id,
    m.channel_name,
    m.message_text as thread_starter,
    m.user_name as thread_starter_user,
    m.reply_count,
    m.reply_users_count,
    m.created_at as thread_started_at,
    COUNT(tp.user_id) as unique_participants
FROM messages m
LEFT JOIN thread_participants tp ON m.slack_ts = tp.thread_ts
WHERE m.thread_ts IS NULL AND m.reply_count > 0
GROUP BY m.thread_ts, m.channel_id, m.channel_name, m.message_text, m.user_name, m.reply_count, m.reply_users_count, m.created_at
ORDER BY m.reply_count DESC;

-- Most reacted messages
CREATE OR REPLACE VIEW most_reacted_messages AS
SELECT
    m.message_id,
    m.slack_ts,
    m.channel_name,
    m.user_name,
    m.message_text,
    m.permalink,
    COUNT(r.reaction_id) as total_reactions,
    COUNT(DISTINCT r.reaction_name) as unique_reaction_types,
    m.created_at
FROM messages m
INNER JOIN reactions r ON m.message_id = r.message_id
GROUP BY m.message_id, m.slack_ts, m.channel_name, m.user_name, m.message_text, m.permalink, m.created_at
ORDER BY total_reactions DESC;

-- Channel activity summary
CREATE OR REPLACE VIEW channel_activity AS
SELECT
    c.channel_id,
    c.channel_name,
    c.is_private,
    c.member_count,
    COUNT(m.message_id) as total_messages,
    COUNT(DISTINCT m.user_id) as active_users,
    MAX(m.created_at) as last_activity,
    COUNT(CASE WHEN m.created_at > NOW() - INTERVAL '7 days' THEN 1 END) as messages_last_7_days,
    COUNT(CASE WHEN m.created_at > NOW() - INTERVAL '30 days' THEN 1 END) as messages_last_30_days
FROM channels c
LEFT JOIN messages m ON c.channel_id = m.channel_id AND m.deleted_at IS NULL
GROUP BY c.channel_id, c.channel_name, c.is_private, c.member_count
ORDER BY messages_last_7_days DESC;

-- User activity summary
CREATE OR REPLACE VIEW user_activity AS
SELECT
    u.user_id,
    u.user_name,
    u.real_name,
    u.title,
    u.department,
    COUNT(m.message_id) as total_messages,
    COUNT(DISTINCT m.channel_id) as channels_active_in,
    MAX(m.created_at) as last_message_at,
    COUNT(CASE WHEN m.created_at > NOW() - INTERVAL '7 days' THEN 1 END) as messages_last_7_days
FROM users u
LEFT JOIN messages m ON u.user_id = m.user_id AND m.deleted_at IS NULL
WHERE u.is_bot = false
GROUP BY u.user_id, u.user_name, u.real_name, u.title, u.department
ORDER BY messages_last_7_days DESC;

-- ============================================================================
-- CONSTRAINTS & VALIDATION
-- ============================================================================

-- Ensure thread_ts references a real message (optional, can be heavy)
-- ALTER TABLE messages ADD CONSTRAINT fk_thread_parent
--   FOREIGN KEY (thread_ts) REFERENCES messages(slack_ts) DEFERRABLE INITIALLY DEFERRED;

-- Ensure timestamps are reasonable
ALTER TABLE messages ADD CONSTRAINT check_created_at_valid
    CHECK (created_at <= NOW() + INTERVAL '1 hour');

ALTER TABLE messages ADD CONSTRAINT check_edited_after_created
    CHECK (edited_at IS NULL OR edited_at >= created_at);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to update thread participant stats
CREATE OR REPLACE FUNCTION update_thread_participants()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.thread_ts IS NOT NULL THEN
        INSERT INTO thread_participants (thread_ts, channel_id, user_id, message_count, first_reply_at, last_reply_at)
        VALUES (NEW.thread_ts, NEW.channel_id, NEW.user_id, 1, NEW.created_at, NEW.created_at)
        ON CONFLICT (thread_ts, user_id)
        DO UPDATE SET
            message_count = thread_participants.message_count + 1,
            last_reply_at = NEW.created_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update thread participants
CREATE TRIGGER trigger_update_thread_participants
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION update_thread_participants();

-- ============================================================================
-- MAINTENANCE
-- ============================================================================

-- Regular vacuum and analyze for performance
-- Run this weekly via cron or scheduler:
-- VACUUM ANALYZE messages;
-- VACUUM ANALYZE reactions;
-- VACUUM ANALYZE links;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE messages IS 'Core message storage with full Slack metadata';
COMMENT ON TABLE reactions IS 'Normalized reaction tracking for analytics';
COMMENT ON TABLE channels IS 'Channel metadata and sync configuration';
COMMENT ON TABLE users IS 'User profiles and organizational info';
COMMENT ON TABLE thread_participants IS 'Track conversation participation';
COMMENT ON TABLE links IS 'Extracted URLs for PR/doc discovery';
COMMENT ON TABLE files IS 'File metadata and content storage';
COMMENT ON TABLE bookmarks IS 'Channel bookmarks and pinned resources';
COMMENT ON TABLE workspace IS 'Slack workspace metadata';
COMMENT ON TABLE teams IS 'Sub-teams for Enterprise Grid';
COMMENT ON TABLE sync_status IS 'Track data collection progress';
COMMENT ON TABLE processing_queue IS 'Async job processing queue';
COMMENT ON TABLE bot_config IS 'Runtime configuration key-value store';

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
