# amebo embed bundle

Single-file vanilla web components that surface amebo data inside any
host shell (abra view, demos, internal pages). Zero dependencies, no
build step.

`<amebo-claws>` accepts `data-status="active|pending|paused|..."` and
`data-limit="N"` (default 20) to filter the list.

## What's here

| File          | What                                                          |
|---------------|---------------------------------------------------------------|
| `amebo.js`    | The bundle. Registers `<amebo-ask>`, `<amebo-goal>`, `<amebo-claws>`, `<amebo-digest>`, `<amebo-goals>`, `<amebo-skills>`. |
| `demo.html`   | Standalone sanity page that mounts all four components against a URL-param-configurable `data-up`. |
| `README.md`   | This file.                                                    |

The backend serves the bundle as a static file at `/embed/amebo.js`
(see `backend/src/api/main.py` — `StaticFiles` mount on `/embed`).

## Components

| Tag                  | Backing endpoint           | Mutates?                                  |
|----------------------|----------------------------|-------------------------------------------|
| `<amebo-ask>`        | `POST /api/qa/ask`         | No (queries only)                         |
| `<amebo-goal>`       | `GET /api/goals/{id}` + `/events` + dispatch-now / pause / resume | Yes |
| `<amebo-claws>`      | `GET /api/goals/?status=&limit=` | No                                  |
| `<amebo-digest>`     | `GET /api/digest`          | No                                        |
| `<amebo-create-claw>` | `POST /api/goals/`         | Yes (creates a claw in amebo's goals table; no abra write) |
| `<amebo-goals>`      | `GET /api/statements/` + `POST`/`PATCH` on edit | Yes (the org's goals, edited in place) |
| `<amebo-skills>`     | `GET /api/skills/?audience=` | No (links into chat)            |

### `<amebo-skills>` — what this dash can hand to amebo

The skills whose file carries a `button` and an `ask`, for the audience the
host asks for (`data-audience`, default `founder`), in the order the files
declare. Each one opens amebo's chat with that question already in the box,
unsent: the person edits it and presses send.

Nothing here is a list in code. A new skill file with `audience`, `order`,
`button` and `ask` in its frontmatter appears on every dash that asks for that
audience, and a skill without a `button` never appears at all.

### `<amebo-goals>` — the goals a person set

The org's own goals, from `org_statements` (`GET /api/statements/`) — mission,
vision, values, OKRs: what the team is aiming at. Golda 2026-08-17: "the
org_statements are the HUMAN goals, and the correct thing for the dash."

It used to read `/api/goals/` and filter out anything with a cron or a
`notify_channel`. That was the wrong table: `goals` is the claw table, every
open row in it is something amebo runs, and the card rendered nothing while the
team's real goals sat one table over.

**Editable in place.** "If you see it, and you have perms, you should be able to
edit right there" (golda 2026-08-17). The value is the control, it commits on
blur, there is no edit mode — the same inline-edit pattern amebo's own
statements page uses. Escape restores, Enter commits a title. A save that fails
keeps the person's words on screen rather than snapping back to the server's
version; a 403 turns that field read-only, so perms are the API's answer and
never a guess in the client. The last line adds a goal, in the same place and
the same way.

A statement amebo PROPOSED (`accepted_at` null) does nothing until a person
takes it. Those show marked as proposals, with the button that accepts them —
never mixed in silently with what the team actually said.

A statement that carries a `pointer` instead of `body` shows the pointer and
does not make it editable: the words live in that document, and nobody should
overwrite a document by typing in a card.

Signed out, or the API says no, the component empties itself and sets `hidden`,
so a host card that autohides on an empty component disappears with it.

Attributes: `data-up` (required), `data-limit` (default 5 accepted goals;
proposals are never cut).

Org is not an attribute — amebo resolves it from the session, so these are
always the viewer's own org's goals, whatever page the component sits on.

### `<amebo-create-claw>` — pure claw-create form

Plain form for creating a new claw row in amebo's `goals` table. No abra
involvement. Amebo manages claws; abra owns goals; the optional
goal-to-claw linkage is recorded abra-side via an EXECUTES_VIA binding,
written by whatever surface triggered this component (typically an
abra-side goals page listening for the `amebo-claw-created` CustomEvent
this component dispatches on success).

Attributes (all optional except `data-up`):
- `data-up` (required) — proxy base URL or origin.
- `data-title` — pre-fill title.
- `data-description` — pre-fill description.
- `data-cron` — pre-fill cron schedule (blank means manual dispatch only).
- `data-notify` — pre-fill notify channel (e.g. Slack channel id).
- `data-stores` — comma-separated list of context-store URLs the claw should read/write at each tick. Each URL implements the [`context-store-contract.md`](../../abra/context-store-contract.md) endpoints (POST/GET /entries). Amebo never parses these. Surfaces as an optional form input the user can override.
- `data-provenance` — who created this claw and how, as a JSON blob. Machine-fed only; not shown in the form.

The stores list and provenance pass through into the claw's `config` JSON unchanged. Amebo does not interpret them. See `arch_notes.md` "Context stores and claws" and `context-store-contract.md` for the durable contract.

## Host-shell contract

The bundle is dumb on purpose. The host shell tells each element where
to fetch from and what it represents:

| Attribute     | Set by shell | Meaning                                             |
|---------------|--------------|-----------------------------------------------------|
| `data-up`     | shell        | Base URL the component fetches from (proxy mount). |
| `data-ref`    | shell        | Full original target URI, e.g. `amebo:goal/42`.    |
| `data-scheme` | shell        | Scheme key from `sources.yaml`, e.g. `amebo:goal`. |
| `data-path`   | shell        | Everything after the scheme prefix, e.g. `42`.     |

Components parse `data-path` (or `data-ref`) themselves. The shell stays
scheme-agnostic — same attribute shape for amebo, Taiga, Odoo, anything.

**Org is not a component attribute.** It is resolved server-side from
the authenticated identity (the JWT carries the user; amebo derives the
org from there). Components never carry org.

All HTTP goes to `${this.dataset.up}/api/...`. No host or token in
this bundle. `credentials: 'include'` so cookies the shell already set
ride along.

## Deployment shape

Recommended: **same-origin proxy** while amebo and the host are co-located
on this VM. nginx proxies a path on the host's origin to amebo's backend.
Everything stays under one origin: no CORS, no cross-origin cookie games,
the bundle and the API calls all look like normal same-origin requests.

Example for the abra view on `demos.linkedtrust.us` (path `/abra-view/`):
add one block to `/etc/nginx/app-proxies/abra-view.conf` (or a sibling
file), reload nginx:

```nginx
location /abra-view/up/amebo/ {
    proxy_pass http://127.0.0.1:8000/;       # amebo backend
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_http_version 1.1;
}
```

Page markup:

```html
<script src="/abra-view/up/amebo/embed/amebo.js"></script>

<amebo-ask  data-up="/abra-view/up/amebo"></amebo-ask>
<amebo-goal data-up="/abra-view/up/amebo"
            data-ref="amebo:goal/42"
            data-scheme="amebo:goal"
            data-path="42"></amebo-goal>
<amebo-digest data-up="/abra-view/up/amebo"></amebo-digest>
```

Cross-origin direct (`data-up="https://amebo.<host>"`) is supported by
the bundle and by the backend's session cookie (below) — the shape the
cohort dash uses (see `PLAN-cohort-dash.md`).

## Auth

Amebo authenticates users via LinkedTrust OIDC / Google OAuth (team
recipe at `/opt/shared/cobox/oauth-login-pattern.md`) and issues a JWT
used in `Authorization: Bearer ...` by the SPA (localStorage).

**Session cookie (cross-origin embeds).** At OIDC callback and token
refresh the backend ALSO mirrors the session JWT into an
`HttpOnly; Secure; SameSite=Lax` cookie on the amebo host. The bundle
fetches with `credentials: 'include'`, so from any origin in the
backend's `CORS_ORIGINS` allowlist the cookie authenticates the embed —
no proxy, no token in the page. The Authorization header, when present,
always takes precedence over the cookie. A component whose fetch gets a
401 renders nothing (signed-out visitors just see fewer cards).

**401 → refresh → retry (the renewal contract).** The OIDC callback also
sets a second cookie carrying the refresh JWT, path-scoped to
`/api/auth/refresh` (the browser only ever sends it there). When a
bundle fetch gets a 401, the shared fetch helper makes ONE empty
`POST {up}/api/auth/refresh` with `credentials: 'include'`; the backend
reads the refresh cookie, re-sets both cookies (new access + same
refresh — no rotation), and the helper retries the original request
once. No loops — if the refresh or the retry fails, the original 401
flows through and the component stays hidden. Effective embed session:
as long as the SPA's — up to 30 days from the user's last actual login
(the refresh token is not rotated, so the horizon is fixed at
login + 30 days, not sliding).

Endpoints:
- `/api/qa/ask`, `/api/digest`, `/api/goals/*` — all accept Bearer JWT
  or the session cookie. `/api/goals/*` and `/api/organizations/links`
  also accept `X-API-Key` for service-to-service callers.

## Updating the bundle

Edit `amebo.js`. The view picks up the new copy on next page load — no
view redeploy. Bump the `// amebo embed bundle v<n>` header comment so
readers can tell which revision they're looking at.

## Adding a new component

1. Add a `class` definition that extends `HTMLElement` and reads from
   `this.dataset` only (no globals, no imports).
2. Register it in the IIFE: `if (!customElements.get('amebo-thing')) customElements.define('amebo-thing', AmeboThing);`.
3. Add it to the table above and to the host-shell registration block in
   `sources.yaml.example`.
4. Document the backing endpoint and whether it mutates.

If the component needs a new amebo endpoint, ship the endpoint first
with a placeholder response shape so the JS can be reviewed against a
running route.
