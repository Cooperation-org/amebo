# Phase 1: Data Collection Bot - Todo List

## ✅ Completed
- [x] Finalize schema design

## 🔄 In Progress
- [ ] Set up PostgreSQL database and test connection

## 📋 Pending
- [ ] Build Slack client wrapper
- [ ] Implement backfill script
- [ ] Set up real-time event listener

---

## Detailed Breakdown

### 1. ✅ Finalize Schema Design
**Status:** COMPLETE
- Created comprehensive 13-table schema
- Normalized reactions table
- Added thread participants tracking
- Added bookmarks, workspace, teams tables
- Prepared for Phase 2 (embeddings)

**Deliverables:**
- [x] planning/final-schema.sql (530 lines)
- [x] planning/schema-decisions.md
- [x] planning/schema-summary.md

---

### 2. 🔄 Set Up PostgreSQL Database and Test Connection
**Status:** IN PROGRESS

**Tasks:**
- [ ] Install PostgreSQL (if not already installed)
- [ ] Create database: `slack_helper`
- [ ] Run schema.sql to create all tables
- [ ] Verify tables created correctly
- [ ] Create Python database connection module
- [ ] Test basic CRUD operations
- [ ] Set up environment variables (.env)

**Deliverables:**
- [ ] src/db/connection.py
- [ ] .env.example
- [ ] requirements.txt (with psycopg2)

---

### 3. Build Slack Client Wrapper
**Status:** PENDING

**Tasks:**
- [ ] Set up Slack app and get tokens
- [ ] Configure OAuth scopes
- [ ] Create slack_client.py wrapper
- [ ] Implement helper methods:
  - [ ] get_channel_list()
  - [ ] get_channel_history()
  - [ ] get_thread_replies()
  - [ ] get_user_info()
- [ ] Add rate limit handling
- [ ] Test with real Slack workspace

**Deliverables:**
- [ ] src/collector/slack_client.py
- [ ] Slack app configuration documented

---

### 4. Implement Backfill Script
**Status:** PENDING

**Tasks:**
- [ ] Create message processor
- [ ] Create link extractor
- [ ] Create user processor
- [ ] Build backfill.py script with CLI args
- [ ] Add progress tracking
- [ ] Implement resume capability
- [ ] Add error handling and logging
- [ ] Test on small channel first

**Deliverables:**
- [ ] src/collector/processors/message_processor.py
- [ ] src/collector/processors/user_processor.py
- [ ] scripts/backfill.py

---

### 5. Set Up Real-Time Event Listener
**Status:** PENDING

**Tasks:**
- [ ] Choose Socket Mode vs Webhooks
- [ ] Set up Slack Bolt app
- [ ] Subscribe to events (message, reaction, etc.)
- [ ] Create event_handler.py
- [ ] Test real-time message collection
- [ ] Add graceful shutdown
- [ ] Create run script

**Deliverables:**
- [ ] src/collector/event_handler.py
- [ ] scripts/run_collector.py

---

## Success Criteria

Phase 1 is complete when:
- ✅ Database is running with all tables
- ✅ Can authenticate with Slack
- ✅ Backfill script successfully syncs historical messages
- ✅ Real-time listener captures new messages within seconds
- ✅ Data quality verified (threads, reactions, links all working)
- ✅ Can resume interrupted syncs
- ✅ Error handling and logging in place
