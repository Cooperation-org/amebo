# Amebo

Amebo is a **team agent**: a participant in an organization's existing spaces — its Slack, git repos, CRM, task tracker, knowledge base — that helps the team pursue its goals. It reads what's there, does the work, writes back attributably (every outbound action gated for human approval), and asks short questions like a colleague. It owns nothing: facts live in the org's own tools; amebo holds only pointers, credentials, and in-flight state.

It is not a chatbot and not primarily a codebase — goals are mostly achieved through people, content, and coordination; code is the plumbing.

## Where to go

| You are | Start at |
|---|---|
| A human getting oriented | [OVERVIEW.md](OVERVIEW.md), then [docs/](docs/) (architecture: `docs/BOUNDARIES.md`) |
| An agent working in this repo | [AGENTS.md](AGENTS.md) → [CLAUDE.md](CLAUDE.md) |
| Anyone wondering what's happening right now | [scratch.md](scratch.md) — the live coordination board (CURRENT STATE header at top) |
| Looking for the governing multi-org architecture | `/opt/shared/projects/plans/amebo/7-4-2026-amebo-architecture.md` |

## Running it

Backend: Python/FastAPI under [backend/](backend/) (`backend/GETTING_STARTED.md`). The live primary runs as the `amebo-backend` systemd service on the team dev VM.

*(This README replaced an auto-generated one that described a different product; see git history if you need it.)*
