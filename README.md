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

## Composing amebo into someone else's page

Amebo ships a **web-component bundle** (`embed/amebo.js`, served at `/embed/amebo.js`)
so any dashboard can carry a card that asks amebo a question, shows the org's goals, or
lists its claws — without that page knowing anything about amebo but its base URL.

```html
<script src="https://amebo.workers.vc/embed/amebo.js" defer></script>
<amebo-goals data-up="https://amebo.workers.vc"></amebo-goals>
```

**Org is never an attribute** — amebo resolves it from the authenticated session, so the
components always show the viewer's own org.

- [`embed/README.md`](embed/README.md) — the component reference: every tag, its backing
  endpoint, whether it mutates, the auth and 401-refresh contract.
- **`govkit/docs/COMPOSITION.md`** — the master document for how these components compose
  into a dashboard with GovKit's and the CRM's: the diagram, the catalog across all
  repos, the contracts, and how to run the whole composition locally.

## Running it

Backend: Python/FastAPI under [backend/](backend/).

```bash
cd backend
python -m venv venv && venv/bin/pip install -r requirements.txt
cp ../.env.production.example .env        # local values, not production ones
PYTHONPATH=. venv/bin/uvicorn src.api.main:app --reload --port 8000
```

Frontend (Next.js): `cd frontend && npm install && npm run dev -- -p 3087`.

A dashboard running on your machine needs its origin in the backend's `CORS_ORIGINS`
allowlist before the embed components will answer it.

Caution on the backend docs: `backend/GETTING_STARTED.md` still describes the Slack
helper bot this repo grew out of, and `backend/README.md` names `src.main` rather than
`src.api.main`. The uvicorn line above is the current entry point.

The live primary runs as the `amebo-backend` systemd service on the team dev VM.

*(This README replaced an auto-generated one that described a different product; see git history if you need it.)*
