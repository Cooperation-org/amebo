# Whiteboard

An **input surface** — a chatter log, not a record (Golda, 2026-07-16: "whiteboard is
for input, its like a chatter log. then amebo has to be smart enough to put into
structured project but there can be different types of structures").

People jot project talk as it happens ("got paid 800 on streetwell", "deadline moved to
friday", "promised Alice 40%"). Amebo files each fact into its one home and stamps the
entry. Nothing lives on the whiteboard; a "clean" board is the success state.

## What exists (2026-07-16)

- `whiteboard_entries` table (migration 027): append-only, org-scoped, with
  `processed_at` + `filed` stamps. This is transient in-flight state — the one kind
  amebo may own (BOUNDARIES).
- API `/api/whiteboard/` — list (`?unprocessed=true`), add, `/{id}/processed`.
  User JWT or service X-API-Key, same auth as pending-actions.
- Dashboard page `/dashboard/whiteboard` — jot box + recent entries, "filed" check
  when amebo has processed one.

## The filing pass (designed, NOT yet built)

A claw (goal-loop work, WP12–16) that:

1. Reads `GET /api/whiteboard/?unprocessed=true`.
2. For each entry, extracts facts and routes each to its one home:
   - deal terms / budget / splits / payouts → **projects tracker**
     (govkit `/api/v1/projects/orgs/<slug>/projects/…` — deal, payouts, links)
   - people/knowledge/context → **abra** (scope + catcode per BOUNDARIES)
   - tasks/deadlines → **Taiga**; contact facts → **CRM**
3. Anything money-shaped or outbound goes through the existing draft-approval gate
   (now with **feedback** — a decline that re-arms the goal with the human's words,
   so amebo redrafts instead of dropping it).
4. Stamps the entry: `POST /{id}/processed` with `filed=[{store, ref}, …]`.

Ambiguous entries don't get guessed at: the claw asks (needs-input) or leaves the
entry unfiled — an unfiled entry visible on the board IS the signal that amebo
didn't understand it.

Slack is a second mouth of the same funnel: channel talk amebo already hears can
feed the same extract-and-file pass; the whiteboard is for what isn't said in a
channel amebo is in.
