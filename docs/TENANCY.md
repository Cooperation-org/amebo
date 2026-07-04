# Tenancy — how amebo serves many orgs

*The multi-org model as built (WP1–WP17). Governing contract: `/opt/shared/projects/plans/amebo/7-4-2026-amebo-architecture.md` (invariants I1–I11). This doc is the practical map: the nouns, how an action finds its org, how a tool finds its connection, and how to add an org / tool / channel — all data, no code.*

## The nouns

| Noun | Is | Cardinality | Where it lives |
|---|---|---|---|
| **Org** | The tenant. Any size — a team or one person. | many | `organizations` (pointer + slug/name/aliases/context_repo); everything else in its **context repo** |
| **Instance** | An amebo deployment/persona (identity prompt, channel apps). **Serves N orgs.** | few | `instances`, `instance_orgs` join |
| **Person** | A global identity, member of N orgs. | many | `platform_users` (org-neutral) + `org_members` |
| **Capability** | Anything an org connected: CRM, tasks, repo, knowledge, chat. | per org | the org's `org.yaml` manifest + `org_credentials` |

`instances.org_id` and `platform_users.org_id` are **deprecated** (mig 020) — kept readable, mirrored into `instance_orgs` / `org_members` by DB triggers, retired at the WP17 cutover.

## Recognition vs attribution (I7 — keep them apart)

- **Recognition** — "who is talking to me?" → a person. Amebo's auth state, in `person_identities` (`provider`, `context_ref`, `external_id` → `user_id`). Created by provisioning/admin, **never inferred from message content**.
- **Attribution** — "who is this person inside the org's tools?" (their Slack `@`-handle, Taiga user) → in `member_tool_accounts`. Read to mention/assign. `MemberToolAccountRepo.slack_mention(org, user)`.

## How an action finds its org (OrgContext, arch §4.2)

Every tool runs under an `OrgContext {org_id, instance_id, actor_type, actor_person_id, authority, venue}`. It's resolved **before** the agent loop by `OrgResolver` (`services/org_resolution.py`):

1. venue → instance · 2. speaker → person (`person_identities`)
3. **candidates** = `memberships(person) ∩ orgs_for_instance(instance)`
4. **explicit targeting** in the utterance — first org *named* (name/slug/alias) wins, and **pins** the thread ("file this under raise the voices")
5. **thread pin** (`conversation_org_pins`) · 6. **channel default** (`channel_defaults`, else the workspace's default) · 7. **sole membership** · 8. else **ask one short line**.

Goal dispatch resolves trivially from `goal.org_id` (`actor_type=claw`, service authority). No org → no org-scoped tool runs (fail-closed, I2).

**Authorization** (I10, arch §4.3) is code below the model, at the tool executor: a `Principal` (transport-agnostic) is scored by a **swappable `TrustEvaluator`** to a tier (T0 unknown → T2 authenticated → SERVICE claw); each tool declares an `access_class`; the executor refuses below-threshold calls. Swap the scorer (e.g. LinkedTrust-backed) via `set_trust_evaluator` — the gate and tools don't change.

## How a tool finds its connection (ConnectionResolver, arch §5)

`credentials/connections.resolve(org_id, tool_key) -> ToolConnection`:

```
organizations.context_repo → pull → parse org.yaml (60s TTL) → tools[tool_key]
   → base_url + config from the manifest
   → credential from org_credentials via the manifest's `cred:` label
```

`ToolConnection.as_subprocess_env()` builds the exact env each CLI wants (per-`kind` template: `odoo_cli→ODOO_*`, `mcp_taiga→TAIGA_*`, `abra→ABRA_DATABASE_URL`). CLI tools do `run_cli(argv, env=...)` — `os.environ` is never mutated (I5).

**Absent = data, not a branch.** No manifest entry → `ToolNotConfigured` (the same for a missing CRM, Discord, or email). Bad manifest → `ManifestInvalid`. Never a silent fallback to stale config (I1).

**Transition:** tools resolve per-org when the org has a manifest, else fall back to the process env (via `_conn_env` / `_crm_conf` / `_projects_root`). linkedtrust runs on the env fallback until its `org.yaml` is seeded; the fallbacks retire at the WP17 cutover.

## The `org.yaml` manifest (in the org's context repo, arch §2.1/§5)

```yaml
schema: 1
org: raise-the-voices
aliases: [rtv]
tools:
  crm:       { kind: odoo_cli,  base_url: https://…, db: rtv_crm, cred: crm-service }
  tasks:     { kind: mcp_taiga,  base_url: https://…, project: rtv, cred: taiga-service }
  knowledge: { kind: abra,       scope: rtv }
  projects:  { kind: git_repo,   path: /opt/shared/…, active_dir: Active }
  chat:      { kind: slack_app,  workspace: T0XXXX, cred: slack-bot }
```
`cred:` values are **labels** into `org_credentials` (secrets never in git). Absent key = capability not connected.

## Add a new org (no code — UC-9, WP17)

`services/org_provisioning.provision_org(slug, name, context_repo=…, aliases=…, instance_id=…, members=[…])`:
creates the `organizations` pointer, attaches it to an instance (`instance_orgs`), adds members (`org_members`) + their tool accounts (`member_tool_accounts`). Idempotent; `dry_run=True` shows the plan. Then seed the org's `org.yaml` (in its context repo) + secrets (`org_credentials`) — those carry real credentials, done separately. **Zero amebo code changes** to add an org.

## Add a tool or channel for one org

1. Add a `tools:` entry to the org's `org.yaml` (a new `kind` + its `cred:` label).
2. Store the secret in `org_credentials` under that label.
3. If the `kind` is new, add its env-template to `connections._env_for` (a leaf; vendor names live only here, I11) and a tool that calls `run_cli(argv, env=_conn_env(context, "<tool_key>"))`.
That's it — no core resolution/dispatch/gate change.

## Skills, knowledge, feedback (org-owned)

- **Skills** are repo files: core in the packaged catalog (`prompts/skills/`), org-specific overlaid from the org's context repo (`<repo>/skills/`). `file_skill` writes a member's words **verbatim** to the resolved org's repo (I9); `list_skills`/`load_skill` read core + overlay.
- **Knowledge** is the org's abra scope (manifest `knowledge.scope`); reads are org-isolated (`BindingService(org_id)`) + scope-filtered.
- **Feedback / corrections** → the org's space (planned: `capture_feedback` + `guidance.md`), so a correction sticks (UC-10).

## Invariant cheat-sheet
I1 participant not owner · I2 fail-closed OrgContext · I3 use-case-ignorant core · I4 one home per fact · I5 no env creds in tools · I6 reads free/writes gated · I7 recognition ≠ attribution · I8 additive migration · I9 verbatim words · I10 auth is code · I11 semantic core (vendor names only in leaves).
