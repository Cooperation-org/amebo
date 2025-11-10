# Refactor to ChromaDB Hybrid Architecture - Todo

## Phase 1: Schema Refactor

### PostgreSQL Changes
- [ ] Add `workspace_id` to all core tables
- [ ] Create `installations` table (multi-tenant)
- [ ] Rename `messages` → `message_metadata` (remove text field)
- [ ] Update all foreign keys with `workspace_id`
- [ ] Add workspace isolation (row-level security)
- [ ] Test schema with sample data

### Drop/Archive Old Data
- [ ] Backup existing 11 messages
- [ ] Drop and recreate tables with new schema
- [ ] Re-run database setup

---

## Phase 2: ChromaDB Setup

### Local Development
- [ ] Install ChromaDB (`pip install chromadb`)
- [ ] Create ChromaDB client wrapper
- [ ] Implement collection management (per workspace)
- [ ] Test basic add/query operations

### Collection Design
- [ ] Define metadata schema
- [ ] Test embedding generation
- [ ] Implement search functions

---

## Phase 3: Update Backfill Script

### Dual-Write Logic
- [ ] Refactor message processor (split metadata/content)
- [ ] Update repositories to write to PostgreSQL (metadata only)
- [ ] Add ChromaDB repository (content + embeddings)
- [ ] Implement atomic dual-write (both or rollback)
- [ ] Update sync progress tracking

### Testing
- [ ] Test backfill with dry-run
- [ ] Verify data in both databases
- [ ] Test query functions (hybrid)

---

## Phase 4: Query Layer

### Build Abstraction
- [ ] Create query service (hides PostgreSQL + ChromaDB)
- [ ] Implement hybrid query patterns
- [ ] Add caching layer (optional)

### Example Queries
- [ ] Get messages by channel (PostgreSQL filter → ChromaDB content)
- [ ] Semantic search with filters
- [ ] Most reacted messages (PostgreSQL + ChromaDB enrichment)

---

## Phase 5: Real-time Events (After Refactor)

- [ ] Update event handler for dual-write
- [ ] Test Socket Mode with both databases
- [ ] Monitor sync consistency

---

## Estimated Time

- **Schema Refactor:** 2-3 hours
- **ChromaDB Setup:** 1-2 hours
- **Backfill Update:** 2-3 hours
- **Query Layer:** 1-2 hours
- **Testing:** 1 hour

**Total:** ~7-11 hours (can spread over 2-3 sessions)

---

## Decision Point

Do we:
1. **Refactor now** (recommended - clean foundation)
2. **Finish Phase 1 first** (PostgreSQL only, refactor later with migration)
