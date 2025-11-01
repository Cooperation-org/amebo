# Slack Helper Bot - Implementation Plan

## Project Overview

Building a comprehensive Slack Helper Bot that collects and analyzes workspace knowledge to help developers find information faster.

### Problem Statement
Junior developers and new team members struggle to find information scattered across Slack channels. Senior devs spend time answering repeated questions.

### Solution
A bot that:
- Collects all Slack messages and metadata
- Answers questions based on historical conversations
- Reviews PRs and provides feedback
- Summarizes threads and highlights important discussions

---

## Project Phases

### Phase 1: Data Collection Bot ⭐ (CURRENT FOCUS)
Build always-on collector that captures all messages from channels the bot is added to.

**Goal:** Have a rich, queryable database of workspace knowledge.

### Phase 2: AI Query Features (Future)
- Q&A on project/company knowledge
- Semantic search with embeddings
- Thread summarization

### Phase 3: PR Review & Integrations (Future)
- GitHub/GitLab PR analysis
- Integration with docs tools (Notion, Confluence)
- Newsletter generation from collected data

---

## Architecture Decision

**Approach:** Standalone comprehensive bot (not MCP extension)
- Always-running service (vs on-demand MCP)
- Newsletter becomes a feature using collected data
- Clean separation of concerns

**Collection Strategy:**
```
┌──────────────┐     ┌──────────────┐     ┌──────────┐
│  Backfill    │────→│  PostgreSQL  │←────│  Events  │
│  Worker      │     │              │     │  API     │
│  (one-time)  │     └──────────────┘     │ (ongoing)│
└──────────────┘                          └──────────┘
```

**Deployment Path:**
1. Local development
2. Docker containerization
3. Cloud hosting (production)

---

## Project Structure

```
slack-helper-bot/
├── planning/                # Documentation and planning
│   ├── implementation-plan.md
│   ├── schema-decisions.md
│   └── phase1-todo.md
├── src/
│   ├── collector/          # Phase 1: Data collection
│   │   ├── slack_client.py
│   │   ├── event_handler.py
│   │   ├── backfill.py
│   │   └── processors/
│   │       ├── message_processor.py
│   │       ├── user_processor.py
│   │       └── file_processor.py
│   ├── db/
│   │   ├── schema.sql
│   │   ├── connection.py
│   │   └── repositories/   # Data access layer
│   │       ├── message_repo.py
│   │       ├── channel_repo.py
│   │       └── sync_repo.py
│   ├── bot/               # Phase 2: Interactive bot
│   │   ├── commands/
│   │   └── handlers/
│   ├── ai/                # Phase 2: AI features
│   │   ├── embeddings.py
│   │   ├── qa_engine.py
│   │   └── pr_reviewer.py
│   └── api/               # Phase 2: REST API (optional)
├── scripts/
│   ├── setup_db.py
│   ├── backfill.py
│   └── run_collector.py
├── tests/
├── config/
│   └── settings.py
├── .env.example
├── requirements.txt
└── README.md
```

---

## Technology Stack

**Core:**
- Python 3.10+
- PostgreSQL 14+ (with pgvector extension for Phase 2)
- Slack SDK (slack-sdk, slack-bolt)

**Data Collection:**
- Slack Events API (Socket Mode for local dev)
- Async processing (asyncio/aiohttp)

**Future (Phase 2):**
- Vector embeddings (OpenAI API or local models)
- LLM integration (Anthropic Claude, OpenAI)

---

## Current Status

🔄 **In Progress:** Finalizing database schema for data collection

**Next Steps:**
1. Finalize schema design
2. Set up database and test connection
3. Build Slack client wrapper
4. Implement backfill script
5. Set up real-time event listener
