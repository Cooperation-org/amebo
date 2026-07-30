# A new amebo deploy — own VM, own database, own tools

Status: written 2026-07-30 (AI-drafted from the code, for review).

For a deploy that is not a new tenant on an existing amebo but a separate
installation with its own Postgres database and its own Taiga, CRM and Slack.
The first one is workers.vc. Nothing is copied database-to-database; the code and
the portable claws come from this repo, the rest is that deploy's own config.

## 1. Database

Against the new database, in order:

```bash
psql "$DATABASE_URL" -f backend/setup_database.sql
for f in backend/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
```

The work list reads `goals`, `pending_actions`, `organizations`, `instances`,
`api_keys` and `platform_users`. All of them are created above.

## 2. Org and instance rows

One `organizations` row and one `instances` row (slug, `identity_prompt`,
`config.allowed_tools`). `backend/scripts/create_changemaker_instance.py` is the
worked example. Instance config is read per request, so changing it needs no
restart; adding a tool to the code registry does need one.

`allowed_tools` is the whole authority boundary — a tool the instance does not
list cannot be used even if it exists in the registry.

## 3. Its own Taiga account (do not skip)

The work list's main source is `open_dated_stories()`: **every** open story with a
due date that the configured Taiga account can see, not a filtered set, and the
credentials are process-level env (`TAIGA_URL`, `TAIGA_USERNAME`,
`TAIGA_PASSWORD`), not per-org. So the account's visibility *is* the filter. Give
the deploy an account on its own Taiga whose only boards are its own. Point it at
a shared account and the list fills with another team's work.

`TAIGA_UI_URL` sets the host used in the links the list hands out; it falls back
to `TAIGA_URL`.

## 4. Its own channel and CRM

Slack bot token and channel belong to the deploy. Same for the CRM connection if
it files chatter. The `+tag` mail router already resolves the CRM database per
message, so one mailbox can serve several teams; a separate deploy can equally
poll its own.

## 5. Load the portable claws

```bash
python backend/scripts/seed_claws.py --notify slack:#its-channel --dry-run
python backend/scripts/seed_claws.py --notify slack:#its-channel
```

See `backend/seeds/claws/README.md`. Each seed lists what must already exist —
the follow-up sweep loads an org skill by name, so that skill has to be on the
deploy or the claw runs into nothing.

Team-specific claws are not portable and stay where they are.

## Known rough edges

- `GET /api/goals/{id}` returns 500 on this deploy, so `amebo-claw show` does not
  work; the list and create paths are fine.
- `trigger_config` is written two ways in existing rows — `{"cron": "..."}` and
  `{"type": "cron", "expression": "..."}`. The seeds carry whichever shape their
  claw was created with. Worth settling on one.
