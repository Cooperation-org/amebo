# Getting Started with Slack Helper Bot

## Overview

Slack Helper Bot is a hybrid PostgreSQL + ChromaDB system for collecting, indexing, and querying Slack workspace knowledge.

**Current Status:** Phase 1 Complete - Data collection and query layer working!

---

## What's Been Built

### ✅ Hybrid Architecture
- **PostgreSQL**: Structured metadata (users, channels, reactions, links)
- **ChromaDB**: Message content + semantic search

### ✅ Data Collection
- **722 messages** synced across 4 channels
- **330 reactions** captured
- **26 users** cached
- **277 links** extracted
- **90-day backfill** working

### ✅ Query Layer
- Most reacted messages
- Semantic search
- Channel activity summaries
- Topic discovery
- Expert finding
- PR discussion tracking

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Slack workspace with bot installed

### 2. Installation

```bash
# Clone and enter directory
cd slack-helper-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up database
psql -U postgres -c "CREATE DATABASE slack_helper;"
psql -d slack_helper -f src/db/schema.sql

# Configure environment
cp .env.example .env
# Edit .env with your Slack tokens
```

### 3. Create Default Workspace

```bash
psql -d slack_helper -c "
INSERT INTO workspaces (workspace_id, team_name, team_domain, is_active)
VALUES ('W_DEFAULT', 'YourTeamName', 'yourteam', true);"
```

### 4. Add Bot to Slack Channels

In Slack, invite the bot to channels:
```
/invite @slack_helper_bot
```

### 5. Run Backfill

```bash
# Sync all channels (last 90 days)
python scripts/backfill_chromadb.py --all --workspace W_DEFAULT --days 90

# Or sync specific channels
python scripts/backfill_chromadb.py --channels C123456,C789012 --workspace W_DEFAULT
```

---

## Usage Examples

### Query Service

```python
from src.services.query_service import QueryService

service = QueryService(workspace_id='W_DEFAULT')

# Most reacted messages
top_messages = service.get_most_reacted_messages(days_back=7, limit=10)
for msg in top_messages:
    print(f"{msg['text'][:50]} - {msg['reaction_count']} reactions")

# Semantic search
results = service.semantic_search('deployment issues', n_results=10)
for result in results:
    print(result['text'])

# Channel activity
activity = service.get_channel_activity_summary(days_back=30)
for channel in activity:
    print(f"#{channel['channel_name']}: {channel['message_count']} messages")

# Find discussions about a PR
pr_discussions = service.get_pr_discussions('https://github.com/org/repo/pull/123')
print(f"Found {pr_discussions['mention_count']} mentions")

# Find experts on a topic
experts = service.find_expert_on_topic('kubernetes deployment', n_results=5)
for expert in experts:
    print(f"{expert['user_name']}: {expert['message_count']} messages")
```

### Direct Database Queries

```sql
-- Most active channels
SELECT channel_name, COUNT(*) as messages
FROM message_metadata
WHERE workspace_id = 'W_DEFAULT'
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY channel_name
ORDER BY messages DESC;

-- Most engaged users
SELECT u.user_name, COUNT(r.reaction_id) as reactions_received
FROM users u
JOIN message_metadata m ON u.user_id = m.user_id
JOIN reactions r ON m.message_id = r.message_id
WHERE u.workspace_id = 'W_DEFAULT'
GROUP BY u.user_name
ORDER BY reactions_received DESC
LIMIT 10;

-- Messages with GitHub links
SELECT m.channel_name, COUNT(*) as pr_count
FROM message_metadata m
JOIN links l ON m.message_id = l.message_id
WHERE m.workspace_id = 'W_DEFAULT'
  AND l.link_type = 'github_pr'
GROUP BY m.channel_name;
```

### Direct ChromaDB Queries

```python
from src.db.chromadb_client import ChromaDBClient

client = ChromaDBClient()

# Semantic search
results = client.search_messages(
    workspace_id='W_DEFAULT',
    query_text='how to deploy to production',
    n_results=10,
    where_filter={'channel_name': 'engineering'}
)

# Get specific message
message = client.get_message('W_DEFAULT', '1234567890.123456')
print(message['text'])

# Collection stats
stats = client.get_collection_stats('W_DEFAULT')
print(f"Total messages: {stats['message_count']}")
```

---

## Project Structure

