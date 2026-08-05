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

Ordered by what a person would notice first.

### Rescheduling a CRM follow-up

Contact cards are read-only and carry no push-out control, so the one thing you
most want to do to a follow-up — move it a week — has to be done in Odoo.

`odoo-cli schedule` **creates** an activity; it cannot move an existing one, so
using it here would leave two. Needs either a new `odoo-cli` verb that writes
`date_deadline` on a given `mail.activity`, or a `crm_reschedule` executor
registered alongside the others. Either way it goes through the executor
registry like every other write — not straight from the route.

### The fixing half of the feedback loop

Saying what is wrong works and files a story. What happens next does not exist.
Two questions are still Golda's to answer:

- does the fixing session run on demand, or on a clock?
- does a fix deploy straight, or wait for someone?

(The third — how little a person may say — is answered: two words, because the
open row goes with them.)

### Per-user Taiga tokens, for attribution

Every edit made from the list is written by amebo's Taiga account, so the board
history says amebo changed things a person changed. That is the real argument
for per-user tokens.

It is **not** a speed argument. Measured: an edit costs about 0.2s and the
opening cost about 6s, so browser-side tokens would have fixed the thing that
was not broken.

### One idea of "important", two implementations

`govkit/apps/tasksources/ordering.py` reimplements this ranking rule. The
constants are deliberately identical so the drift is easy to spot.

The decision, which is an architecture call and not a coding one: **does the
ranked list become a service other apps read, or does each app rank its own
tracker data?** If the first, govkit's ordering module is the first caller and
should be deleted.

### A campaign lens

Rank deep, show shallow, and make the visible slice representative — some from
each campaign — rather than the raw top rows. The mechanism already exists;
`top()` reserves slots so one band cannot take the whole page.

What blocks it is data, not code: 1092 of 1237 CRM leads carry `campaign_id`,
and **a Taiga story has no campaign field at all**. A campaign filter built
today would silently cover CRM rows and drop every task, which reads as broken
rather than filtered. How work gets tagged to a campaign is a question for
Golda. Do not guess it.

### The remaining two and a half seconds

Almost all of it is one Taiga query for every open story, which is Taiga's own
speed. The next real win is asking it for less, or holding the answer between
requests — not more concurrency, which is spent.

### More than one process

Change notices live in memory, which is correct for one uvicorn process with one
event loop. A second process silently halves who hears them. Putting Postgres
LISTEN/NOTIFY behind `publish()`/`subscribe()` is the whole change; nothing else
has to move.
