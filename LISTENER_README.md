# Slack Real-Time Listener

Real-time message collection service using Slack Socket Mode. Automatically collects messages, reactions, and user updates from all connected workspaces.

## Features

✅ **Multi-Workspace Support** - Listens to all connected workspaces simultaneously
✅ **Real-Time Collection** - Instant message collection via WebSocket
✅ **Dual Storage** - Metadata in PostgreSQL, content in ChromaDB
✅ **Event Handling** - Messages, reactions, user changes, channels
✅ **Error Recovery** - Graceful error handling and logging
✅ **No Webhooks Required** - Uses Socket Mode (no public URL needed)

## How It Works

```
Slack Workspace 1 ─┐
Slack Workspace 2 ─┼─> Socket Mode ─> Listener ─┬─> PostgreSQL (metadata)
Slack Workspace 3 ─┘                             └─> ChromaDB (content)
```

**Events Collected:**
- 📩 `message` - New messages in channels/DMs
- 👍 `reaction_added` - Reactions added to messages
- 👎 `reaction_removed` - Reactions removed
- 👤 `user_change` - User profile updates
- 📢 `channel_created` - New channel creation

## Setup

### 1. Configure Slack App for Socket Mode

Go to https://api.slack.com/apps → Your App:

1. **Socket Mode** → Enable Socket Mode
   - Generate App-Level Token with `connections:write` scope
   - Copy token (starts with `xapp-`)

2. **Event Subscriptions** → Enable Events
   - Subscribe to bot events:
     - `message.channels`
     - `message.groups`
     - `message.im`
     - `message.mpim`
     - `reaction_added`
     - `reaction_removed`
     - `user_change`
     - `channel_created`

3. **Update .env:**
   ```bash
   SLACK_APP_TOKEN=xapp-1-your-app-token-here
   ```

### 2. Store App Token in Database

When a workspace is installed via OAuth, you need to store the app token:

```python
# In OAuth callback (already handled in slack_oauth.py)
cur.execute(
    """
    INSERT INTO installations (workspace_id, bot_token, app_token, ...)
    VALUES (%s, %s, %s, ...)
    """,
    (workspace_id, bot_token, app_token)
)
```

