# CLAUDE.md

Guidance for any coding agent working in this repository ([AGENTS.md](AGENTS.md) points here). Vendor-neutral despite the name.

## Start here (the map — don't create guidance outside it)

| What | Where |
|---|---|
| **Governing architecture** (multi-org contract, invariants I1–I11, all decisions) | `/opt/shared/projects/plans/amebo/7-4-2026-amebo-architecture.md` — read before changing core code. Being folded into `docs/` by WP18. |
| Coordination board — read FIRST, append status/questions, never delete | [scratch.md](scratch.md) |
| Agent working aids (review checklist — run it before every commit) | [.ai/](.ai/README.md) |
| Architecture & subsystem docs (human-readable) | [docs/](docs/) — start with `docs/BOUNDARIES.md` |
| Work-package plan + runbook | `/opt/shared/projects/plans/amebo/` |
| Hard guardrails (hooks: no stash, no force-push, amebo-services-only systemctl) | [.claude/](.claude/) |

Standing rules (details in the architecture doc): amebo is a **participant, not owner** (I1); core code is **semantic, vendor names only in leaves** (I11); **all outbound gated** (I6); **never `git stash`**; commit as you go; **never use the AskUserQuestion tool** — write questions to the board in plain language.

**Starting with no instructions?** Read the CURRENT STATE header at the top of [scratch.md](scratch.md) — it tells you what's done, what's next, and the operative rules. Announce what you pick up there before you start.

## What Amebo Is

Amebo is a **knowledge cooperation tool** — not a chatbot, not an engineering tool. It helps teams, nonprofits, organizers, activists, and small businesses leverage their collective knowledge to grow and collaborate effectively.

The core purpose: **make a team's scattered knowledge (conversations, contacts, documents, meeting notes, relationships) accessible and actionable through natural questions, with efficient context management that scales.**

Target users: nonprofit teams, community organizers, activists, small businesses who need a growth engine for their network and relationships — not just a Q&A bot over Slack history.

### Design Principles

1. **Source-agnostic** — Slack today, but also email, web, CLI shell, API. The conversation manager doesn't know or care where messages come from.
2. **Instance-configurable** — Each deployment has its own identity prompt, skills, tools, and knowledge sources. A WhatsCookin instance has CRM access; a nonprofit deployment does not.
3. **Efficient context** — Modeled after Claude Code: full thread history with prompt caching (stable prefix cached, only new turn is fresh tokens), compaction when threads get long, 24h TTL garbage collection on stale threads.
4. **Knowledge layered, not monolithic** — Vector search (pgvector) for fuzzy recall, structured bindings (abra) for typed relationships, hot tags for priority, skills for question-type behavior. Each layer adds context without requiring the others.
5. **Tools are per-instance permissions** — An instance's `config.allowed_tools` controls what CLI tools (odoo-cli, abra, mcp-taiga) it can invoke. Never hardcode tool access.

### Architecture Summary

```
Instance (identity + skills + tools + knowledge config)
  └── Thread (source-agnostic conversation: Slack, email, web, API)
       └── Turn (user question + assistant answer)

ConversationManager — builds Claude API calls with:
  - System prompt (identity + knowledge context) → cached
  - Thread history (summary + recent turns) → prefix cached
  - New question → fresh tokens only
  - Compaction when >80K tokens, GC when >24h stale
```

### Key Abstractions

| Concept | Table | Purpose |
|---------|-------|---------|
| Instance | `instances` | Per-deployment config (identity, skills, tools, knowledge) |
| Thread | `threads` | A conversation, any source |
| Turn | `thread_turns` | One exchange within a thread |
| Binding | abra DB `bindings` | Typed relationship (name → target) |
| Content | abra DB `content` | Searchable knowledge (project docs, notes) |
| Hot Tag | abra DB `hot_tags` | Priority flag on a name |
| Skill | `backend/prompts/skills/*.md` → moving to repo-root `skills/` (+ `patterns/`) per arch §7 | Question-type-specific behavior; org overlays live in each org's context repo |

## Architecture Principles

### Org is the Core Grouping Noun
Org (short for Organization) is amebo's top-level grouping. It is **not** Slack-specific. A Slack workspace IS an org, but an org can hold multiple data sources (Slack, email, LinkedIn, documents, etc.).

**Org primitives** (stored via abra as hot-tagged content blobs, not hardcoded):
- Vision — what the org is working toward
- Values — what guides decisions
- Goals — short/medium/long term intentions
- Current context — pointers to relevant knowledge, projects, relationships

