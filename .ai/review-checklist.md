# Review checklist — run before every commit / on every diff

Governing spec: `/opt/shared/projects/plans/amebo/7-4-2026-amebo-architecture.md` (the multi-org contract, invariants **I1–I11**; agreed 2026-07-04). This checklist is how you *check* a diff against it — the spec itself is the source of truth. Anything the spec doesn't cover is not your decision: write the question to `scratch.md` and keep going on what is specified.

## Mechanical checks (run them, don't eyeball)

```bash
# I11 semantic core: vendor names may appear only in adapters/leaf tools/comments —
# never in resolution, dispatch, gate, or executor logic.
grep -riE 'slack|odoo|taiga|github' backend/src/services/ backend/src/tools/registry.py \
  | grep -viE '^\S+:\s*#|adapter|_claw|example'   # review every hit that remains

# I5 no env credentials in tool/channel code
grep -rn 'os.getenv' backend/src/tools/ backend/src/channels/ | grep -viE 'test|PATH'

# Tests
cd backend && pytest -q   # 5 pre-existing failures are known (changemaker 403s + chromadb); anything else is yours
```

## Judgment checks (the invariants, as review questions)

- **I1 participant, not owner** — does the diff cache shared-system state as truth, or assume amebo is the only writer? Goal-carryover notes must be re-verified against the world before acting (§8.1).
- **I2 fail-closed OrgContext** — can any tool run without a resolved OrgContext? Any fallback to a default org inside a tool is a bug.
- **I3 use-case-ignorant core** — any org name, team, or use case in core code? (Seeds and tests may name orgs; core may not.)
- **I4 one home per fact** — is a fact being stored in amebo's DB that belongs in the org's context repo, abra, Taiga, or the CRM? Abra is for *naming* (bindings); durable text goes in a repo.
- **I5/I10 hard gates** — every outbound/write path through the draft-approval gate; authorization decided in code (tier + membership + access_class), never by prompt text. Secrets never in model-visible content.
- **I6 reads free, writes gated** — new write tool without a gate test = incomplete.
- **I7 recognition ≠ attribution** — speaker identity from `person_identities` only; tool-account handles from `member_tool_accounts` only; never inferred from message content.
- **I8 additive migration** — migrations reversible (rollback comment present), applied-live safe, deprecated columns kept readable until their cutover WP.
- **I9 verbatim words** — filed ideas/skills keep the person's words; summaries are separate and marked.
- **I11 semantic core** — new concepts named semantically (venue, principal, membership), vendor logic pushed to adapters/kind-templates.

## Process checks

- Commit as you go; never leave a dirty tree; never `git stash` (hook-enforced).
- Board (`scratch.md`): status appended for anything another session must know; questions written there, not improvised.
- Human-facing docs updated in the same commit when behavior changes (`docs/`, `CLAUDE.md` if entry-level).
