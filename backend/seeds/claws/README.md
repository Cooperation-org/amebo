# Portable claws

Claws in here are deploy-independent: the mechanics are the claw, the contents
are whatever board, CRM and channel the deploy points at. A new deploy pulls the
repo and loads them instead of copying rows between databases.

One file per claw:

```json
{
  "claw":     { "title": "...", "description": "...", "trigger_config": {...} },
  "requires": ["what must already exist on the deploy for this claw to work"],
  "notes":    "one line on what it does"
}
```

`claw` is exactly the `POST /api/goals/` body. `requires` and `notes` are for the
person loading it and are not sent. The notify channel is deliberately absent —
it belongs to the deploy, so the loader supplies it:

```bash
python backend/scripts/seed_claws.py --notify slack:#your-channel
python backend/scripts/seed_claws.py --notify slack:#your-channel --dry-run
```

The loader posts through the API with the same `X-API-Key` file `amebo-claw`
uses, so claws land under the key's org and go through one write path. It skips a
claw whose title already exists, so re-running it is safe.

## Adding one

A claw belongs here only if its body names no person, project, repo or channel of
one team. Read the description back and ask whether another team could run it
unchanged. Anything team-specific stays in that deploy's database.
