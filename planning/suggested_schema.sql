-- Slack Helper Bot Database Schema
-- Comprehensive data collection for future AI features

-- Core message storage with all Slack metadata
CREATE TABLE IF NOT EXISTS messages (
    message_id SERIAL PRIMARY KEY,
    slack_ts VARCHAR(20) UNIQUE NOT NULL, -- Slack's timestamp ID
    channel_id VARCHAR(20) NOT NULL,
    channel_name VARCHAR(255),
    user_id VARCHAR(20) NOT NULL,
    user_name VARCHAR(255),
    message_text TEXT,
    message_type VARCHAR(50), -- 'regular', 'thread_reply', 'bot_message', 'file_share'
    thread_ts VARCHAR(20), -- Parent thread timestamp if reply
    reply_count INT DEFAULT 0,
    reply_users_count INT DEFAULT 0,
    reactions JSONB, -- Store all reactions as JSON
    attachments JSONB, -- Files, links, etc.
    mentions JSONB, -- User/channel mentions
    permalink TEXT, -- Slack message permalink
    is_pinned BOOLEAN DEFAULT false,
    edited_at TIMESTAMP,
    deleted_at TIMESTAMP, -- Soft delete
    created_at TIMESTAMP NOT NULL,
    raw_data JSONB -- Store complete Slack event for future needs
);

-- Indexes for common queries
CREATE INDEX idx_messages_channel_time ON messages(channel_id, created_at DESC);
CREATE INDEX idx_messages_thread ON messages(thread_ts) WHERE thread_ts IS NOT NULL;
CREATE INDEX idx_messages_user ON messages(user_id, created_at DESC);
CREATE INDEX idx_messages_search ON messages USING GIN(to_tsvector('english', message_text));
CREATE INDEX idx_messages_slack_ts ON messages(slack_ts);

-- Separate table for channels to track metadata
CREATE TABLE IF NOT EXISTS channels (
    channel_id VARCHAR(20) PRIMARY KEY,
    channel_name VARCHAR(255) NOT NULL,
    is_private BOOLEAN DEFAULT false,
    is_archived BOOLEAN DEFAULT false,
    purpose TEXT,
    topic TEXT,
    member_count INT,
    last_message_ts VARCHAR(20), -- Quick access to latest
    created_at TIMESTAMP,
    last_sync TIMESTAMP,
    sync_enabled BOOLEAN DEFAULT true
);

-- Track users for context
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(20) PRIMARY KEY,
    user_name VARCHAR(255),
    real_name VARCHAR(255),
    display_name VARCHAR(255),
    email VARCHAR(255),
    title VARCHAR(255),
    department VARCHAR(255),
    is_bot BOOLEAN DEFAULT false,
    is_admin BOOLEAN DEFAULT false,
    timezone VARCHAR(50),
    avatar_url TEXT,
    status_text VARCHAR(255),
    status_emoji VARCHAR(50),
    last_seen TIMESTAMP,
    joined_at TIMESTAMP
);

-- Track file uploads and documents shared
CREATE TABLE IF NOT EXISTS files (
    file_id SERIAL PRIMARY KEY,
    slack_file_id VARCHAR(50) UNIQUE,
    message_id INT REFERENCES messages(message_id),
    file_name VARCHAR(500),
    file_type VARCHAR(50),
    file_size BIGINT,
    url_private TEXT,
    permalink TEXT,
    content TEXT, -- Extracted text from docs/PDFs
    uploaded_by VARCHAR(20),
    uploaded_at TIMESTAMP
);

-- For maintaining sync state
CREATE TABLE IF NOT EXISTS sync_status (
    sync_id SERIAL PRIMARY KEY,
    channel_id VARCHAR(20) REFERENCES channels(channel_id),
    last_message_ts VARCHAR(20),
    messages_synced INT DEFAULT 0,
    total_messages INT, -- Progress tracking
    sync_started_at TIMESTAMP,
    sync_completed_at TIMESTAMP,
    status VARCHAR(20), -- 'running', 'completed', 'failed'
    error_message TEXT
);

-- For future: pre-computed embeddings
CREATE TABLE IF NOT EXISTS message_embeddings (
    embedding_id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(message_id),
    embedding_vector VECTOR(1536), -- When you add semantic search
    embedding_model VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- For tracking what needs processing
CREATE TABLE IF NOT EXISTS processing_queue (
    queue_id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(message_id),
    process_type VARCHAR(50), -- 'embedding', 'summarization', 'indexing'
    priority INT DEFAULT 5,
    status VARCHAR(20) DEFAULT 'pending',
    attempts INT DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX idx_sync_status_channel ON sync_status(channel_id);
CREATE INDEX idx_processing_queue_status ON processing_queue(status, priority);
CREATE INDEX idx_files_message ON files(message_id);
CREATE INDEX idx_users_name ON users(user_name);
CREATE INDEX idx_channels_sync ON channels(sync_enabled, last_sync);