These are semantic concepts amebo can interpret. **Apps calling amebo are clients, not part of amebo's core.** Amebo knows about Vision/Values/Goals as concepts. It does not know about Changemaker, LinkedIn, or any specific app. App-specific behavior goes into per-instance configuration, not into core code.

### Channels are General I/O
Slack, email, Twitter/X, Discord are general-purpose channels. They are configured, not hardcoded. If a channel is widely used, it may warrant code-level support, but prefer configuration over baked-in behavior.

### Git Repo Per Org
Each org has one primary Git repo (created on their behalf if they don't have one) holding their context map and org-specific resources. Onboarding: connect existing or create new (in a dedicated GitHub org, private). Credential management: use modern auth (GitHub App or fine-grained tokens), never store passwords.

### Custom Endpoints Are an Antipattern
Other apps (like Changemaker) calling amebo must use amebo's public API generically. Custom per-app endpoints couple apps to amebo internals and create a maintenance burden. All app-facing behavior goes through the standard API surface.

Static HTML demos are a valid exception — they are for fast prototyping only.

### Thin Claw Layer
Goal/agent execution is a separate module, not baked into core Q&A. Controlled by `goal_mode: enabled | disabled` in instance config. When disabled, the goal system is completely inactive. Core Q&A is never affected by goal mode.

### Instances Serve Multiple Orgs (updated 2026-07-04 — supersedes the old one-to-one rule)
An instance is a deployment/persona; it can serve N orgs (`instance_orgs` join, mig 020; `instances.org_id` is deprecated). Every action resolves its target org per the architecture doc §4.2 (explicit "under <org>" → thread pin → channel default → sole membership → ask). Orgs are any size, provisioned generically — no use-case knowledge in core (I3).

### Vision/Values/Goals Storage (Abra)
- Stored as abra content blobs with hot tag flags (`hot tag definition`)
- Queried at runtime via abra when building context
- No fixed schema — flexible semantics per org
- Amebo can interpret meaning but does not enforce structure

## Development Commands

### Backend (Python/FastAPI)

```bash
cd backend && source venv/bin/activate

# Run (port 8001 for rearchitect test instance)
API_PORT=8001 python -m src.main

# Tests
pytest
pytest tests/test_qa_service.py
pytest -k "test_name"

# Formatting
black src/ && flake8 src/
```

### Production (systemd on VM 200)

```bash
# Live primary (port 8000) — no isolated test instance exists (tmp-amebo2 retired 2026-06-07)
sudo systemctl status amebo-backend
sudo journalctl -u amebo-backend -f

# Frontend
sudo systemctl status amebo-frontend
```

### Key Environment Variables

```
DATABASE_URL          — amebo DB on Postgres VM 100
ABRA_DATABASE_URL     — abra DB (read-only, for structured knowledge)
ANTHROPIC_API_KEY     — Claude API
SLACK_BOT_TOKEN       — Slack bot token
SLACK_APP_TOKEN       — Slack app token (Socket Mode)
USE_EVENT_SUBSCRIPTIONS — 'true' for HTTP webhooks instead of Socket Mode
```

## Related Repos & Tools

- `/opt/shared/repos/abra` — binding spec + pgvector CLI (aliased as `lingo`)
- `/opt/shared/projects/` — team projects, plans, docs (ingested into abra)
- `odoo-cli` — CRM operations (contacts, follow-ups, tags) — available to WhatsCookin instance
- `mcp-taiga` — task management — available to WhatsCookin instance
- `abra` — knowledge base search — available to all instances (scoped by org)

## Backend Structure (`backend/src/`)

**Routes → Services → Repositories → Database**

- `api/routes/` — REST endpoints: `auth`, `qa`, `documents`, `workspaces`, `bindings`, `team`, `organizations`, `slack_oauth`, `admin`
- `services/conversation_manager.py` — **THE KERNEL**: thread context, caching, compaction
- `services/qa_service.py` — RAG pipeline: vector search + knowledge base + bindings → Claude
- `services/binding_service.py` — structured knowledge enrichment
- `services/ingestion_service.py` — source-agnostic content storage
- `db/pgvector_client.py` — vector storage/search (replaces chromadb)
- `db/abra_connection.py` — read-only connection to abra's knowledge
- `db/repositories/` — thread_repo, instance_repo, binding_repo, message_repo, etc.
- `prompts/identity.md` — default identity prompt
- `prompts/skills/*.md` — skill definitions with YAML frontmatter + triggers
