# The work list

One ranked list of what needs a human, assembled from what the team's systems
already hold.

`src/services/work_list.py` (the rules, pure), `work_list_taiga.py` and
`work_list_crm.py` (the vendor leaves), `src/api/routes/work_list.py` (the API),
`frontend/app/dashboard/list/` (the page).

## What a card may contain

- What a person said, attributed, with a way back to where they said it.
- The thing itself, and its links.
- One reason it is where it is.

Nothing amebo wrote about its own activity. If it did something useful, the
result is on the card, not a report about it.

Their words means the words a person typed. Chatter that arrived by mail carries
amebo's own stamp and the mail client's header block; both are stripped, and the
words are attributed to the `From:` line of the forward rather than to whoever
pasted it in (`human_words`).

## Where the cards come from

| Source | What reaches the list | What does not |
|---|---|---|
| Taiga | open stories with a due date | closed, blocked boards, work owned by amebo |
| Odoo CRM | scheduled follow-ups (`mail.activity`) | undated leads — 1237 of them; a list is not a backlog |
| amebo goals | goals at `waiting_user` | queued goals; those are amebo's own work |
| amebo drafts | drafts not about a task already listed | a draft about a listed task is not a second row |

The four are read at the same time, so opening the list costs the slowest source
rather than all four added up. Each fails on its own: a source that is down
loses its own rows and nothing else.

## Card kinds

A card's type is read back out of its subject, never stored twice.

| Subject | Kind |
|---|---|
| `taiga:<slug>#<ref>` | task |
| `crm:activity/<id>` | contact |
| `goal:<uuid>` | goal |
| `draft:<uuid>` | draft |

An unknown scheme reads as a task, so a new source shows up as an ordinary row
instead of breaking the page. Every kind sits on one ladder — a call due
tomorrow beside a task due tomorrow — and only the controls on the opened sheet
differ.

## Ranking

Two halves, and every card says which one put it where it is.

- **Clock** — dated. Sooner is higher. Deterministic, needs no defending.
- **Judgement** — undated. Kept small and explainable, and capped below the
  clock band so judgement can never bury a dated card.

What went past its date drops out of the live list into `past`: visible without
nagging from the top.

## Whose list it is

You see what you own, plus what nobody owns yet. Work assigned to amebo's own
account is on nobody's list unless it is holding a question for you.

The map from an amebo login to an account elsewhere is per-team config, read
fresh on every request, so adding a teammate never needs a deploy:

- `config.taiga_identities` — `{login: taiga username}`
- `config.crm_identities` — `{login: odoo login | [odoo logins]}`, a list because
  one human can hold more than one account in the same CRM

Matching is by id, never display name: this CRM has two accounts both reading
"Golda Velez".

An unmapped viewer gets no filtering rather than an empty list. Seeing too much
is a nuisance; seeing nothing looks like the product is broken.

Who a person **is** stays in abra (`taiga:username/<n>`). Only the login side
lives in amebo, because abra refuses to store an email address at all.

## Staying current

Amebo's own changes push, over server-sent events (`src/services/live.py`,
`GET /api/work-list/stream`): a goal crossing into or out of `waiting_user`, an
edit someone pressed, a draft handed back. The event carries no content, only
"look again" — the browser refetches through the one endpoint that assembles the
list, so there is no second copy of the truth arriving by another road.

Taiga and Odoo have no change feed pointed at us, so something edited directly
in Marten or the CRM is found by a slow fallback refresh instead.

Subscribers live in memory, which is correct while amebo is one process with one
event loop. More than one process means putting Postgres LISTEN/NOTIFY behind
`publish()`/`subscribe()`, and nothing else changes.

## Writes

Every write a human presses goes through the registered executors in
`src/tools/gated_actuators.py` — the same ones the draft gate would have run on
approval. One write path, no new authority.

Not gated: the gate exists to stop the claw acting unilaterally, and when the
human presses the button there is nothing to gate. Every edit is checked against
the org's own list first, so a subject the org was never shown cannot be edited
by passing it in.

Links to a story always go to Marten (`/p/<slug>/board?story=<ref>`), never
Taiga's own interface. One function builds them so a Taiga link cannot creep
back in through a second one.

## Saying what is wrong

One line at the foot of the page. Whatever row is open goes with the words, so
two words are enough. It is filed as a story on `config.feedback_board` — where
work already lives, because a note nobody sweeps is a note nobody reads. The
person's words become the title.

Pushed back on only when nobody could act on it later: a couple of words about
no row in particular. The board is never guessed.

That is the filing half. Whether a fixing session runs on demand or on a clock,
and whether a fix deploys straight or waits, are open.

## Still open

- Rescheduling a CRM follow-up. The card is read-only because there is no write
  path to `mail.activity` yet — `odoo-cli schedule` creates a new activity
  rather than moving the existing one, which would leave two.
- The fixing half of the feedback loop.
- Per-user Taiga tokens in the browser. Worth revisiting on its merits
  (attribution: edits from the list are currently made by amebo's account), but
  measured, it was not what made the list feel slow.
