# Cohort Dash — cross-repo plan (amebo copy)

2026-07-19. One of six coordinated plan files, one per repo:
`workers.vc`, `govkit`, `amebo`, `marten`, `crm-outreach-runner`, `earnkit` —
each named `PLAN-cohort-dash.md` at the repo root. The **Architecture**
section is identical in all six; the **This repo** section is per-repo.
Work in parallel; commit and push regularly; each repo only implements its
own section and consumes the others' contracts as written here.

## Architecture (shared across all six repos)

**Goal.** Land accelerator teams on a real dashboard: the v3 design
(demos.linkedtrust.us/workersvc-design/dashboard.html) grown out of the
existing `/dash/` page, plus a mentor view, so invites can go out now.

**Principle** (amebo docs/DASHBOARD.md): the dash is an orientation
surface, not a workspace. Every fact lives in the tool that owns it; the
dash renders read-only cards and every card expands into the owning app
(Marten, GovKit, CRM, amebo). No fact is copied into the dash's DB.

**Mechanism: web components, one bundle per owning app.** Following the
existing amebo embed pattern (`amebo/embed/amebo.js`): each app ships a
vanilla-JS custom-elements bundle as a static file from its own origin.
The dash page includes the scripts and mounts the tags. No build step, no
framework, no shared library.

**Auth: SSO + same-site cookies + CORS allowlist.** Everything runs under
`*.workers.vc`, and every app logs in via LinkedTrust OIDC
(live.linkedtrust.us). Because all hosts share the registrable domain
`workers.vc`, each app's `SameSite=Lax` session cookie IS sent on a
credentialed fetch from the dash page — the only missing layer is CORS
response headers. So each app: (1) allowlists `https://workers.vc` (and
`https://www.workers.vc`) for CORS **with credentials**, scoped to its
JSON API paths; (2) authenticates component fetches with its normal
session cookie (`credentials: 'include'`). A component whose upstream
returns 401/403 renders nothing (the existing dash behavior) — signed-out
or non-member visitors just see fewer cards. Never render placeholder or
demo data.

**Org scoping.** The dash is per-team: `workers.vc/dash/<org-slug>/`.
The org slug is the shared tenant key across GovKit (`Org.slug`), amebo
(`organizations.slug` / instance orgs), Taiga (project slug), and Odoo
(DB `crm-<slug>_vc`, host `crm-<slug>.workers.vc`) — provisioned together by
`earnkit/playbooks/add-team.yml`. Components take the org via a
`data-org` attribute where the owning app needs it (GovKit), or resolve
it server-side from the authenticated identity (amebo — org is never a
component attribute there).

**Card → owner map** (v3 design → who ships the component):

| Card | Owner | Component | Expand target |
|---|---|---|---|
| The pie | GovKit | `<govkit-pie>` | `dash.workers.vc/o/<org>/pie/` |
| Earned on tasks (hours feed) | GovKit | `<govkit-feed>` | `dash.workers.vc/o/<org>/pie/` |
| Curriculum tracker | GovKit (genesis checklist) | `<govkit-checklist>` | `dash.workers.vc/o/<org>/` |
| Tasks to do | GovKit (tasksources → Taiga) | `<govkit-tasks>` | `martin.workers.vc/p/<org>/board` |
| Money | GovKit (projects app) | `<govkit-money>` | `dash.workers.vc/o/<org>/projects/` |
| Reach out (CRM) | crm-outreach-runner (Odoo) | `<crm-reachout>` | `crm-<org>.workers.vc` Outreach Runner |
| Ask amebo | amebo (exists) | `<amebo-ask>` | `amebo.workers.vc` |
| Campaigns / GTM board | amebo (`/api/organizations/board`) | `<amebo-board>` (phase 2) | org context repo / CRM / Taiga links |
| Whiteboard | amebo (phase 2) | — | amebo whiteboard |
| Tools row, faces, launch card | workers.vc server-side | — | — |

**Mentors.** No new role system. A mentor is a person with GovKit
`Membership` rows in multiple orgs (the accelerator org plus team orgs).
`GET dash.workers.vc/api/v1/accounts/me/` already returns
`memberships[{org_slug, org_name, role}]` — the dash uses it (via the
same CORS/session mechanism) to render an org switcher and a mentor
overview listing every org the viewer belongs to. Mentor booking info
(calendar_url/time_level) already lives in workers.vc's ledger.

