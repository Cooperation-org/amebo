# Credential Helper — the two-authority consumer seam

The Credential Helper is the encapsulated boundary that issued OAuth/SSO
tokens flow **into**, and that the rest of amebo (goal dispatcher, tools,
background claws) asks for a **capability**: a scoped token or nothing. No
call site ever sees a raw secret, a refresh token, or an all-powerful
token.

This document is the contract for the people who build OAuth/SSO issuance
(other sessions own that code). It explains where issued tokens get stored
so the helper can hand them out, and how the consumer side selects between
the two authorities.

Source: `backend/src/credentials/credential_helper.py`.
Public import surface: `from src.credentials import CredentialHelper, ScopedToken`.

## Two kinds of authority

Amebo acts under exactly one authority per turn (BOUNDARIES decision,
2026-06-06):

| | Delegated | Service / team |
|---|---|---|
| When | Live turn, on behalf of a person | Background claw |
| Acts as | That person, bounded by their grant | The team's own service identity |
| Tokens belong to | The person | The team (a bot account) |
| Retrieved | Per-turn | Held by amebo, isolated per team |
| Acting identity | `urn:amebo:user:<principal>` | `amebo:<team>` |
| Helper method | `get_delegated(...)` | `get_service(system, team)` |

`team` in the helper's API is the **org** (`org_id`). We use the word
"team" because that is the BOUNDARIES vocabulary; internally it is the same
integer the existing `CredentialResolver` expects.

## What the consumer side gets: `ScopedToken`

```python
@dataclass(frozen=True)
class ScopedToken:
    system: str                      # 'gmail' | 'github' | 'slack' | ...
    scope: tuple[str, ...]           # granted scopes (fine-grained gate)
    expires_at: datetime | None
    acting_identity: str             # stamped: person URI or amebo:<team>
    authority: str                   # 'delegated' | 'service'
    def reveal() -> str              # raw token — call ONLY at the wire
    def has_scope(required) -> bool
    @property is_expired -> bool
```

The secret value is **never** in `repr()` / `str()` / `%r` — it shows
`value=<redacted>`. Code that puts the token on the wire calls
`tok.reveal()` at that one point; everything else logs the `ScopedToken`
freely.

## How a turn selects delegated vs service

The dispatcher already knows which mode a turn is in:

- A **live turn** has an authenticated person on it (the API already builds
  `urn:amebo:user:<google_sub>` in `api/routes/intentions.py`). That
  `<google_sub>` is the `principal`.
- A **background claw** has no live person; it runs as `amebo:claw/<uuid>`
  for the org. That org is the `team`.

```python
from src.credentials import CredentialHelper
creds = CredentialHelper()           # default: ResolverCredentialStore

# Live turn acting AS a person (org known from the auth context):
tok = creds.get_delegated_for_team("gmail", principal=google_sub, team=org_id)

# Background claw acting as the team's service identity:
tok = creds.get_service("github", team=org_id)

if tok is None:
    # No usable credential. Live turn -> mint a connect-link
    # (src.credentials.mint_connect_link). Background claw -> record a
    # goal_event noting the missing power and stop that branch.
    ...
elif not tok.has_scope("repo"):
    # Connected, but not with the scope this action needs -> reconnect with
    # broader scope rather than failing mid-action.
    ...
else:
    use(tok.reveal())
```

`get_delegated(system, principal)` exists for call sites that only have the
principal; with the DB store it returns `None` and steers you to
`get_delegated_for_team` (the DB is keyed by org). The env store can serve
principal-only lookups directly.

## How `allowed_tools` (coarse gate) composes with credential scope (fine gate)

Two independent gates, applied in order:

1. **Coarse — `allowed_tools`** (existing, in `goal_guardrails.py` /
   `tools/registry.py`): *is this tool permitted for this goal/instance at
   all?* Decided from `instance.config.allowed_tools` before any credential
   is touched. A tool not in `allowed_tools` never runs, regardless of
   credentials.

2. **Fine — credential scope** (this helper): *does the acting authority
   actually hold a usable, sufficiently-scoped token for the system this
   tool calls?* Checked via `ScopedToken.has_scope(...)` / `is_expired`.

