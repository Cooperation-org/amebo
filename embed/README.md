# amebo embed bundle

Single-file vanilla web components that surface amebo data inside any
host shell (abra view, demos, internal pages). Zero dependencies, no
build step.

`<amebo-goals>` accepts `data-status="active|pending|paused|..."` and
`data-limit="N"` (default 20) to filter the list.

## What's here

| File          | What                                                          |
|---------------|---------------------------------------------------------------|
| `amebo.js`    | The bundle. Registers `<amebo-ask>`, `<amebo-goal>`, `<amebo-digest>`. |
| `README.md`   | This file.                                                    |

The backend serves the bundle as a static file at `/embed/amebo.js`
(see `backend/src/api/main.py` — `StaticFiles` mount on `/embed`).

## Components

| Tag                  | Backing endpoint           | Mutates?                                  |
|----------------------|----------------------------|-------------------------------------------|
| `<amebo-ask>`        | `POST /api/qa/ask`         | No (queries only)                         |
| `<amebo-goal>`       | `GET /api/goals/{id}` + `/events` + dispatch-now / pause / resume | Yes |
| `<amebo-goals>`      | `GET /api/goals/?status=&limit=` | No                                  |
| `<amebo-digest>`     | `GET /api/digest`          | No                                        |

## Host-shell contract

The bundle is dumb on purpose. The host shell tells each element where
to fetch from and what it represents:

| Attribute     | Set by shell | Meaning                                             |
|---------------|--------------|-----------------------------------------------------|
| `data-up`     | shell        | Base URL the component fetches from (proxy mount). |
| `data-ref`    | shell        | Full original target URI, e.g. `amebo:goal/42`.    |
| `data-scheme` | shell        | Scheme key from `sources.yaml`, e.g. `amebo:goal`. |
| `data-path`   | shell        | Everything after the scheme prefix, e.g. `42`.     |
| `data-org`    | shell        | Current org context, if known.                     |

Components parse `data-path` (or `data-ref`) themselves. The shell stays
scheme-agnostic — same attribute shape for amebo, Taiga, Odoo, anything.

All HTTP goes to `${this.dataset.up}/api/...`. No host or token in
this bundle. `credentials: 'include'` so cookies the shell already set
ride along.

## Deployment shape (single-origin, recommended)

Per the abra view session (2026-05-31): the host shim proxies amebo
under a single-origin mount, including the bundle. From the page's
point of view:

```html
<script src="/abra-view/up/amebo/embed/amebo.js"></script>

<amebo-ask  data-up="/abra-view/up/amebo"></amebo-ask>
<amebo-goal data-up="/abra-view/up/amebo"
            data-ref="amebo:goal/42"
            data-scheme="amebo:goal"
            data-path="42"
            data-org="cooperation.org"></amebo-goal>
<amebo-digest data-up="/abra-view/up/amebo"></amebo-digest>
```

The proxy forwards a per-user JWT (carrying `user_uri`) to amebo. amebo
audits every call as the real user, not the view-server identity.

## Auth notes (per-user JWT vs service key)

- `/api/qa/ask` and `/api/digest` use `get_current_user` (JWT). These
  work end-to-end through the proxy as soon as the proxy mints / forwards
  a per-user JWT.
- `/api/goals/*` currently uses `get_service_client` (X-API-Key). To run
  `<amebo-goal>` through the same proxy with end-to-end user identity,
  the goals routes need to also accept a JWT. Pending view-session
  confirmation before widening that surface.

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
