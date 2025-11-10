-- Slack Helper Bot - Hybrid Architecture Schema
-- PostgreSQL (Metadata) + ChromaDB (Content + Vectors)
-- Multi-Tenant Ready
-- PostgreSQL 14+

-- ============================================================================
-- MULTI-TENANT CORE
-- ============================================================================

-- 1. WORKSPACES: Organization/workspace tracking
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id VARCHAR(20) PRIMARY KEY,
    team_name VARCHAR(255) NOT NULL,
    team_domain VARCHAR(255), -- yourcompany.slack.com
    email_domain VARCHAR(255),
    icon_url TEXT,
    plan VARCHAR(50), -- 'free', 'pro', 'business', 'enterprise'
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_workspaces_active ON workspaces(is_active) WHERE is_active = true;
CREATE INDEX idx_workspaces_domain ON workspaces(team_domain);

-- ============================================================================

-- 2. INSTALLATIONS: Track bot installations per workspace
CREATE TABLE IF NOT EXISTS installations (
    installation_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    bot_token TEXT NOT NULL, -- Encrypted in production!
    app_token TEXT, -- For Socket Mode
    signing_secret TEXT,
    installed_by VARCHAR(20),
    installed_at TIMESTAMP DEFAULT NOW(),
    last_active TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    UNIQUE(workspace_id)
);

CREATE INDEX idx_installations_workspace ON installations(workspace_id);
CREATE INDEX idx_installations_active ON installations(is_active) WHERE is_active = true;

-- ============================================================================
-- CORE DATA TABLES (Multi-Tenant)
-- ============================================================================

