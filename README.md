# Slack Helper Bot - SaaS Platform

AI-powered Q&A and knowledge management for Slack workspaces.

## Project Structure

This is a monorepo containing:

```
slack-helper/
├── backend/          # Python FastAPI backend
├── frontend/         # Next.js frontend (coming soon)
└── planning/         # Product roadmap & docs
```

## Quick Start

### Backend

```bash
cd backend
source venv/bin/activate
python -m src.main
```

See [backend/README.md](backend/README.md) for details.

### Frontend

Coming in Week 2!

## Features

### ✅ Completed (Week 1)
- **Workspace Isolation** - Multi-tenant security with 4-layer architecture
- **Unified Backend** - Single command starts all services
- **Automated Backfills** - Scheduled message collection per organization
- **Credential Encryption** - Fernet encryption for Slack tokens at rest
- **Organization Settings** - Configure AI behavior, backfill schedules
- **Background Tasks** - APScheduler for automated jobs

### 🔄 In Progress (Week 2)
- Frontend foundation (Next.js 14)
- User authentication & signup
- Workspace onboarding

### 📋 Planned
- Web-based Q&A interface
- Document upload
- Team management
- Analytics dashboard

## Tech Stack

**Backend:**
- FastAPI (Python)
- PostgreSQL + ChromaDB
- APScheduler
- Slack SDK
- Anthropic Claude API

**Frontend:**
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS + shadcn/ui
- TanStack Query
- Zustand

## Development

See individual READMEs:
- [Backend Development](backend/README.md)
- Frontend Development (coming soon)

## Production Plan

See [planning/production-plan.md](planning/production-plan.md) for the 6-week roadmap.

**Current Status:** ✅ Week 1 Complete (100%)

## License

[Your License]
