# 🚀 Quick Start Guide - Slack Helper Bot

**Updated:** 2025-11-27 (Week 1, Tuesday)

---

## ⚡ New: Unified Backend (Single Command!)

The backend has been consolidated into a single unified process. No more running multiple scripts!

### Start Everything with One Command:

```bash
# Activate virtual environment
source venv/bin/activate

# Start the unified backend
python -m src.main
```

**This single command starts:**
- ✅ FastAPI server (REST API on port 8000)
- ✅ Slack Socket Mode listener (slash commands, mentions)
- ✅ Background task scheduler (automated backfills)

---

## 📋 Prerequisites

### Required:
- Python 3.10+
- PostgreSQL 14+
- Slack workspace with bot/app installed

### Environment Variables:

Create a `.env` file:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/slack_helper

# Slack Credentials
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# AI (Claude)
ANTHROPIC_API_KEY=sk-ant-your-api-key

# Security (optional - for encrypting stored credentials)
ENCRYPTION_KEY=your-encryption-key
```

---

## 🔧 Setup (First Time Only)

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt
```

### 2. Setup Database

```bash
# Create database
psql -U postgres -c "CREATE DATABASE slack_helper;"

# Run migrations
psql -U postgres -d slack_helper -f migrations/001_initial_schema.sql
psql -U postgres -d slack_helper -f migrations/002_add_chromadb_id.sql
psql -U postgres -d slack_helper -f migrations/003_add_reactions.sql
psql -U postgres -d slack_helper -f migrations/004_add_org_workspaces.sql
psql -U postgres -d slack_helper -f migrations/005_add_users_orgs.sql
```

### 3. Create ChromaDB Data Directory

```bash
mkdir -p chromadb_data
```

---

## 🎯 Running the Application

### Start Unified Backend:

```bash
source venv/bin/activate
python -m src.main
```

**You should see:**
```
======================================================================
SLACK HELPER BOT - UNIFIED BACKEND
======================================================================

🚀 Starting FastAPI server on http://0.0.0.0:8000
🚀 Starting Slack Socket Mode listener
   Bot token: xoxb-...
   App token: xapp-...
✅ Slack listener ready - slash commands enabled
🚀 Starting background task scheduler
✅ Scheduler ready

======================================================================
✅ All services started successfully
======================================================================

📍 API Documentation: http://localhost:8000/api/docs
📍 Health Check: http://localhost:8000/health

Press Ctrl+C to shutdown
```

### Access Points:

- **API Docs:** http://localhost:8000/api/docs
- **Health Check:** http://localhost:8000/health
- **Slack Commands:** `/ask <question>` or `/askall <question>` in Slack

---

## 📊 Using the Bot

### 1. In Slack (Slash Commands)

```
/ask What are the main topics discussed this week?
/askall Who is working on AI projects?
```

- `/ask` - Private response (only you see it)
- `/askall` - Public response (everyone in channel sees it)

### 2. Mention the Bot

```
@Slack Helper Bot What hackathon projects are being discussed?
```

### 3. Via API (Web/Frontend)

```bash
# Login and get token
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "your-password"}'

# Ask a question
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "question": "What are people working on?",
    "workspace_id": "W_DEFAULT",
    "max_sources": 10
  }'
```

---

## 🔄 Backfilling Messages

### One-time Manual Backfill:

```bash
source venv/bin/activate
python scripts/backfill_chromadb.py --workspace W_DEFAULT --all --days 90
```

### Scheduled Automatic Backfills:

Coming in Week 1, Thursday! Will run automatically based on org settings.

---

## 🛑 Stopping the Application

Press `Ctrl+C` in the terminal where `python -m src.main` is running.

**Graceful shutdown will:**
- Close Slack connections
- Stop accepting new API requests
- Complete in-flight requests
- Close database connections
- Clean up resources

---

## 🐛 Troubleshooting

### Port 8000 Already in Use

```bash
# Find process using port 8000
lsof -ti:8000

# Kill it
lsof -ti:8000 | xargs kill -9

# Then restart
python -m src.main
```

### Slack Commands Not Working

1. Check Slack tokens are set: `echo $SLACK_BOT_TOKEN`
2. Verify Socket Mode is enabled in Slack app settings
3. Check logs for connection errors

### Database Connection Errors

```bash
# Test PostgreSQL connection
psql -U postgres -d slack_helper -c "SELECT 1;"

# Check DATABASE_URL in .env
cat .env | grep DATABASE_URL
```

### No Messages Found

1. Run backfill first: `python scripts/backfill_chromadb.py --workspace W_DEFAULT --all --days 30`
2. Verify messages in database: `psql -U postgres -d slack_helper -c "SELECT COUNT(*) FROM message_metadata;"`

---

## 📝 Logs

Logs are written to:
- **Console:** Real-time output
- **File:** `slack_helper.log`

View logs:
```bash
tail -f slack_helper.log
```

---

## ⚙️ Configuration

### Changing the Port

Edit `src/main.py`:
```python
config = Config(
    app=fastapi_app,
    host="0.0.0.0",
    port=3000,  # Change this
    ...
)
```

### Enabling Debug Mode

```bash
export LOG_LEVEL=DEBUG
python -m src.main
```

---

## 🎯 Next Steps

1. ✅ **Running?** Great! Try asking questions in Slack
2. 📊 **Need data?** Run a backfill to collect historical messages
3. 👥 **Add users?** Use the API to invite team members (coming soon)
4. ⚙️ **Configure AI?** Settings API coming in Week 5

---

## 📚 More Documentation

- **API Reference:** http://localhost:8000/api/docs (when running)
- **Production Plan:** `planning/production-plan.md`
- **Phase 1 TODO:** `planning/phase1-todo.md`

---

## 🆘 Getting Help

- Check logs: `tail -f slack_helper.log`
- Test API health: `curl http://localhost:8000/health`
- Review production plan: `planning/production-plan.md`

---

**Last Updated:** 2025-11-27
**Version:** Week 1, Tuesday - Unified Backend
