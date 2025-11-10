# Hybrid Architecture: PostgreSQL + ChromaDB

## Design Decision: Multi-Tenant Scale with Vector Search

**Date:** 2025-10-30
**Status:** APPROVED - Rebuilding with ChromaDB

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Slack Helper Bot                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────┐         ┌──────────────────┐    │
│  │   PostgreSQL     │         │    ChromaDB      │    │
│  │                  │         │                  │    │
│  │ • Users          │         │ • Message Text   │    │
│  │ • Channels       │         │ • Embeddings     │    │
│  │ • Workspaces     │         │ • Semantic       │    │
│  │ • Reactions      │         │   Search         │    │
│  │ • Links          │         │                  │    │
│  │ • Files          │         │ • Thread Context │    │
│  │ • Sync Status    │         │                  │    │
│  │                  │         │                  │    │
│  │ Message Metadata │◄────────┤ Message Content  │    │
│  │ (who/when/where) │  Ref    │ (what was said)  │    │
│  └──────────────────┘         └──────────────────┘    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Data Distribution

### PostgreSQL: Structured Relational Data

#### Core Tables
1. **workspaces** - Multi-tenant workspace tracking
2. **users** - User profiles (workspace-scoped)
3. **channels** - Channel metadata
4. **message_metadata** - Lightweight message records
5. **reactions** - Normalized reactions
6. **links** - Extracted URLs
7. **files** - File metadata
8. **bookmarks** - Channel bookmarks
9. **thread_participants** - Conversation tracking

#### Operational Tables
10. **sync_status** - Sync progress
11. **processing_queue** - Async jobs
12. **bot_config** - Configuration
13. **installations** - Multi-tenant app installations

### ChromaDB: Message Content + Vectors

#### Collections (per workspace)
- **Collection naming:** `workspace_{workspace_id}_messages`
- **Documents:** Full message text
- **Metadata:**
  - `message_id` (links to PostgreSQL)
  - `workspace_id`
  - `channel_id`
  - `user_id`
  - `timestamp`
  - `thread_ts`
  - `message_type`
- **Embeddings:** Auto-generated or custom

---

## Why This Split?

### PostgreSQL Handles:
✅ Relationships (user → messages, channel → messages)
✅ Aggregations (reaction counts, message counts)
✅ Filtering (by date, user, channel)
✅ Transactions (atomic updates)
✅ Analytics (most active users, channels)

### ChromaDB Handles:
✅ Semantic search ("find messages about X")
✅ Vector similarity (find related discussions)
✅ Content storage (full message text)
✅ Automatic embeddings (no manual pipeline needed)
✅ Horizontal scaling (distributed collections)

---

## Query Patterns

### Pattern 1: Metadata Query (PostgreSQL Only)
```python
# "Show me all PRs from last week"
links = db.query("""
    SELECT l.url, COUNT(r.reaction_id) as reactions
    FROM links l
    JOIN message_metadata m ON l.message_id = m.message_id
    LEFT JOIN reactions r ON m.message_id = r.message_id
    WHERE l.link_type = 'github_pr'
      AND m.created_at > NOW() - INTERVAL '7 days'
    GROUP BY l.url
    ORDER BY reactions DESC
""")
```

### Pattern 2: Semantic Search (ChromaDB Only)
```python
# "Find all messages about deployment issues"
results = chromadb.query(
    query_texts=["deployment problems errors"],
    n_results=20,
    where={"workspace_id": "W123456"}
)
```

### Pattern 3: Hybrid Query (Both)
```python
# "Find messages about authentication from engineers in last month"

# Step 1: Filter in PostgreSQL (fast)
engineering_channel_ids = db.query("""
    SELECT channel_id FROM channels
    WHERE workspace_id = %s AND channel_name = 'engineering'
""", (workspace_id,))

# Step 2: Semantic search in ChromaDB (filtered)
messages = chromadb.query(
    query_texts=["authentication login issues"],
    n_results=50,
    where={
        "workspace_id": workspace_id,
        "channel_id": {"$in": engineering_channel_ids},
        "timestamp": {"$gte": one_month_ago}
    }
)

# Step 3: Enrich with metadata from PostgreSQL
for msg in messages:
    metadata = db.get_message_metadata(msg['id'])
    reactions = db.get_reactions(msg['id'])
    msg.update(metadata, reactions)
```

---

## Multi-Tenant Isolation

### PostgreSQL
```sql
-- Row-level security
CREATE POLICY workspace_isolation ON messages
    USING (workspace_id = current_setting('app.current_workspace'));

-- All queries automatically filtered
SET app.current_workspace = 'W123456';
SELECT * FROM messages; -- Only sees W123456 data
```

### ChromaDB
```python
# Collection per workspace (strongest isolation)
collection = chromadb.get_collection(f"workspace_{workspace_id}_messages")

# OR single collection with metadata filtering
collection.query(
    where={"workspace_id": workspace_id}
)
```

**Recommendation:** Use **collection per workspace** for:
- Perfect isolation
- Independent scaling
- Easier deletion (delete workspace = delete collection)

---

## Impact on Features

### Newsletter Generation ✅ BETTER
**Before (PostgreSQL only):**
- Keyword search for topics
- Simple reaction counting

**After (with ChromaDB):**
```python
# Semantic topic extraction
topics = chromadb.query(
    query_texts=["product updates", "engineering wins", "customer feedback"],
    where={"timestamp": last_week},
    n_results=20
)

# Group similar discussions
clusters = cluster_similar_messages(topics)

# Generate newsletter sections
for cluster in clusters:
    section = generate_section(cluster)
    newsletter.add(section)
```

**Benefits:**
- Auto-discover trending topics (no manual keywords)
- Group related discussions across channels
- Find important context even without keywords

---