-- 3. MESSAGE_METADATA: Lightweight message records (NO TEXT - that's in ChromaDB)
CREATE TABLE IF NOT EXISTS message_metadata (
    message_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    slack_ts VARCHAR(20) NOT NULL,
    channel_id VARCHAR(20) NOT NULL,
    channel_name VARCHAR(255),
    user_id VARCHAR(20) NOT NULL,
    user_name VARCHAR(255),
    message_type VARCHAR(50) DEFAULT 'regular', -- 'regular', 'thread_reply', 'bot_message', 'file_share'
    thread_ts VARCHAR(20), -- Parent thread timestamp if reply
    reply_count INT DEFAULT 0,
    reply_users_count INT DEFAULT 0,
    has_attachments BOOLEAN DEFAULT false,
    has_files BOOLEAN DEFAULT false,
    has_reactions BOOLEAN DEFAULT false,
    mention_count INT DEFAULT 0,
    link_count INT DEFAULT 0,
    permalink TEXT,
    is_pinned BOOLEAN DEFAULT false,
    edited_at TIMESTAMP,
    deleted_at TIMESTAMP, -- Soft delete
    created_at TIMESTAMP NOT NULL,
    chromadb_id VARCHAR(100), -- Reference to ChromaDB document
    UNIQUE(workspace_id, slack_ts)
);

-- Message metadata indexes
CREATE INDEX idx_message_metadata_workspace ON message_metadata(workspace_id);
CREATE INDEX idx_message_metadata_channel_time ON message_metadata(workspace_id, channel_id, created_at DESC);
CREATE INDEX idx_message_metadata_thread ON message_metadata(workspace_id, thread_ts) WHERE thread_ts IS NOT NULL;
CREATE INDEX idx_message_metadata_user ON message_metadata(workspace_id, user_id, created_at DESC);
CREATE INDEX idx_message_metadata_slack_ts ON message_metadata(workspace_id, slack_ts);
CREATE INDEX idx_message_metadata_deleted ON message_metadata(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_message_metadata_pinned ON message_metadata(is_pinned) WHERE is_pinned = true;
CREATE INDEX idx_message_metadata_type ON message_metadata(message_type);
CREATE INDEX idx_message_metadata_chromadb ON message_metadata(chromadb_id);

-- ============================================================================

-- 4. REACTIONS: Normalized reaction tracking
CREATE TABLE IF NOT EXISTS reactions (
    reaction_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    message_id INT NOT NULL REFERENCES message_metadata(message_id) ON DELETE CASCADE,
    user_id VARCHAR(20) NOT NULL,
    user_name VARCHAR(255),
    reaction_name VARCHAR(100) NOT NULL, -- 'thumbsup', 'heart', 'fire', etc.
    reacted_at TIMESTAMP DEFAULT NOW()
);

-- Reaction indexes
CREATE INDEX idx_reactions_workspace ON reactions(workspace_id);
CREATE INDEX idx_reactions_message ON reactions(message_id);
CREATE INDEX idx_reactions_user ON reactions(workspace_id, user_id);
CREATE INDEX idx_reactions_name ON reactions(reaction_name);
CREATE UNIQUE INDEX idx_reactions_unique ON reactions(workspace_id, message_id, user_id, reaction_name);

-- View for reaction counts
CREATE OR REPLACE VIEW reaction_counts AS
SELECT
    workspace_id,
    message_id,
    reaction_name,
    COUNT(*) as count,
    ARRAY_AGG(user_id) as users
FROM reactions
GROUP BY workspace_id, message_id, reaction_name;

-- ============================================================================

-- 5. CHANNELS: Channel metadata
CREATE TABLE IF NOT EXISTS channels (
    channel_id VARCHAR(20) NOT NULL,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
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
    sync_enabled BOOLEAN DEFAULT true,
    PRIMARY KEY (workspace_id, channel_id)
);

CREATE INDEX idx_channels_workspace ON channels(workspace_id);
CREATE INDEX idx_channels_sync ON channels(workspace_id, sync_enabled, last_sync);
CREATE INDEX idx_channels_archived ON channels(workspace_id, is_archived) WHERE is_archived = false;
CREATE INDEX idx_channels_name ON channels(workspace_id, channel_name);

-- ============================================================================

-- 6. USERS: User profiles
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(20) NOT NULL,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
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
    is_restricted BOOLEAN DEFAULT false,
    timezone VARCHAR(50),
    avatar_url TEXT,
    status_text VARCHAR(255),
    status_emoji VARCHAR(50),
    last_seen TIMESTAMP,
    joined_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX idx_users_workspace ON users(workspace_id);
CREATE INDEX idx_users_name ON users(workspace_id, user_name);
CREATE INDEX idx_users_email ON users(workspace_id, email);
CREATE INDEX idx_users_is_bot ON users(workspace_id, is_bot) WHERE is_bot = false;
CREATE INDEX idx_users_team ON users(workspace_id, team_id);

-- ============================================================================

-- 7. THREAD_PARTICIPANTS: Track conversation participation
CREATE TABLE IF NOT EXISTS thread_participants (
    participant_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_ts VARCHAR(20) NOT NULL,
    channel_id VARCHAR(20) NOT NULL,
    user_id VARCHAR(20) NOT NULL,
    message_count INT DEFAULT 0,
    first_reply_at TIMESTAMP,
    last_reply_at TIMESTAMP,
    UNIQUE(workspace_id, thread_ts, user_id)
);

CREATE INDEX idx_thread_participants_workspace ON thread_participants(workspace_id);
CREATE INDEX idx_thread_participants_thread ON thread_participants(workspace_id, thread_ts);
CREATE INDEX idx_thread_participants_user ON thread_participants(workspace_id, user_id);
CREATE INDEX idx_thread_participants_channel ON thread_participants(workspace_id, channel_id);

-- ============================================================================

-- 8. LINKS: Extracted URLs
CREATE TABLE IF NOT EXISTS links (
    link_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    message_id INT NOT NULL REFERENCES message_metadata(message_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    link_type VARCHAR(50), -- 'github_pr', 'github_issue', 'jira', 'docs', etc.
    domain VARCHAR(255),
    title TEXT,
    description TEXT,
    extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_links_workspace ON links(workspace_id);
CREATE INDEX idx_links_type ON links(workspace_id, link_type);
CREATE INDEX idx_links_message ON links(message_id);
CREATE INDEX idx_links_domain ON links(workspace_id, domain);
CREATE INDEX idx_links_url_hash ON links(workspace_id, MD5(url));

-- ============================================================================

-- 9. FILES: File metadata
CREATE TABLE IF NOT EXISTS files (
    file_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    slack_file_id VARCHAR(50) NOT NULL,
    message_id INT REFERENCES message_metadata(message_id) ON DELETE SET NULL,
    file_name VARCHAR(500),
    file_type VARCHAR(50),
    file_size BIGINT,
    mime_type VARCHAR(100),
    url_private TEXT,
    url_private_download TEXT,
    permalink TEXT,
    local_path TEXT, -- Where stored locally/S3
    content TEXT, -- Extracted text (Phase 2)
    uploaded_by VARCHAR(20),
    uploaded_at TIMESTAMP,
    downloaded_at TIMESTAMP,
    parsed_at TIMESTAMP,
    UNIQUE(workspace_id, slack_file_id)
);

CREATE INDEX idx_files_workspace ON files(workspace_id);
CREATE INDEX idx_files_message ON files(message_id);
CREATE INDEX idx_files_type ON files(workspace_id, file_type);
CREATE INDEX idx_files_uploader ON files(workspace_id, uploaded_by);
CREATE INDEX idx_files_slack_id ON files(workspace_id, slack_file_id);

-- ============================================================================

-- 10. BOOKMARKS: Channel bookmarks
CREATE TABLE IF NOT EXISTS bookmarks (
    bookmark_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    channel_id VARCHAR(20) NOT NULL,
    slack_bookmark_id VARCHAR(50),
    title VARCHAR(500),
    link TEXT,
    emoji VARCHAR(50),
    created_by VARCHAR(20),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    position INT,
    UNIQUE(workspace_id, slack_bookmark_id)
);

CREATE INDEX idx_bookmarks_workspace ON bookmarks(workspace_id);
CREATE INDEX idx_bookmarks_channel ON bookmarks(workspace_id, channel_id);
CREATE INDEX idx_bookmarks_creator ON bookmarks(workspace_id, created_by);

-- ============================================================================

-- 11. TEAMS: Sub-teams (Enterprise Grid)
CREATE TABLE IF NOT EXISTS teams (
    team_id VARCHAR(20) NOT NULL,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    team_name VARCHAR(255) NOT NULL,
    team_domain VARCHAR(255),
    icon_url TEXT,
    created_at TIMESTAMP,
    PRIMARY KEY (workspace_id, team_id)
);

CREATE INDEX idx_teams_workspace ON teams(workspace_id);

-- ============================================================================
-- OPERATIONAL TABLES
-- ============================================================================

-- 12. SYNC_STATUS: Track sync progress per channel
CREATE TABLE IF NOT EXISTS sync_status (
    sync_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    channel_id VARCHAR(20) NOT NULL,
    last_message_ts VARCHAR(20),
    oldest_message_ts VARCHAR(20),
    messages_synced INT DEFAULT 0,
    total_messages INT,
    sync_started_at TIMESTAMP,
    sync_completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed', 'paused'
    error_message TEXT,
    sync_type VARCHAR(20) -- 'backfill', 'incremental', 'realtime'
);

CREATE INDEX idx_sync_status_workspace ON sync_status(workspace_id);
CREATE INDEX idx_sync_status_channel ON sync_status(workspace_id, channel_id);
CREATE INDEX idx_sync_status_status ON sync_status(status);
CREATE UNIQUE INDEX idx_sync_status_active ON sync_status(workspace_id, channel_id, status)
    WHERE status IN ('running', 'pending');

-- ============================================================================

-- 13. PROCESSING_QUEUE: Async job tracking
CREATE TABLE IF NOT EXISTS processing_queue (
    queue_id SERIAL PRIMARY KEY,
    workspace_id VARCHAR(20) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    message_id INT REFERENCES message_metadata(message_id) ON DELETE CASCADE,
    process_type VARCHAR(50) NOT NULL, -- 'embedding', 'summarization', 'file_download', etc.
    priority INT DEFAULT 5, -- 1 (high) to 10 (low)
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    last_error TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_processing_queue_workspace ON processing_queue(workspace_id);
CREATE INDEX idx_processing_queue_status ON processing_queue(status, priority);
CREATE INDEX idx_processing_queue_type ON processing_queue(workspace_id, process_type, status);
CREATE INDEX idx_processing_queue_message ON processing_queue(message_id);

-- ============================================================================

-- 14. BOT_CONFIG: Runtime configuration
CREATE TABLE IF NOT EXISTS bot_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Default configurations
INSERT INTO bot_config (config_key, config_value, description) VALUES
('sync_frequency_minutes', '"5"', 'How often to run incremental sync'),
('backfill_days', '"90"', 'How far back to sync on first run'),
('max_messages_per_batch', '"100"', 'Messages to fetch per API call'),
('excluded_channels', '[]', 'Channel IDs or names to skip'),
('file_download_enabled', '"true"', 'Whether to download file contents'),
('max_file_size_mb', '"50"', 'Maximum file size to download'),
('chromadb_enabled', '"true"', 'Whether to sync to ChromaDB'),
('embedding_model', '"openai"', 'Embedding model to use (openai, sentence-transformers)')
ON CONFLICT (config_key) DO NOTHING;

-- ============================================================================
-- USEFUL VIEWS (Multi-Tenant)
-- ============================================================================

-- Most active threads per workspace
CREATE OR REPLACE VIEW active_threads AS
SELECT
    m.workspace_id,
    m.thread_ts,
    m.channel_id,
    m.channel_name,
    m.user_name as thread_starter_user,
    m.reply_count,
    m.reply_users_count,
    m.created_at as thread_started_at,
    COUNT(tp.user_id) as unique_participants
FROM message_metadata m
LEFT JOIN thread_participants tp ON m.workspace_id = tp.workspace_id AND m.slack_ts = tp.thread_ts
WHERE m.thread_ts IS NULL AND m.reply_count > 0
GROUP BY m.workspace_id, m.thread_ts, m.channel_id, m.channel_name, m.user_name, m.reply_count, m.reply_users_count, m.created_at
ORDER BY m.reply_count DESC;

-- Most reacted messages per workspace
CREATE OR REPLACE VIEW most_reacted_messages AS
SELECT
    m.workspace_id,
    m.message_id,
    m.slack_ts,
    m.channel_name,
    m.user_name,
    m.permalink,
    COUNT(r.reaction_id) as total_reactions,
    COUNT(DISTINCT r.reaction_name) as unique_reaction_types,
    m.created_at
FROM message_metadata m
INNER JOIN reactions r ON m.message_id = r.message_id
GROUP BY m.workspace_id, m.message_id, m.slack_ts, m.channel_name, m.user_name, m.permalink, m.created_at
ORDER BY total_reactions DESC;

-- Channel activity summary per workspace
CREATE OR REPLACE VIEW channel_activity AS
SELECT
    c.workspace_id,
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
LEFT JOIN message_metadata m ON c.workspace_id = m.workspace_id AND c.channel_id = m.channel_id AND m.deleted_at IS NULL
GROUP BY c.workspace_id, c.channel_id, c.channel_name, c.is_private, c.member_count
ORDER BY messages_last_7_days DESC;

-- User activity summary per workspace
CREATE OR REPLACE VIEW user_activity AS
SELECT
    u.workspace_id,
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
LEFT JOIN message_metadata m ON u.workspace_id = m.workspace_id AND u.user_id = m.user_id AND m.deleted_at IS NULL
WHERE u.is_bot = false
GROUP BY u.workspace_id, u.user_id, u.user_name, u.real_name, u.title, u.department
ORDER BY messages_last_7_days DESC;

-- ============================================================================
-- ROW-LEVEL SECURITY (Enable in production)
-- ============================================================================

-- Enable RLS on all multi-tenant tables
-- ALTER TABLE message_metadata ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE reactions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE channels ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- etc.

-- Create policy for workspace isolation
-- CREATE POLICY workspace_isolation ON message_metadata
--     USING (workspace_id = current_setting('app.current_workspace_id')::VARCHAR);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to update thread participant stats
CREATE OR REPLACE FUNCTION update_thread_participants()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.thread_ts IS NOT NULL THEN
        INSERT INTO thread_participants (workspace_id, thread_ts, channel_id, user_id, message_count, first_reply_at, last_reply_at)
        VALUES (NEW.workspace_id, NEW.thread_ts, NEW.channel_id, NEW.user_id, 1, NEW.created_at, NEW.created_at)
        ON CONFLICT (workspace_id, thread_ts, user_id)
        DO UPDATE SET
            message_count = thread_participants.message_count + 1,
            last_reply_at = NEW.created_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update thread participants
CREATE TRIGGER trigger_update_thread_participants
    AFTER INSERT ON message_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_thread_participants();

-- ============================================================================
-- CONSTRAINTS & VALIDATION
-- ============================================================================

-- Ensure timestamps are reasonable
ALTER TABLE message_metadata ADD CONSTRAINT check_created_at_valid
    CHECK (created_at <= NOW() + INTERVAL '1 hour');

ALTER TABLE message_metadata ADD CONSTRAINT check_edited_after_created
    CHECK (edited_at IS NULL OR edited_at >= created_at);

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE workspaces IS 'Multi-tenant workspace tracking';
COMMENT ON TABLE installations IS 'Bot installation per workspace (store tokens encrypted!)';
COMMENT ON TABLE message_metadata IS 'Lightweight message records (content stored in ChromaDB)';
COMMENT ON TABLE reactions IS 'Normalized reaction tracking';
COMMENT ON TABLE channels IS 'Channel metadata per workspace';
COMMENT ON TABLE users IS 'User profiles per workspace';
COMMENT ON TABLE thread_participants IS 'Track conversation participation';
COMMENT ON TABLE links IS 'Extracted URLs for PR/doc discovery';
COMMENT ON TABLE files IS 'File metadata and content storage';
COMMENT ON TABLE bookmarks IS 'Channel bookmarks per workspace';
COMMENT ON TABLE teams IS 'Sub-teams for Enterprise Grid';
COMMENT ON TABLE sync_status IS 'Track data collection progress';
COMMENT ON TABLE processing_queue IS 'Async job processing queue';
COMMENT ON TABLE bot_config IS 'Runtime configuration';

COMMENT ON COLUMN message_metadata.chromadb_id IS 'Reference to document in ChromaDB collection';
COMMENT ON COLUMN message_metadata.has_attachments IS 'Quick check without querying attachments';
COMMENT ON COLUMN message_metadata.mention_count IS 'Number of @mentions in message';
COMMENT ON COLUMN message_metadata.link_count IS 'Number of URLs in message';

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