```
slack-helper-bot/
├── src/
│   ├── db/
│   │   ├── schema.sql               # PostgreSQL schema
│   │   ├── connection.py            # DB connection pool
│   │   ├── chromadb_client.py       # ChromaDB wrapper
│   │   └── repositories/
│   │       └── message_repo.py      # Message metadata repo
│   ├── collector/
│   │   ├── slack_client.py          # Slack API wrapper
│   │   └── processors/
│   │       └── message_processor.py # Message parsing
│   └── services/
│       └── query_service.py         # High-level queries
├── scripts/
│   └── backfill_chromadb.py         # Data collection script
├── planning/
│   ├── architecture-chromadb.md     # Architecture docs
│   ├── refactor-complete.md         # Refactor summary
│   └── phase1-todo.md               # Implementation plan
├── chromadb_data/                   # ChromaDB storage (local)
├── .env                              # Configuration
└── requirements.txt
```

---

## Current Data

**As of last sync:**
- 722 total messages
- 330 reactions
- 26 users
- 4 channels (#standup, #general, #hackathons, #expression)
- 277 links extracted

**Channel breakdown:**
- #standup: 411 messages (most active)
- #general: 233 messages
- #hackathons: 40 messages
- #expression: 38 messages

---

## Next Steps

### Immediate Enhancements
1. Build newsletter generation feature
2. Add PR review automation
3. Create Q&A bot interface
4. Set up real-time event listener

### Phase 2: Real-Time Collection
- Event listener for new messages
- Incremental sync
- Live updates

### Phase 3: AI Features
- Newsletter generation (semantic topic extraction)
- PR review (find related discussions)
- Q&A bot (RAG with ChromaDB)
- Thread summarization

### Phase 4: Multi-Tenant
- Add more workspaces
- Implement installation flow
- Per-workspace billing
- Admin dashboard

---

## API Examples (Future)

### Newsletter Generation

```python
from src.services.newsletter_service import NewsletterService

newsletter = NewsletterService(workspace_id='W_DEFAULT')

# Generate weekly newsletter
content = newsletter.generate_weekly(
    topics=['engineering', 'product', 'announcements'],
    max_items_per_topic=5
)

print(content)
```

### PR Review

```python
from src.services.pr_review_service import PRReviewService

pr_service = PRReviewService(workspace_id='W_DEFAULT')

# Analyze PR discussions
analysis = pr_service.analyze_pr('https://github.com/org/repo/pull/123')

print(f"Sentiment: {analysis['sentiment']}")
print(f"Key feedback: {analysis['key_points']}")
print(f"Similar past PRs: {analysis['similar_prs']}")
```

### Q&A Bot

```python
from src.services.qa_service import QAService

qa = QAService(workspace_id='W_DEFAULT')

# Answer question based on Slack history
answer = qa.answer_question(
    question="How do we deploy to production?",
    context_messages=10
)

print(answer['answer'])
print(f"Sources: {answer['source_messages']}")
```

---

## Configuration

### Environment Variables

```bash
# Slack API
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=slack_helper
DB_USER=user
DB_PASSWORD=

# ChromaDB
CHROMADB_PATH=./chromadb_data

# Bot Settings
BACKFILL_DAYS=90
SYNC_FREQUENCY_MINUTES=5
MAX_MESSAGES_PER_BATCH=100
```

### Bot Permissions (Slack App)

Required OAuth scopes:
- `channels:history`, `channels:read`
- `groups:history`, `groups:read`
- `users:read`, `users:read.email`
- `files:read`, `reactions:read`
- `bookmarks:read`, `team:read`

---

## Troubleshooting

### Bot can't read messages
- Ensure bot is invited to channels: `/invite @slack_helper_bot`
- Check OAuth scopes in Slack app settings
- Verify `SLACK_BOT_TOKEN` is correct

### Database connection errors
- Verify PostgreSQL is running
- Check `DB_*` environment variables
- Ensure database `slack_helper` exists

### ChromaDB errors
- Check `CHROMADB_PATH` directory exists
- Ensure sufficient disk space
- Try deleting `chromadb_data/` and re-syncing

### No search results
- Run backfill script to collect data
- Verify messages in database: `SELECT COUNT(*) FROM message_metadata;`
- Check ChromaDB: `python -c "from src.db.chromadb_client import ChromaDBClient; print(ChromaDBClient().get_collection_stats('W_DEFAULT'))"`

---

## Performance

### Current (722 messages)
- Backfill: ~2 minutes
- PostgreSQL queries: <50ms
- ChromaDB search: <200ms
- Hybrid queries: <300ms

### Expected (10K messages)
- Backfill: ~15 minutes
- PostgreSQL: <100ms
- ChromaDB: <300ms
- Hybrid: <500ms

---

## Contributing

This is currently a personal/team project. Phase 1 is complete! Next phases coming soon.

---

## License

[Your License]

---

## Support

For questions or issues:
- Check [planning/](planning/) docs
- Review [architecture-chromadb.md](planning/architecture-chromadb.md)
- See examples in [query_service.py](src/services/query_service.py)
