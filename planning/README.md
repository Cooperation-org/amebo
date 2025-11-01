# Slack Helper Bot - Data Collection Phase

## Overview
This project implements a comprehensive Slack data collection bot that stores all workspace conversations, files, and metadata for future AI-powered features like Q&A, PR reviews, and knowledge extraction.

## Database Schema

### Core Tables

#### `messages`
Stores all Slack messages with complete metadata and threading support.
```sql
- message_id: Primary key
- slack_ts: Slack's unique timestamp ID
- channel_id/channel_name: Channel information
- user_id/user_name: Message author
- message_text: Actual message content
- message_type: 'regular', 'thread_reply', 'bot_message', 'file_share'
- thread_ts: Parent thread timestamp for replies
- reactions: JSONB of all reactions
- attachments: JSONB of files, links, embeds
- mentions: JSONB of @user and #channel mentions
- raw_data: Complete Slack event JSON
```

#### `channels`
Channel metadata and sync configuration.
```sql
- channel_id: Slack channel ID
- channel_name: Human-readable name
- is_private/is_archived: Channel status
- sync_enabled: Whether to collect from this channel
```

#### `users`
User profiles and metadata.
```sql
- user_id: Slack user ID
- user_name/real_name/display_name: User identifiers
- email/title/department: Profile information
- is_bot/is_admin: User type flags
```

#### `files`
Shared files and extracted content.
```sql
- slack_file_id: Slack's file identifier
- message_id: Associated message
- content: Extracted text from documents
```

#### `sync_status`
Tracks data collection progress per channel.
```sql
- channel_id: Target channel
- last_message_ts: Latest synced message
- status: 'running', 'completed', 'failed'
```

### Performance Indexes
- Channel + time queries: `idx_messages_channel_time`
- Thread lookups: `idx_messages_thread`
- Full-text search: `idx_messages_search` (GIN index)

## Data Collection Bot Implementation

### Phase 1: Setup & Authentication

1. **Create Slack App**
   - Go to https://api.slack.com/apps
   - Create new app with Bot Token Scopes:
     - `channels:history`
     - `channels:read`
     - `groups:history`
     - `groups:read`
     - `users:read`
     - `files:read`

2. **Database Setup**
   ```bash
   # Install PostgreSQL and create database
   createdb slack_helper
   psql slack_helper < schema.sql
   ```

3. **Environment Configuration**
   ```env
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_APP_TOKEN=xapp-your-app-token
   DATABASE_URL=postgresql://user:pass@localhost/slack_helper
   ```

### Phase 2: Historical Data Collection

**Priority Order:**
1. Sync all channels and users
2. Collect recent messages (last 30 days)
3. Backfill historical data
4. Extract file contents

**Implementation Steps:**

1. **Channel Discovery**
   ```python
   # Get all channels user has access to
   channels = slack_client.conversations_list(types="public_channel,private_channel")
   # Store in channels table
   ```

2. **User Sync**
   ```python
   # Get all workspace users
   users = slack_client.users_list()
   # Store in users table with profiles
   ```

3. **Message Collection**
   ```python
   # For each channel, get message history
   history = slack_client.conversations_history(
       channel=channel_id,
       oldest=last_sync_timestamp
   )
   # Store messages with all metadata
   ```

4. **File Processing**
   ```python
   # Extract text from shared documents
   # Store file metadata and content
   ```

### Phase 3: Real-time Collection

**Event Subscription Setup:**
- Subscribe to `message` events
- Handle `message_changed`, `message_deleted`
- Process `file_shared` events

**Real-time Processing:**
```python
@slack_app.event("message")
def handle_message(event):
    # Store new message immediately
    # Add to processing queue for future features
```

### Phase 4: Data Quality & Monitoring

**Sync Monitoring:**
- Track sync progress in `sync_status` table
- Monitor for gaps in message timestamps
- Alert on sync failures

**Data Validation:**
- Verify message threading integrity
- Check for duplicate messages
- Validate user/channel references

## Development Roadmap

### Immediate (Week 1-2)
- [ ] Database schema implementation
- [ ] Slack app setup and authentication
- [ ] Basic message collection script
- [ ] Channel and user sync

### Short-term (Week 3-4)
- [ ] Historical data backfill
- [ ] Real-time event handling
- [ ] File content extraction
- [ ] Sync monitoring dashboard

### Future Features (Built on collected data)
- [ ] Q&A bot using full-text search
- [ ] Thread summarization
- [ ] PR review integration
- [ ] Semantic search with embeddings
- [ ] Knowledge base extraction

## File Structure
```
slack-helper/
├── README.md
├── schema.sql              # Database schema
├── requirements.txt        # Python dependencies
├── config/
│   └── settings.py        # Configuration management
├── src/
│   ├── collectors/        # Data collection modules
│   ├── models/           # Database models
│   └── utils/            # Helper functions
└── scripts/
    ├── setup_db.py       # Database initialization
    ├── sync_historical.py # Backfill script
    └── run_bot.py        # Real-time collection
```

## Getting Started

1. **Clone and setup:**
   ```bash
   git clone <repo>
   cd slack-helper
   pip install -r requirements.txt
   ```

2. **Initialize database:**
   ```bash
   python scripts/setup_db.py
   ```

3. **Configure Slack app and run:**
   ```bash
   export SLACK_BOT_TOKEN=xoxb-...
   python scripts/run_bot.py
   ```

The bot will start collecting all new messages and you can run historical sync separately to backfill existing data.