# amebo embed bundle

Single-file vanilla web components that surface amebo data inside any
host shell (abra view, demos, internal pages). Zero dependencies, no
build step.

`<amebo-claws>` accepts `data-status="active|pending|paused|..."` and
`data-limit="N"` (default 20) to filter the list.

## What's here

| File          | What                                                          |
|---------------|---------------------------------------------------------------|
| `amebo.js`    | The bundle. Registers `<amebo-ask>`, `<amebo-goal>`, `<amebo-claws>`, `<amebo-digest>`. |
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
401 renders nothing (signed-out visitors just see fewer cards). The
cookie carries the access JWT, so the embed session lasts as long as
that token (60 min from the user's last amebo login/refresh).

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