### PR Review Automation ✅ BETTER
**Before:**
- Find messages with GitHub links only

**After:**
```python
# Find ALL discussions about a PR (even without link)
pr_discussions = chromadb.query(
    query_texts=[f"PR {pr_number}", pr_title, pr_description],
    where={"workspace_id": workspace_id},
    n_results=50
)

# Find similar past PR discussions
similar_prs = chromadb.query(
    query_embeddings=[pr_embedding],
    where={"message_type": "github_pr"},
    n_results=10
)

# Get feedback patterns
feedback = analyze_pr_discussions(pr_discussions, similar_prs)
```

**Benefits:**
- Find discussions even when PR link not shared
- Learn from similar past PRs
- Identify patterns in feedback

---

### Q&A Feature ✅ ENABLED
**This is why ChromaDB shines:**
```python
# User asks: "How do we deploy to production?"
answer = chromadb.query(
    query_texts=["production deployment process"],
    where={"workspace_id": workspace_id},
    n_results=10
)

# Get relevant context
context = build_context(answer)

# Generate answer with LLM
response = llm.generate(
    context=context,
    question="How do we deploy to production?"
)
```

---

## Data Sync Strategy

### Backfill Process
```python
# 1. Fetch from Slack
message = slack.get_message(channel, ts)

# 2. Store metadata in PostgreSQL
msg_id = postgres.insert_message_metadata({
    'workspace_id': workspace_id,
    'channel_id': channel_id,
    'user_id': user_id,
    'slack_ts': ts,
    'created_at': timestamp,
    'has_reactions': bool(message.reactions),
    'has_thread': bool(message.thread_ts)
})

# 3. Store content in ChromaDB
chromadb.add(
    collection=f"workspace_{workspace_id}_messages",
    documents=[message.text],
    metadatas=[{
        'message_id': msg_id,
        'workspace_id': workspace_id,
        'channel_id': channel_id,
        'user_id': user_id,
        'timestamp': timestamp.isoformat(),
        'thread_ts': thread_ts
    }],
    ids=[f"{workspace_id}_{ts}"]
)

# 4. Extract and store relations (PostgreSQL)
extract_reactions(msg_id, message.reactions)
extract_links(msg_id, message.text)
extract_files(msg_id, message.files)
```

### Real-time Events
```python
@slack.event("message")
def handle_message(event):
    # Same flow as backfill
    sync_message_to_both_dbs(event)
```

---

## Deployment Architecture

### Development
```
Docker Compose:
├── postgres:14
├── chromadb/chromadb:latest
└── app
```

### Production
```
├── AWS RDS PostgreSQL (or Supabase)
├── ChromaDB Cloud (or self-hosted on EC2/ECS)
└── App (Lambda/ECS/Cloud Run)
```

---

## Migration Plan

### Phase 1: Refactor Schema (Current)
- [x] Keep PostgreSQL schema
- [ ] Remove `message_text` from messages table
- [ ] Add `message_metadata` lightweight table
- [ ] Add `workspace_id` to all tables

### Phase 2: Add ChromaDB Integration
- [ ] Set up ChromaDB client
- [ ] Create collection management
- [ ] Update backfill script to write to both
- [ ] Test dual-write

### Phase 3: Update Query Layer
- [ ] Build hybrid query service
- [ ] Update newsletter generation
- [ ] Update PR review logic
- [ ] Test multi-tenant isolation

### Phase 4: Production
- [ ] Deploy ChromaDB (cloud or self-hosted)
- [ ] Migrate existing data
- [ ] Monitor performance
- [ ] Scale as needed

---

## Cost Estimate (100 Organizations)

### PostgreSQL
- RDS db.t3.medium: ~$150/month
- Storage (50GB): ~$10/month
- **Subtotal: $160/month**

### ChromaDB
- **Option A: Self-hosted** (EC2 t3.large): ~$70/month
- **Option B: ChromaDB Cloud**: ~$99-299/month (based on scale)
- **Subtotal: $70-300/month**

### Total Infrastructure
- **Budget option:** ~$230/month (self-hosted ChromaDB)
- **Managed option:** ~$460/month (ChromaDB Cloud)

**vs PostgreSQL-only:** ~$250-550/month (comparable, but ChromaDB scales better)

---

## Performance Expectations

### ChromaDB Benchmarks
- **10M vectors:** <100ms search
- **100M vectors:** <200ms search
- **Horizontal scaling:** Add nodes as needed

### PostgreSQL + ChromaDB
- **Metadata queries:** <50ms (PostgreSQL)
- **Semantic search:** <200ms (ChromaDB)
- **Hybrid query:** <300ms total

---

## Next Steps

1. **Refactor PostgreSQL schema** - Remove message_text, add workspace_id
2. **Set up ChromaDB** - Local development environment
3. **Update backfill script** - Dual write to both databases
4. **Build query layer** - Abstract hybrid queries
5. **Test multi-tenant** - Ensure data isolation

---

## Decision Log

| Date | Decision | Reason |
|------|----------|--------|
| 2025-10-30 | Use ChromaDB instead of pgvector | Multi-tenant scale, better vector search, future-proof |
| 2025-10-30 | Collection per workspace | Strongest isolation, easier scaling |
| 2025-10-30 | Keep PostgreSQL for structured data | Best for relations, analytics, transactions |
| 2025-10-30 | Hybrid query pattern | Leverage strengths of both databases |

---

## Open Questions

1. **ChromaDB hosting:** Self-hosted vs Cloud? (recommend Cloud for production)
2. **Embedding model:** OpenAI vs open-source? (can decide in Phase 2)
3. **Collection strategy:** One per workspace or metadata filtering? (recommend per workspace)
4. **Sync frequency:** Real-time vs batch? (both, with event listener)
