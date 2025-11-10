# Refactor Status: PostgreSQL + ChromaDB Hybrid Architecture

**Date:** 2025-10-30
**Status:** Schema Refactor Complete ✅ | Backfill Update In Progress 🔄

---

## ✅ Completed

### 1. PostgreSQL Schema Refactor
- **New schema:** `src/db/schema.sql` (refactored version)
- **Backup:** `src/db/schema-old.sql` (original version)

**Key Changes:**
- Added `workspaces` table for multi-tenant support
- Added `installations` table for per-workspace bot tokens
- Renamed `messages` → `message_metadata` (removed `message_text` field)
- Added `workspace_id` to ALL tables (users, channels, reactions, links, etc.)
- Added `chromadb_id` field to track ChromaDB references
- Updated all indexes to include `workspace_id`
- Updated views to be workspace-aware
- Added helper fields: `has_attachments`, `has_files`, `has_reactions`, `mention_count`, `link_count`

**Tables:** 14 total
1. workspaces
2. installations
3. message_metadata (was: messages)
4. reactions
5. channels
6. users
7. thread_participants
8. links
9. files
10. bookmarks
11. teams
12. sync_status
13. processing_queue
14. bot_config

### 2. ChromaDB Setup
- **Installed:** ChromaDB 0.4.22
- **Client:** `src/db/chromadb_client.py`
- **Storage:** `./chromadb_data/` (local, gitignored)

**Features:**
- Collection-per-workspace strategy
- Add/get/delete messages
- Batch operations
- Semantic search
- Metadata filtering
- Collection management

**Tested:** ✅ All operations working

---

## 🔄 In Progress

### 3. Backfill Script Update

**What Needs to Change:**
The current backfill script (`scripts/backfill.py`) writes to the old schema. Need to update for dual-write.

**Required Updates:**

#### A. Update Repositories
All repositories need `workspace_id` parameter:
- `src/db/repositories/message_repo.py` → Update for `message_metadata` table
- `src/db/repositories/channel_repo.py` → Add `workspace_id`
- `src/db/repositories/user_repo.py` → Add `workspace_id`
- `src/db/repositories/sync_repo.py` → Add `workspace_id`

#### B. Add ChromaDB Repository
New file: `src/db/repositories/chromadb_repo.py`
- Wrapper around `chromadb_client.py`
- Handles message content storage
- Batch operations for performance

#### C. Update Message Processor
`src/collector/processors/message_processor.py`
- Split metadata vs content
- Return both for dual-write

#### D. Update Backfill Script
`scripts/backfill.py`
- Add workspace context (hardcode for now, multi-tenant later)
- Dual-write: PostgreSQL metadata + ChromaDB content
- Atomic operations (both succeed or rollback)
- Update progress tracking

---

## 📋 Next Steps

### Immediate (Next Session)
1. [ ] Create default workspace in database
2. [ ] Update all repository files for `workspace_id`
3. [ ] Create `chromadb_repo.py`
4. [ ] Update backfill script for dual-write
5. [ ] Test backfill on one channel
6. [ ] Verify data in both PostgreSQL and ChromaDB

### After Backfill Works
7. [ ] Build hybrid query layer
8. [ ] Create query examples (metadata + semantic search)
9. [ ] Update event listener for dual-write
10. [ ] Test multi-workspace isolation

---

## Architecture Summary

```
Slack Messages
      ↓
   Backfill Script
      ↓
  ┌───────────────────┐
  │                   │
  ↓                   ↓
PostgreSQL        ChromaDB
(Metadata)       (Content)
  │                   │
  └─────────┬─────────┘
            ↓
      Query Layer
   (Hybrid Queries)
            ↓
        Features
  (Newsletter, PR Review, Q&A)
```

---

## Data Flow

### Write Path (Backfill/Events)
```python
1. Fetch message from Slack
2. Parse into metadata + content
3. Write to PostgreSQL:
   - message_metadata (no text)
   - reactions
   - links
   - files
4. Write to ChromaDB:
   - full message text
   - metadata for filtering
   - auto-generate embeddings
5. Update message_metadata.chromadb_id
6. Commit both or rollback
```

### Read Path (Queries)
```python
# Simple metadata query (PostgreSQL only)
most_reacted = db.get_most_reacted_messages(last_week)

# Semantic search (ChromaDB only)
results = chromadb.search("deployment issues")

# Hybrid query (both)
# 1. Filter in PostgreSQL
engineering_msgs = db.filter(channel="engineering", date=last_week)
# 2. Semantic search in ChromaDB with filter
results = chromadb.search(
    "authentication problems",
    where={"message_id": {"$in": engineering_msgs}}
)
# 3. Enrich with PostgreSQL metadata
for msg in results:
    msg.reactions = db.get_reactions(msg.id)
```

---

## Testing Checklist

Before moving to Phase 2:
- [ ] Can insert workspace
- [ ] Can backfill messages to both databases
- [ ] Message text NOT in PostgreSQL (only in ChromaDB)
- [ ] Can retrieve message content from ChromaDB
- [ ] Can search semantically in ChromaDB
- [ ] Can filter by workspace (isolation)
- [ ] Reactions/links stored correctly
- [ ] Thread relationships preserved
- [ ] Sync status tracking works

---

## Migration Notes

**For Existing Data:**
If you had real data in the old schema (we only had 11 test messages), you would need a migration script:
1. Export messages from old `messages` table
2. Split into metadata + content
3. Insert metadata into `message_metadata` (with workspace_id)
4. Insert content into ChromaDB
5. Update references

**Current Status:** No migration needed - we're starting fresh.

---

## Cost & Performance Estimates

### Development (Current)
- PostgreSQL: Local
- ChromaDB: Local persistent storage (~100MB for 10K messages)
- **Cost:** $0

### Production (10 workspaces, 100K messages)
- PostgreSQL (RDS): ~$150/month
- ChromaDB (self-hosted EC2): ~$70/month
- **Total:** ~$220/month

### Production (100 workspaces, 1M messages)
- PostgreSQL (RDS): ~$200/month
- ChromaDB (self-hosted + scaling): ~$200-300/month
- **Total:** ~$400-500/month

---

## Open Questions

1. **Default workspace ID:** Use "W_DEFAULT" for single-workspace mode?
2. **Embedding model:** Use ChromaDB's default or specify OpenAI?
3. **Batch size:** How many messages to write at once (100? 500?)
4. **Error handling:** Rollback strategy if ChromaDB fails but PostgreSQL succeeds?

---

## Files Modified/Created

**Modified:**
- `src/db/schema.sql` (completely refactored)
- `.gitignore` (added chromadb_data/)
- `requirements.txt` (added chromadb)

**Created:**
- `src/db/chromadb_client.py`
- `planning/architecture-chromadb.md`
- `planning/refactor-chromadb-todo.md`
- `planning/refactor-status.md` (this file)

**Backed Up:**
- `src/db/schema-old.sql`
- `src/db/schema-old-backup.sql`

**To Update (Next):**
- `src/db/repositories/*.py` (all repositories)
- `src/collector/processors/message_processor.py`
- `scripts/backfill.py`

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Collection per workspace | Strongest data isolation, easier scaling |
| Remove message_text from PostgreSQL | Avoid duplication, ChromaDB is source of truth for content |
| Add helper fields (has_attachments, etc.) | Fast queries without joining |
| Keep reactions in PostgreSQL | Structured data, not semantic |
| Atomic dual-write | Data consistency between databases |
| Local ChromaDB for dev | Faster iteration, no cloud costs |

---

**Next Session:** Update repositories and backfill script for dual-write.