**Note:** The app token is the same for all workspaces (it's app-level, not workspace-specific).

### 3. Run the Listener

```bash
# Start listener (runs indefinitely)
python scripts/start_listener.py
```

**For production, use a process manager:**

```bash
# Using systemd
sudo systemctl start slack-listener

# Using supervisor
supervisorctl start slack-listener

# Using PM2
pm2 start scripts/start_listener.py --name slack-listener --interpreter python3
```

## Architecture

### Message Flow

```
1. Message posted in Slack
   ↓
2. Slack sends event via WebSocket (Socket Mode)
   ↓
3. Listener receives event
   ↓
4. Extract message data (text, user, channel, timestamp)
   ↓
5. Dual-write:
   ├─> PostgreSQL: message_metadata (metadata only)
   └─> ChromaDB: message content + embeddings
   ↓
6. Link records via chromadb_id
```

### Database Storage

**PostgreSQL (message_metadata):**
- `workspace_id`, `slack_ts`, `channel_id`
- `user_id`, `user_name`, `channel_name`
- `message_type`, `thread_ts`, `permalink`
- `link_count`, `mention_count`, `has_reactions`
- `chromadb_id` ← Links to ChromaDB

**ChromaDB:**
- Full message text
- Vector embeddings (auto-generated)
- Metadata for filtering (channel, user, timestamp)

### Handled Events

#### 1. Messages
```python
{
  "type": "message",
  "channel": "C1234567890",
  "user": "U1234567890",
  "text": "Hello world!",
  "ts": "1234567890.123456",
  "thread_ts": "1234567890.123456"  # If reply
}
```

Stored as:
- PostgreSQL: Message metadata
- ChromaDB: Message text + embeddings

#### 2. Reactions
```python
{
  "type": "reaction_added",
  "user": "U1234567890",
  "reaction": "thumbsup",
  "item": {
    "type": "message",
    "channel": "C1234567890",
    "ts": "1234567890.123456"
  }
}
```

Stored in PostgreSQL `reactions` table

#### 3. User Changes
```python
{
  "type": "user_change",
  "user": {
    "id": "U1234567890",
    "name": "john",
    "real_name": "John Doe",
    "profile": {...}
  }
}
```

Updates PostgreSQL `users` table

## Monitoring

### Check Listener Status

```bash
# View logs
tail -f logs/slack-listener.log

# Check if running
ps aux | grep start_listener
```

### Verify Data Collection

```bash
# Check recent messages
psql $DATABASE_URL -c "
SELECT channel_name, user_name, LEFT(chromadb_id, 20) as chromadb_ref, created_at
FROM message_metadata
WHERE workspace_id = 'YOUR_WORKSPACE_ID'
ORDER BY created_at DESC
LIMIT 10;
"

# Check ChromaDB
python -c "
from src.db.chromadb_client import ChromaDBClient
client = ChromaDBClient()
collection = client.get_or_create_collection('W_DEFAULT')
print(f'Total messages: {collection.count()}')
"
```

### Common Issues

**Issue: "No active workspace installations found"**
- **Solution:** Install workspace via OAuth first (`/api/slack/install`)
- Ensure `app_token` is stored in `installations` table

**Issue: "Connection refused"**
- **Solution:** Check that Socket Mode is enabled in Slack app settings
- Verify `SLACK_APP_TOKEN` is correct

**Issue: "Messages not being stored"**
- **Solution:** Check PostgreSQL and ChromaDB connections
- Review logs for errors: `tail -f logs/slack-listener.log`

## Socket Mode vs Webhooks

| Feature | Socket Mode (Current) | Webhooks (Events API) |
|---------|----------------------|----------------------|
| Public URL | ❌ Not required | ✅ Required |
| Real-time | ✅ WebSocket | ✅ HTTP POST |
| Setup | Easier (no ngrok for dev) | Harder (need public endpoint) |
| Scalability | Good (up to ~100 workspaces) | Better (unlimited) |
| Latency | Very low | Low |
| Deployment | Runs as service | Handled by web server |

**Recommendation:** Socket Mode is perfect for MVP and small-medium deployments. Switch to webhooks when scaling to 100+ workspaces.

## Systemd Service (Production)

Create `/etc/systemd/system/slack-listener.service`:

```ini
[Unit]
Description=Slack Helper Bot Listener
After=network.target postgresql.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/slack-helper
Environment="PATH=/path/to/slack-helper/venv/bin"
ExecStart=/path/to/slack-helper/venv/bin/python scripts/start_listener.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable slack-listener
sudo systemctl start slack-listener
sudo systemctl status slack-listener
```

## Integration with FastAPI

The listener runs independently from the FastAPI server:

```
┌─────────────────┐         ┌──────────────────┐
│  FastAPI Server │         │ Socket Listener  │
│  (port 8000)    │         │  (background)    │
│                 │         │                  │
│  - Auth         │         │  - Collect msgs  │
│  - OAuth        │         │  - Store in DB   │
│  - Q&A API      │         │  - Real-time     │
└────────┬────────┘         └────────┬─────────┘
         │                           │
         └────────┬─────┬────────────┘
                  ▼     ▼
         ┌─────────────────────┐
         │  PostgreSQL + Chroma │
         └─────────────────────┘
```

**Run both:**
```bash
# Terminal 1: FastAPI server
PYTHONPATH=. uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Socket Mode listener
python scripts/start_listener.py
```

## Next Steps

After setting up the listener:

1. **Install workspace via OAuth** - Use `/api/slack/install` endpoint
2. **Store app token** - Update installation with app-level token
3. **Start listener** - Run `python scripts/start_listener.py`
4. **Verify collection** - Check database for new messages
5. **Test Q&A** - Query messages via API

The listener will automatically collect all new messages from all connected workspaces!
