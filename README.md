# Slack Helper Bot

A comprehensive data collection and AI-powered assistant for Slack workspaces.

## Overview

Slack Helper Bot collects and indexes all Slack messages, enabling powerful search, Q&A, and insights across your workspace's knowledge base.

### Current Status: Phase 1 - Data Collection ✅

## Features

### Phase 1 (Current) ✅
- **Historical Message Sync** - Backfill all messages from channels
- **Real-time Collection** - Live event streaming (coming soon)
- **Rich Metadata** - Captures threads, reactions, links, files, users
- **Resumable Sync** - Can pause and resume large backfills
- **Progress Tracking** - Monitor sync status per channel

### Phase 2 (Planned)
- AI-powered Q&A on workspace knowledge
- Semantic search with embeddings
- Thread summarization
- PR review automation
- Newsletter generation

## Quick Start

### 1. Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Slack workspace with bot permissions

### 2. Installation

```bash
# Clone repo
git clone <your-repo>
cd slack-helper-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up database
psql -U postgres -c "CREATE DATABASE slack_helper;"
psql -d slack_helper -f src/db/schema.sql
```

### 3. Configuration

Copy `.env.example` to `.env` and fill in your Slack credentials:

```bash
cp .env.example .env
```

Required environment variables:
- `SLACK_BOT_TOKEN` - Bot User OAuth Token (xoxb-...)
- `SLACK_APP_TOKEN` - App-Level Token for Socket Mode (xapp-...)
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` - Database config

### 4. Slack App Setup

1. Create a Slack app at https://api.slack.com/apps
2. Add OAuth scopes:
   - `channels:history`, `channels:read`
   - `groups:history`, `groups:read`
   - `users:read`, `users:read.email`
   - `files:read`, `reactions:read`, `bookmarks:read`
3. Enable Socket Mode and create app token
4. Install app to workspace
5. Add bot to channels you want to sync

## Usage

### Backfill Historical Messages

Sync all channels:
```bash
python scripts/backfill.py --all
```

Sync specific channels:
```bash
python scripts/backfill.py --channels C123456,C789012
```

Only sync recent history:
```bash
python scripts/backfill.py --all --days 30
```

Dry run (test without writing to DB):
```bash
python scripts/backfill.py --all --dry-run
```

### Monitor Progress

Check sync status:
```bash
psql -d slack_helper -c "SELECT * FROM sync_status ORDER BY sync_started_at DESC;"
```

View collected data:
```bash
psql -d slack_helper -c "
SELECT
    channel_name,
    COUNT(*) as messages,
    MAX(created_at) as latest_message
FROM messages
GROUP BY channel_name;
"
```

## Project Structure for message collection bot

```
slack-helper-bot/
├── src/
│   ├── collector/
│   │   ├── slack_client.py          # Slack API wrapper
│   │   ├── event_handler.py         # Real-time events (TODO)
│   │   └── processors/
│   │       └── message_processor.py # Parse messages
│   ├── db/
│   │   ├── schema.sql               # Database schema
│   │   ├── connection.py            # DB connection pool
│   │   └── repositories/            # Data access layer
│   │       ├── message_repo.py
│   │       ├── channel_repo.py
│   │       ├── user_repo.py
│   │       └── sync_repo.py
├── scripts/
│   └── backfill.py                  # Historical sync script
├── planning/                         # Design docs
├── .env                              # Configuration (not in git)
└── requirements.txt
```

## Database Schema

### Core Tables
- **messages** - All Slack messages with full metadata
- **reactions** - Normalized reaction tracking
- **channels** - Channel metadata
- **users** - User profiles
- **thread_participants** - Conversation tracking
- **links** - Extracted URLs (PRs, docs, etc.)
- **files** - File metadata
- **bookmarks** - Channel bookmarks
- **workspace** - Organization info

### Operational Tables
- **sync_status** - Track backfill progress
- **processing_queue** - Async job queue
- **bot_config** - Runtime configuration

See [src/db/schema.sql](src/db/schema.sql) for complete schema.

## Development

### Test Slack Connection
```bash
python src/collector/slack_client.py
```

### Test Database Connection
```bash
python src/db/connection.py
```

### Run Tests
```bash
pytest tests/
```

## Roadmap

- [x] Database schema design
- [x] Slack API client wrapper
- [x] Historical message backfill
- [x] Thread sync
- [x] Reaction tracking
- [x] Link extraction
- [ ] Real-time event listener
- [ ] Incremental sync
- [ ] File content extraction
- [ ] Message embeddings
- [ ] Semantic search
- [ ] Q&A bot interface

## Architecture

### Single Workspace (Current)
- One deployment per workspace
- Simple, fast development
- Perfect for team use

### Multi-Tenant (Future)
- Support multiple workspaces
- Slack Marketplace ready
- Row-level security

See [planning/implementation-plan.md](planning/implementation-plan.md) for details.

## Contributing

This is currently a personal/team project. Contributions welcome after Phase 1 is complete!

## License

[Your License Here]

## Support

For issues or questions, check the [planning docs](planning/) or open an issue.