**Deploys.** Push to main deploys workers.vc / govkit / amebo / marten
via GitHub Actions → `/opt/earnkit/bin/update-*` (service restart). Odoo
addons and nginx/env changes deploy by ansible run (see earnkit plan).

**Sequencing.** GovKit's CORS + bundle is the critical path (4 of the 8
cards); everything else proceeds in parallel against these contracts, and
each card goes live the moment its owner ships.

---

## This repo: amebo — cookie session for the embed, CORS origins, links auth

This plan follows the repo's own rules: no custom endpoints for app
clients (CLAUDE.md "Custom Endpoints Are an Antipattern"), org resolved
server-side from identity, core stays use-case-ignorant.

### Current state (verified 2026-07-19)

- Embed bundle exists (`embed/amebo.js`, served at `/embed/amebo.js`):
  `<amebo-ask>`, `<amebo-goal>`, `<amebo-digest>`, `<amebo-claws>`,
  `<amebo-create-claw>`. All fetches use `credentials:'include'` —
  **cookie auth** — but amebo sessions are JWTs handed to the Next.js
  frontend and stored in localStorage; no session cookie is ever set.
  So on a cross-origin dash the components have no way to authenticate
  today (embed README assumes a same-origin proxy instead).
- CORS (backend/src/api/main.py:42-59): origins from `CORS_ORIGINS` env;
  default list is localhost + demos.linkedtrust.us. `allow_credentials`
  already True. `https://workers.vc` not included; `CORS_ORIGINS` not set
  in deploy env.
- `GET /api/organizations/links` (organizations.py:353) returns
  `instances.config->'links'` — the dash tools row. JWT-only
  (`get_current_user`); workers.vc currently calls it S2S with a **user
  JWT** stashed in its env (doorway/amebo.py notes amebo has no service
  token for it). `X-API-Key` service auth exists (`get_service_or_user`)
  but only `/api/goals/*` accepts it.
- `GET /api/organizations/board` (organizations.py:375) reads
  `instances.config->'board'` from the org context repo
  (`organizations.context_repo`, migration 022) — fails closed to
  `{items:[]}`. The campaigns/GTM card feed, once a team's context repo
  is provisioned.
- AuthGate: external requests (nginx stamps `X-Amebo-Edge: public`) need
  Bearer JWT or X-API-Key; loopback passes.

### Work items (in order)

1. **Session cookie for browser auth** — at OIDC callback (and refresh),
   also set the session JWT as an `HttpOnly; Secure; SameSite=Lax`
   cookie on the amebo host, and accept it in `get_current_user` as a
   fallback when no `Authorization` header is present (header keeps
   precedence; CSRF exposure is limited — state-changing embed calls are
   the gated-goals ones, and Lax blocks cross-site POSTs). This makes
   `credentials:'include'` embeds work cross-origin exactly as the
   bundle already assumes. Frontend localStorage flow unchanged.
2. **CORS origins** — document + support
   `CORS_ORIGINS=https://workers.vc,https://www.workers.vc,https://amebo.workers.vc`
   for the cohort deployment (env change itself rides earnkit's
   amebo.env.j2; add to `.env.production.example`). AuthGate must let a
   cookie-authenticated request through the public edge — extend the
   gate to accept the session cookie as a credential.
3. **Service auth for links** — allow `get_service_or_user` on
   `GET /api/organizations/links` (org resolved from the API key's
   org_id) so workers.vc's server-side tools-row fetch uses a real
   `api_keys` entry instead of a personal JWT. Provision a key for the
   doorway.
4. **`<amebo-board>` component** (phase 2, after a team org has a
   context repo): add to `embed/amebo.js` — renders
   `GET /api/organizations/board` items (name, one-liner, status, owner,
   links out to MAIN.md / CRM / Taiga per DASHBOARD.md v1 scope). Same
   contract as the other components: `data-up`, cookie auth, empty on
   401/no-config.
5. **Digest on the dash** (optional, phase 2): `<amebo-digest>` already
   exists and becomes usable on the dash as soon as items 1-2 land —
   no code, just note it for the workers.vc side.

### Definition of done

From `https://workers.vc` with an amebo session (established by logging
into amebo.workers.vc once): `<amebo-ask data-up="https://amebo.workers.vc">`
answers; unauthenticated visitors see nothing. workers.vc fetches links
with an API key. `GET /api/organizations/board` serves a provisioned
org's campaigns to the phase-2 component.
