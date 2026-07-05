# Dashboard — design decisions

*AI-written (Claude Fable) record of Golda's spoken direction, design session 2026-07-05. Quoted phrases are her words. Implementation instructions for v1: `/opt/shared/projects/plans/amebo/7-5-2026-dashboard-v1-instructions.md`.*

## The standing principle: everything visible is relevant to the team

Golda (2026-07-05): "the principle is a little like the abra view one — everything we see should be relevant to the team. No extra clutter, cruft, words." Applied to every amebo surface: no section headings over things that explain themselves (pills, cards), no counts or dividers that don't help someone act, no label whose only job is naming the UI itself ("Dashboard", "Your tools", "Tools"). If a word can be removed without losing the ability to act, remove it. Accessibility labels stay, visually hidden.

## The core decision: orientation surface, not workspace

The dashboard **orients** a team member — what are our tools, what are our campaigns, where is the work — and then **sends them to the tool that owns the thing**. It is not an editing surface.

Golda's reasoning (2026-07-05): "a good app is super fast and responsive... because it's actually dealing directly with the database. Anything I see, I wanna be able to touch and change. And you can't do that with this cached assembled view." A mutable assembled view over three sources "is gonna become a mess" — so we don't build one. Fast editing happens in the app that sits next to its database (Marten, the CRM); the dashboard's job is to get you there in one click, oriented.

This is participant-not-owner (I1) applied to UI: Hermes gets its dashboard speed by owning all the data in its own store; amebo gets its honesty by not pretending to. Read-only glance here, real work in the real tool.

## v1 scope (building now)

1. **Key links bar** — the org's main tools (LinkedTrust: Marten, CRM, projects repo, chat). Per-org configurable, already backed by `GET/PUT /api/organizations/links` (instance `config.links`). Never hardcoded.
2. **Campaigns board** — one card per live campaign, read from the org's context repo `campaigns/<slug>/MAIN.md` (the convention documented in `projects/campaigns/README.md`: MAIN.md is content truth, mirrored by a CRM campaign for who/response tracking). Card face: name, one-liner, status, owner; links out to the MAIN.md, the CRM campaign, the Taiga board.
3. **Chat list** — the user's conversations with amebo, sidebar, links into the chat interface.

Everything on it links out. No edit-in-place anywhere in v1.

## Template principle

Campaigns-board is **one template, not amebo's UI**. "I don't know that that is always going to be what amebo users want... it would be nice if that's a template that can be the front end of amebo, but it can also completely change its front end to something else." Core stays campaign-ignorant (I3): the board endpoint reads a per-instance config (what kind of board, which repo dir it binds to); "campaign" is vocabulary that lives in the LinkedTrust template and the org's own repo convention. Another org's template could be cases, clients, or no board at all.

## Data entry: chat is the entry path (Golda, 2026-07-05)

"Anytime I see something, I am gonna want to enter data." The answer is not edit-forms on the dashboard — it's chat + gated drafts: tell amebo what you saw, it drafts the write into the *correct home* (CRM note, task, campaign log line), you approve. The create-campaign "+" flow is the first instance of this pattern (chat-scoped draft → one-click approve → gated writes to repo + CRM). If capture friction shows up, the future affordance is a one-tap "note this" on any card that pre-fills chat — a thin ribbon over the same gated path, never a direct write.

## Recorded for later (NOT in v1 — deliberate deferrals)

- **Suggested next steps (the judgment layer).** Amebo-generated per-campaign suggestions ("what's the next contact"), overridable by the user, whose word always wins. An *accepted* suggestion graduates into the owning tool — a next-contact becomes an Odoo activity (`crm_schedule` exists), a work item becomes a Marten task. Amebo keeps only the transient draft, never the accepted fact.
- **Crystallized status lines.** One line per card: "given the world plus this org's goals, what does this user need to see right now" — the first UI consumer of [CRYSTALLIZE.md](CRYSTALLIZE.md). Regenerated when underlying sources change or on explicit refresh; never an LLM call per page load.
- **Read-model cache.** If assembly ever gets slow: cached per-card slices in amebo's DB with per-source freshness timestamps, **display-only** — shown with their age, never acted on; any action re-reads fresh (that keeps it I1-legal). Not needed at v1 scale.
- **Social listening claw.** Surface when campaign targets post something worth reacting to; research them; know where their Slacks/Discords are; remind when re-outreach is due. Blocked on data-homing: targets currently "somewhere in CSVs or work files or somewhere in the CRM... not surfaceable" — they must be homed in the CRM first (a one-time gated ingestion job).
- **The CRM question.** The fast editing surface for contacts/campaigns long-term is a better CRM front end — improving Odoo's UI or eventually replacing it ("we need to improve the Odoo CRM interface or write our own CRM... it needs to be close to the database"). NOT an amebo sync layer.
- **Shared boards** (e.g. Alonovo board with George Polishner) require nothing new: a board is org-scoped; membership + OIDC login = both see it.
- **Backwards-facing team log view** — dated, tagged, searchable "what happened" history; the substrate of Kene's original weekly-newsletter idea. Recorded in [TEAM_LOG.md](TEAM_LOG.md).
- **Analytics tab** (Golda, 2026-07-05). The old dashboard's stat counters (active workspaces, messages indexed, queries this month, documents) do NOT belong on the orientation dashboard — it read as clutter and buried the tools. Move those numbers into a separate **Analytics** tab. The `GET /api/organizations/stats` endpoint that fed them still exists; nothing was deleted, just taken off the orientation surface.
- **Shared / multi-participant web chats.** Golda (2026-07-05): "because this is a team, I'd like to be able to share and continue chats with the team... we should be able to have multi-participant chats. But... we could do it in Slack." Her conclusion is the architecture's: threads are source-agnostic, and a Slack channel with amebo in it IS the multi-participant chat — Slack is the team surface, web chat the personal one. Revisit only if a team ends up without Slack/Discord (then the answer is a channel adapter, not a parallel chat product).
