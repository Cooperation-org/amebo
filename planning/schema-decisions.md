# Database Schema - Data Collection Phase

## Design Principles

1. **Slack-native**: Use Slack's IDs and timestamps for reliable syncing
2. **Comprehensive**: Capture everything now, use selectively later
3. **Flexible**: JSONB for evolving Slack data structures
4. **Query-optimized**: Indexes for common access patterns
5. **AI-ready**: Structure supports future embedding and semantic search

---

## Core Tables

### 1. messages
**Purpose:** Central storage for all Slack messages with full metadata

**Key Design Decisions:**
- `slack_ts` as unique identifier (Slack's timestamp-based ID)
- JSONB fields for flexibility (reactions, attachments, mentions, blocks)
- `raw_data` JSONB stores complete Slack event for future needs
- Soft deletes (`deleted_at`) to preserve conversation context
- Thread support via `thread_ts` and reply counts

**Indexes:**
- Time-based queries per channel (most common)
- Thread lookups
- User activity tracking
- Full-text search on message content
- Fast lookups by Slack timestamp

```sql
CREATE TABLE IF NOT EXISTS messages (
    message_id SERIAL PRIMARY KEY,
    slack_ts VARCHAR(20) UNIQUE NOT NULL,
    channel_id VARCHAR(20) NOT NULL,
    channel_name VARCHAR(255),
    user_id VARCHAR(20) NOT NULL,
    user_name VARCHAR(255),
    message_text TEXT,
    message_type VARCHAR(50), -- 'regular', 'thread_reply', 'bot_message', 'file_share'
    thread_ts VARCHAR(20), -- Parent thread timestamp if reply
    reply_count INT DEFAULT 0,
    reply_users_count INT DEFAULT 0,
    reactions JSONB, -- Store all reactions as JSON [{name: "thumbsup", count: 5, users: [...]}]
    attachments JSONB, -- Files, images, link previews
    mentions JSONB, -- User/channel mentions [@user1, @channel]
    blocks JSONB, -- Slack's structured message blocks
    permalink TEXT, -- Direct link to message
    is_pinned BOOLEAN DEFAULT false,
    edited_at TIMESTAMP,
    deleted_at TIMESTAMP, -- Soft delete (keep for context)
    created_at TIMESTAMP NOT NULL,
    raw_data JSONB -- Complete Slack event payload
);

CREATE INDEX idx_messages_channel_time ON messages(channel_id, created_at DESC);
CREATE INDEX idx_messages_thread ON messages(thread_ts) WHERE thread_ts IS NOT NULL;
CREATE INDEX idx_messages_user ON messages(user_id, created_at DESC);
CREATE INDEX idx_messages_search ON messages USING GIN(to_tsvector('english', message_text));
CREATE INDEX idx_messages_slack_ts ON messages(slack_ts);
CREATE INDEX idx_messages_deleted ON messages(deleted_at) WHERE deleted_at IS NOT NULL;
```

---

### 2. channels
**Purpose:** Track channel metadata and sync configuration

**Key Design Decisions:**
- Separate table (not embedded in messages) for easier updates
- `sync_enabled` flag to control which channels to monitor
- `last_message_ts` for quick "what's new" checks
- Track archive status to skip dead channels

```sql
CREATE TABLE IF NOT EXISTS channels (
    channel_id VARCHAR(20) PRIMARY KEY,
    channel_name VARCHAR(255) NOT NULL,
    is_private BOOLEAN DEFAULT false,
    is_archived BOOLEAN DEFAULT false,
    purpose TEXT,
    topic TEXT,
    member_count INT,
    last_message_ts VARCHAR(20),
    created_at TIMESTAMP,
    last_sync TIMESTAMP, -- When we last synced this channel
    sync_enabled BOOLEAN DEFAULT true -- Allow disabling specific channels
);

CREATE INDEX idx_channels_sync ON channels(sync_enabled, last_sync);
CREATE INDEX idx_channels_archived ON channels(is_archived) WHERE is_archived = false;
```

---

### 3. users
**Purpose:** Store user context for better AI responses

**Key Design Decisions:**
- Capture role info (title, department) for context
- Track bot vs human for filtering
- Status and activity for "who's available" queries
- Separate table allows updates without touching messages

```sql
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
    joined_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_users_name ON users(user_name);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_is_bot ON users(is_bot) WHERE is_bot = false;
```

---

### 4. links
**Purpose:** Extract and categorize URLs for quick access to PRs, docs, issues

**Key Design Decisions:**
- Separate table for easier querying ("show me all PRs from last week")
- `link_type` classification for filtering
- Domain tracking for analytics

```sql
CREATE TABLE IF NOT EXISTS links (
    link_id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(message_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    link_type VARCHAR(50), -- 'github_pr', 'github_issue', 'jira', 'docs', 'confluence', 'other'
    domain VARCHAR(255),
    title TEXT, -- Extracted from preview if available
    extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_links_type ON links(link_type);
CREATE INDEX idx_links_message ON links(message_id);
CREATE INDEX idx_links_domain ON links(domain);
```

**Link Type Detection Logic:**
- `github.com/.../pull/` → `github_pr`
- `github.com/.../issues/` → `github_issue`
- `*.atlassian.net/browse/` → `jira`
- `notion.so/` → `notion`
- Others → `other`

---

### 5. files
**Purpose:** Track file uploads and shared documents

**Key Design Decisions:**
- Store metadata immediately, defer content extraction to Phase 2
- Link to message for context
- `content` field prepared for future PDF/doc text extraction

```sql
CREATE TABLE IF NOT EXISTS files (
    file_id SERIAL PRIMARY KEY,
    slack_file_id VARCHAR(50) UNIQUE,
    message_id INT REFERENCES messages(message_id) ON DELETE SET NULL,
    file_name VARCHAR(500),
    file_type VARCHAR(50), -- pdf, docx, png, etc.
    file_size BIGINT,
    mime_type VARCHAR(100),
    url_private TEXT, -- Slack's private download URL
    permalink TEXT, -- Slack file permalink
    content TEXT, -- Extracted text (Phase 2: OCR, PDF parsing)
    uploaded_by VARCHAR(20) REFERENCES users(user_id),
    uploaded_at TIMESTAMP
);

CREATE INDEX idx_files_message ON files(message_id);
CREATE INDEX idx_files_type ON files(file_type);
CREATE INDEX idx_files_uploader ON files(uploaded_by);
```

---

## Operational Tables

### 6. sync_status
**Purpose:** Track sync progress and enable resumption

**Key Design Decisions:**
- Per-channel tracking for parallel processing
- Progress metrics for monitoring
- Status field for failure detection
- Stores last synced timestamp for incremental updates

```sql
CREATE TABLE IF NOT EXISTS sync_status (
    sync_id SERIAL PRIMARY KEY,
    channel_id VARCHAR(20) REFERENCES channels(channel_id),
    last_message_ts VARCHAR(20), -- Resume from here
    oldest_message_ts VARCHAR(20), -- How far back we've gone
    messages_synced INT DEFAULT 0,
    total_messages INT, -- Estimated total (from Slack API)
    sync_started_at TIMESTAMP,
    sync_completed_at TIMESTAMP,
    status VARCHAR(20), -- 'pending', 'running', 'completed', 'failed', 'paused'
    error_message TEXT,
    sync_type VARCHAR(20) -- 'backfill', 'incremental', 'realtime'
);

CREATE INDEX idx_sync_status_channel ON sync_status(channel_id);
CREATE INDEX idx_sync_status_status ON sync_status(status);
CREATE UNIQUE INDEX idx_sync_status_active ON sync_status(channel_id, status)
    WHERE status IN ('running', 'pending');
```

---

### 7. processing_queue
**Purpose:** Track async work (embeddings, summarization in Phase 2)

**Key Design Decisions:**
- Generic queue for multiple job types
- Priority support for important messages
- Retry tracking with error logging
- Can be used in Phase 1 for link extraction or user info fetch

```sql
CREATE TABLE IF NOT EXISTS processing_queue (
    queue_id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(message_id) ON DELETE CASCADE,
    process_type VARCHAR(50), -- 'embedding', 'summarization', 'link_extraction', 'user_info'
    priority INT DEFAULT 5, -- 1 (high) to 10 (low)
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_processing_queue_status ON processing_queue(status, priority);
CREATE INDEX idx_processing_queue_type ON processing_queue(process_type, status);
```

---

### 8. bot_config
**Purpose:** Runtime configuration without code changes

**Key Design Decisions:**
- Key-value store with JSONB for complex config
- Can update sync frequency, channel filters, etc. without redeployment

```sql
CREATE TABLE IF NOT EXISTS bot_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value JSONB,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Example configurations:
-- INSERT INTO bot_config VALUES
-- ('sync_frequency_minutes', '5', 'How often to run incremental sync'),
-- ('excluded_channels', '["random", "water-cooler"]', 'Channels to skip'),
-- ('backfill_days', '90', 'How far back to sync on first run');
```

---

## Phase 2 Preparation (Not Implemented Yet)

### 9. message_embeddings
**Purpose:** Vector embeddings for semantic search

**Note:** Requires `pgvector` extension

```sql
-- Install pgvector extension first: CREATE EXTENSION vector;

CREATE TABLE IF NOT EXISTS message_embeddings (
    embedding_id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(message_id) ON DELETE CASCADE,
    embedding_vector VECTOR(1536), -- OpenAI ada-002: 1536 dims
    embedding_model VARCHAR(50), -- 'text-embedding-ada-002', 'all-MiniLM-L6-v2', etc.
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_embeddings_message ON message_embeddings(message_id);
-- Add vector similarity index when implementing:
-- CREATE INDEX idx_embeddings_vector ON message_embeddings
--   USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100);
```

---

## Data Collection Strategy

### Backfill Process
1. Fetch all channels bot is member of → populate `channels` table
2. For each channel:
   - Check `sync_status` for existing progress
   - Fetch messages in batches (100-200 at a time)
   - Process each message:
     - Insert into `messages`
     - Extract links → insert into `links`
     - If thread parent, fetch replies
     - Cache user info → upsert into `users`
   - Update `sync_status` after each batch
3. Handle rate limits (Slack: ~1 req/sec for most endpoints)

### Real-Time Event Collection
1. Subscribe to Slack Events API (Socket Mode or Webhooks)
2. Listen for:
   - `message` → insert new message
   - `message.channels` / `message.groups` → channel messages
   - `message_changed` → update message, set `edited_at`
   - `message_deleted` → soft delete, set `deleted_at`
   - `reaction_added` / `reaction_removed` → update `reactions` JSONB
   - `channel_created` / `channel_rename` → update `channels`
   - `user_change` → update `users`

### Incremental Sync (Fallback)
- Every N minutes, query `channels.last_message_ts`
- Fetch new messages since that timestamp
- Catch anything Events API missed

---

## Schema Validation & Constraints

### Foreign Key Relationships
```
messages.message_id ← links.message_id (CASCADE on delete)
messages.message_id ← files.message_id (SET NULL on delete)
messages.message_id ← processing_queue.message_id (CASCADE on delete)
channels.channel_id ← sync_status.channel_id
users.user_id ← files.uploaded_by
```

### Data Integrity Checks
- `slack_ts` must be unique (prevents duplicates)
- `thread_ts` should reference another `slack_ts` (add CHECK constraint?)
- Timestamps should be in past (created_at <= NOW())

---

## Storage Estimates

**Assumptions:**
- 100 active users
- 50 channels
- 500 messages/day average
- 90-day retention for initial backfill

**Estimated Initial Size:**
- Messages: ~45,000 rows × ~2KB = ~90 MB
- Links: ~5,000 rows × 500 bytes = ~2.5 MB
- Users: ~100 rows × 1KB = ~100 KB
- Channels: ~50 rows × 1KB = ~50 KB

**Growth Rate:** ~1 MB/day (messages + metadata)

**With Embeddings (Phase 2):**
- Add ~6 KB per message × 45,000 = ~270 MB
- Total: ~400 MB for 90 days

**Recommendation:** Start with 10 GB database, monitor growth

---

## Open Questions & Decisions Needed

### 1. Message Retention Policy
- **Option A:** Keep everything forever (until disk full)
- **Option B:** Archive messages older than X days to separate table
- **Option C:** Delete low-value messages (e.g., "👍" only, no replies)

**Recommendation:** Keep everything for Phase 1, revisit in Phase 2

### 2. Reaction Storage Format
- **Decision:** Separate `reactions` table (normalized)
- Allows querying reaction trends, most-reacted messages
- Better for analytics and engagement tracking

**Status:** ✅ APPROVED - Normalized table

### 3. Blocks Field
- **Decision:** Keep `blocks` JSONB field
- Essential for preserving Slack's rich formatting, interactive elements
- Needed for proper message context

**Status:** ✅ APPROVED - Included in schema

### 4. File Storage Strategy
- **Decision:** Store file metadata + download files locally/S3
- Parse content asynchronously (Phase 2)
- Allows offline access and better control

**Status:** ✅ APPROVED - Hybrid approach

### 5. Additional Tables
- **Bookmarks/Saved Messages:** Track user-saved messages
- **Workspace/Team Info:** Organization metadata
- **Thread Participants:** Track who contributed to discussions

**Status:** ✅ APPROVED - All included

### 6. Thread Depth Limits
- Slack threads can be very deep (100+ replies)
- **Current:** Fetch all replies during backfill
- **Alternative:** Limit depth, fetch on-demand

**Recommendation:** Fetch all (threads are important context)

### 7. Bot Message Filtering
- Include bot messages in collection?
- **Yes:** Bots provide context (CI results, alerts)
- **No:** Reduce noise

**Recommendation:** Collect all, filter in queries using `users.is_bot`

---

## Next Steps

1. ✅ Review and finalize this schema
2. Create `schema.sql` with final DDL
3. Set up PostgreSQL database
4. Test schema with sample data
5. Build data access layer (repositories)
