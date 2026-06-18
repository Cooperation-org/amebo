# Credentials — current state (per-org vs global)

Evaluation as of 2026-06-16. Read alongside `POWERS_PLAN.md` (the per-org
design intent) and `CREDENTIAL_HELPER.md`. This doc is an honest snapshot of
what is *actually wired*, not the target architecture — the gap between them is
the point.

Short version: **mostly global in `.env`**, with a well-built per-org framework
(`CredentialResolver`) that is only partly adopted. Per-org is real for
Slack/Google, designed-but-not-adopted for everything else, and entirely global
for Taiga/Anthropic.

> **DIRECTION (decided 2026-06-18, Golda) — single-tenant per instance, for now.**
> We got too fancy chasing multi-tenant-in-one-process. New plan: **one amebo
> instance per org.** Other orgs are supported by giving them their **own
> instance** (own deployment + own `.env`), not by multiplexing one process across
> orgs. So global `.env` creds are *fine* — within a single-org instance they ARE
> that org's creds. The per-org `CredentialResolver` / `org_credentials` work
> below is **deferred**: keep it (it's good and additive) but do not block on
> wiring the consumer side. Revisit "are we really able to multi-tenant" later.
> Everything below describing the per-org gap is the *future* path, not the now.

## What is per-org today (actually working)

- **Slack** — genuinely per-workspace. `slack_bot_service` loads
  `bot_token / app_token / signing_secret FROM installations` (populated by
  Slack OAuth install). Multi-tenant.
- **Google** — per-org user tokens via `CredentialResolver` + `google_adapter`
  (OAuth'd, Fernet-encrypted, auto-refresh). This is the one provider wired
  end-to-end through the resolver.

## What is global in `.env` (single-tenant reality)

- **Taiga** — one service account (`TAIGA_USERNAME` / `TAIGA_PASSWORD`) shared by
  all orgs. No `taiga` kind in `org_credentials`, no adapter. mcp-taiga refreshes
  the JWT from these (so they are "long-lived" for our team).
- **Anthropic API key** — one key for everything. Arguably *correct* to keep
  global: it is amebo's own model budget, not an org's resource.
- **Google OAuth client id/secret**, **SMTP** — global. (The client id/secret
  *should* be global; the per-org part is the user token, which lives in
  `org_credentials`.)
- **Slack slash-command token** — `slack_commands.py` reads the global
  `SLACK_BOT_TOKEN` env even though `installations` has per-workspace tokens.
  **Inconsistent** with `slack_bot_service`.

## The framework that exists (the destination)

`src/credentials/resolver.py` — `CredentialResolver` — is a clean per-org
credential system: "single point of truth, tool code calls this, no other module
reads `org_credentials`." It encapsulates SQL storage on `org_credentials`,
Fernet encryption, pre-flight refresh (5-min buffer), DB-level refresh locking,
provider adapters (`base` / `google` / `fake`), and error normalization
(`CredentialMissing` / `CredentialExpired` / revoked).

**But its consumption side is not wired.** The resolver / `org_credentials` is
referenced by the OAuth / connect / admin paths (`slack_oauth.py`,
`workspaces.py`, `credential_service.py`) — the **producer** side. The actual
tools (`slack_post`, `abra`, `mcp_taiga`, the Anthropic calls) still read global
`os.getenv` or the older `installations` table — **not** the resolver. Only
Google goes producer→consumer through it.

## Net assessment

- The **invite-link flow** is exactly the right move — it is the *producer*:
  connect-link → OAuth → store an encrypted per-org credential via the resolver.
  It fills `org_credentials`.
- The unfinished half is the **consumer side**: making tools resolve their secret
  through `CredentialResolver(org_id, kind)` instead of `os.getenv`. Today only
  Google does this end-to-end.
- For the **claws** specifically (`pm_claw`, `opportunity_claw`): Taiga is fully
  global. There is no `taiga` kind/adapter, so `TaigaCliTaskReader.resolve()`
  (left injected) has nothing per-org to read — it works for our org only because
  the global `.env` creds happen to be our team's Taiga login.

## To finish per-org (when picked up)

1. **Adopt the resolver on the consumer side** — route tool secrets through
   `CredentialResolver(org_id, kind)` instead of `os.getenv`, provider by
   provider. Reconcile the two Slack paths (`installations` vs global env) onto
   one.
2. **Add a `taiga` kind + adapter** so per-org Taiga login tokens can live in
   `org_credentials`; then the claws' `resolve()` reads real per-org tokens.
3. Decide what *stays* global on purpose (Anthropic key, OAuth client id/secret)
   vs what must be per-org (provider access tokens).