Both must pass. The coarse gate is about policy ("this claw may use
`slack_post`"); the fine gate is about capability ("…and team 7's service
identity actually has a Slack token with `chat:write`"). The helper never
widens the coarse gate and the coarse gate never substitutes for missing
credentials.

## Storage: where the OAuth/SSO owners plug issued tokens IN

Storage is swappable behind the `CredentialStore` Protocol
(`fetch(authority, team, owner_key, system) -> ScopedToken | None`). The
helper accepts a layered list of stores (first hit wins), so a deployment
can stack `EnvCredentialStore` (static service secrets) in front of the
DB-backed store in front of a future vault/KMS/SSO-broker store **without
changing any call site**.

### Default: `ResolverCredentialStore` (reuses the existing encrypted layer)

The default store reuses the existing `org_credentials` table and
`CredentialResolver` (migration 010) — the same Fernet encryption,
pre-flight refresh, 401 retry, and revoke. It maps the helper's key onto
the resolver's `(org_id, kind, label)` UNIQUE key:

| Authority | org_id | kind | label |
|---|---|---|---|
| Delegated person X | `team` | `system` | `user:<principal>` |
| Team service | `team` | `system` | `service` |

**This is the integration point.** The OAuth/SSO callback owners do **not**
need to know about this helper. They keep calling the resolver's existing
admin API exactly as today; they only choose the `label`:

```python
from src.credentials import CredentialResolver

# Delegated: a person connected their own Gmail during a live turn.
CredentialResolver.store_new(
    org_id=org_id, kind="gmail", label=f"user:{principal}",
    access_token=..., refresh_token=..., expires_at=...,
    granted_scopes=[...], connected_by_user_id=user_id,
)

# Service: an admin connected the team's bot GitHub account.
CredentialResolver.store_new(
    org_id=org_id, kind="github", label="service",
    access_token=..., refresh_token=..., expires_at=...,
    granted_scopes=[...], connected_by_user_id=admin_user_id,
)
```

That is the entire wiring: **issue as today, choose the label**, and the
helper hands the token to consumers as a `ScopedToken`. The
`connect_links` flow (`mint_connect_link` / `consume_connect_link`) is
unchanged; pass the same `label` through it.

### Why no new `service_credentials` table

The two-authority distinction is fully expressible in `org_credentials` via
the `label` namespace, so **no schema change is required** and the helper
stores nothing new in the DB. A separate table would duplicate the
encryption, refresh, and revoke machinery and create a second place secrets
could leak. Isolation is already guaranteed by the existing
`(org_id, kind, label)` UNIQUE key: a service lookup for team A
(`org_id=A`) cannot return team B's row, and `user:X` can never collide with
`user:Y`.

A migration file is included for documentation and an optional index:
`backend/migrations/016_credential_helper_label_convention.sql` —
**NOT APPLIED**. It only adds a column comment recording the label
convention and one partial index; it adds no token data and changes no
existing column. Apply it only after the OAuth owners confirm the
convention.

### `EnvCredentialStore` (static service secrets / dev)

For systems whose service token is a static secret injected by the
deployment (not an OAuth-refreshable token), and for local dev. Key:

```
AMEBO_CRED__<AUTHORITY>__<TEAM>__<OWNER>__<SYSTEM>
AMEBO_CRED__<...>__SCOPES        # optional, comma-separated
```

e.g. `AMEBO_CRED__SERVICE__1__SERVICE__GITHUB=ghp_...`. There is no
wildcard / "all teams" variable — the team and owner are always in the name,
preserving isolation.

### Future stores

Implement `CredentialStore.fetch(...)` for vault, KMS, or an SSO broker and
prepend it to the `CredentialHelper(...)` store list. No call site changes.

## Invariants (enforced in code, covered by tests)

- **No god-token.** Every accessor requires `system` plus an owner
  (`principal` or `team`). There is no method returning an unscoped or
  cross-owner token. (`tests/test_credential_helper.py::TestNoGodToken`)
- **Per-team / per-principal isolation.** The owner is part of the lookup
  key in every store. (`TestIsolation`)
- **Acting identity stamped.** Every `ScopedToken` carries the person URI or
  `amebo:<team>`. (`TestAuthoritySelectionAndIdentity`)
- **Secret-safe.** `ScopedToken` never renders its value.
  (`TestScopedTokenSecrecy`)

## Boundaries / what is left to the OAuth owners

- **Issuance** (consent URLs, code exchange, refresh-token acquisition,
  callback routes, login) is owned elsewhere and untouched here. This seam
  is read-side: it consumes what issuance writes.
- The OAuth owners decide **whether** a given system's service token is
  OAuth-refreshable (store via the resolver, `label="service"`) or a static
  injected secret (env store). The helper serves either.
- Final mapping of a live request to `(principal, org_id)` is the
  dispatcher/auth layer's job (it already builds `urn:amebo:user:<sub>`);
  the helper only consumes those values.

## Running the tests

```
cd backend
python -m pytest tests/test_credential_helper.py -q
```

DB-free: in-memory and env stores plus a monkeypatched resolver. No real
database, no real credentials, no OAuth provider contact. 24 tests.
