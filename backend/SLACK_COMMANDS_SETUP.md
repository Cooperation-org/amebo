# Using Q&A Directly in Slack Workspace

Ask questions directly in your Slack workspace using slash commands!

## Quick Start

### 1. Configure Slack App

Go to https://api.slack.com/apps → Your App:

#### A. Enable Socket Mode
- **Settings** → **Socket Mode** → Enable
- Generate **App-Level Token** with `connections:write` scope
- Copy token (starts with `xapp-`)
- Add to `.env`: `SLACK_APP_TOKEN=xapp-your-token`

#### B. Create Slash Commands
- **Features** → **Slash Commands** → Create New Command

**Command 1:** `/ask`
- Command: `/ask`
- Request URL: (leave empty for Socket Mode)
- Short Description: `Ask a question (private answer)`
- Usage Hint: `What are people discussing about AI?`

**Command 2:** `/askall`
- Command: `/askall`
- Request URL: (leave empty for Socket Mode)
- Short Description: `Ask a question (public answer)`
- Usage Hint: `What hackathon projects are being discussed?`

#### C. Enable Events (for @mentions)
- **Event Subscriptions** → Enable Events
- Subscribe to **Bot Events**:
  - `app_mention` (so users can @mention the bot)

#### D. OAuth Scopes
Make sure you have these scopes:
- `channels:history`
- `channels:read`
- `chat:write`
- `commands` (for slash commands)
- `app_mentions:read` (for @mentions)

#### E. Reinstall App
After making changes, reinstall to your workspace:
- **Settings** → **Install App** → Reinstall to Workspace

### 2. Update .env

```bash
# Make sure these are set
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token  # For Socket Mode
SLACK_SIGNING_SECRET=your-signing-secret
ANTHROPIC_API_KEY=sk-ant-your-key
```

### 3. Start the Command Handler

```bash
source venv/bin/activate
python scripts/start_slack_commands.py
```

You should see:
```
🚀 Starting Slack command handler...
⚡️ Bolt app is running!
```

## Usage in Slack

### Option 1: Slash Command (Private)
Only you see the answer:
```
/ask What hackathon projects are being discussed?
```

### Option 2: Slash Command (Public)
Everyone in the channel sees the answer:
```
/askall What are the main topics this week?
```

### Option 3: @Mention the Bot
```
@YourBotName What technical challenges have people mentioned?
```

## Example Questions

```
/ask What are people working on this week?
/ask Who is discussing AI projects?
/ask What are the most mentioned tools or technologies?
/ask Summarize the discussions about the hackathon
/ask What questions have people asked in #general?
```

## Response Format

The bot will reply with:
```
Question: What hackathon projects are being discussed?

Answer:
Based on recent Slack messages, several hackathon projects are being discussed:

1. DoraHacks Hackathon - Multiple team members are working on submissions
2. AI Customer Care Bot - John and Sarah are building a multi-tenant solution
3. Data Collection Bot - Being developed with GitHub integration
...

Sources:
1. #hackathons - john: "Just submitted our DoraHacks project!"
2. #general - sarah: "The AI care bot is looking great..."
3. #standup - mike: "Working on the data collector today"

Confidence: high | Sources: 8 messages
```

## Running Everything Together

You need **2 terminal windows**:

**Terminal 1: Command Handler (for Slack commands)**
```bash
source venv/bin/activate
python scripts/start_slack_commands.py
```

**Terminal 2: Listener (for collecting new messages)**
```bash
source venv/bin/activate
python scripts/start_listener.py
```

## Architecture

```
Slack Workspace
     │
     ├─ User types: /ask What's being discussed?
     │
     ▼
Socket Mode (WebSocket)
     │
     ▼
Command Handler
     │
     ├─ Extracts question
     ├─ Calls QAService
     │   └─ Searches ChromaDB
     │   └─ Calls Claude API
     └─ Sends formatted answer back to Slack
```

## Troubleshooting

**"Command not found" when typing /ask**
- Solution: Make sure you created the slash command in Slack app settings
- Reinstall the app to your workspace

**Bot doesn't respond**
- Check command handler is running: `python scripts/start_slack_commands.py`
- Verify `SLACK_APP_TOKEN` is set in `.env`
- Check logs for errors

**"No messages found"**
- Make sure listener collected messages: `python scripts/start_listener.py`
- Check ChromaDB has data:
  ```python
  from src.db.chromadb_client import ChromaDBClient
  client = ChromaDBClient()
  collection = client.get_or_create_collection('YOUR_WORKSPACE_ID')
  print(collection.count())  # Should show message count
  ```

**Slow responses**
- First query may be slow (loading embeddings)
- Subsequent queries should be faster
- Consider reducing `max_sources` for faster responses

## Tips

1. **Use `/ask` for private questions** - Great for sensitive topics
2. **Use `/askall` to share knowledge** - Good for team-wide questions
3. **Be specific** - Better questions = better answers
4. **Check sources** - The bot shows which messages it used

## Next: API Access

You can also ask questions via the REST API:

```bash
curl -X POST 'http://localhost:8000/api/qa/ask' \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What are people discussing?","max_sources":10}'
```

This is useful for:
- Building a web dashboard
- Programmatic access
- Integration with other tools
