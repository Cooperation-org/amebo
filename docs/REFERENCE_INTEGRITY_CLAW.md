# Reference Integrity Claw

A read-only claw that uses the system to track itself: it validates the
cross-system *pointers* amebo/abra hold and flags the ones that have gone
dangling. It writes nothing and notifies no one.

## Why

Per the storage split in `ORGS_GOALS_CLAW.md`, a name-binding holds a
*pointer* into another system of record, not a copy of that system's data.
Bindings carry `(scope, name, relationship, target_type, target_ref)`. When
`target_ref` points at a CRM contact or a Taiga task, the binding is only as
good as that target's continued existence. Targets get deleted, merged, and
archived; the pointer is left dangling. This claw finds those.

This is "sync pointers, not data; flag dangling references" applied to
amebo's own bookkeeping.

## What it does

`ReferenceIntegrityService.check_scope(scope, names)`:

1. Reads bindings for each name (read-only `BindingReader`).
2. Keeps only bindings whose `target_type` is a cross-system reference
   (`crm_contact`, `taiga_task` by default). `content` (amebo-internal) and
   `uri` (the `amebo:claw/<goal_id>` pointer convention and arbitrary external
   URLs) are skipped, not flagged.
3. Resolves each reference against its system of record via an injected,
   read-only `ReferenceResolver` and classifies:
   - `OK` — target exists.
   - `DANGLING` — system answered; target is gone.
   - `UNRESOLVABLE` — system unreachable/errored, or no resolver registered
     for that kind. Never treated as dangling: we never flag on a guess.
4. Returns a structured `IntegrityReport` (counts + per-reference checks,
   with `dangling`/`unresolvable` slices carrying enough detail —
   `binding_id`, `scope`, `name`, `target_type`, `target_ref` — to locate
   each problem). `report.to_dict()` is JSON-serializable.

## Read-wiring status (real vs. TODO)

- **Bindings (abra/amebo):** wired. The existing read-only
  `src.db.repositories.binding_repo.BindingRepo.search_bindings_by_name`
  satisfies the `BindingReader` protocol with no changes.
- **CRM (Odoo) and Taiga:** the resolvers in
  `reference_integrity_adapters.py` call the existing read-only CLI wrappers
  (`odoo-cli`, `mcp-taiga` via `registry._exec_cli_tool`) with a read-only
  `show` subcommand, but the **exact read subcommand and output schema for an
  existence probe are not pinned down in this repo**, so they are marked
  `TODO` and default to `UNRESOLVABLE` for any non-error output rather than
  guessing existence. Confirm the read subcommands before relying on
  `OK`/`DANGLING` from CRM/Taiga. This is the safe direction: a parsing miss
  yields `UNRESOLVABLE`, never a false `DANGLING`.

## Files

- `backend/src/services/reference_integrity.py` — service, report shapes,
  resolver `Protocol`s, and the `run_reference_integrity_claw` entry point.
- `backend/src/services/reference_integrity_adapters.py` — real read-only
  CLI-backed resolvers (CRM/Taiga) + `default_resolvers()`.
- `backend/tests/test_reference_integrity.py` — fully-mocked unit tests.

## Integration note (NOT wired)

The claw is intentionally **not** registered anywhere. To run it from the
`GoalScheduler` tick later, call:

```python
from src.services.reference_integrity import run_reference_integrity_claw
report = run_reference_integrity_claw(scope, names, org_id=org_id)
```

`names` is the set of binding name-keys to check. The binding store is
name-keyed (`search_bindings_by_name`), so a scope-wide enumeration needs a
name source — e.g. the `names` an org already tracks in abra, or a future
`list_bindings(scope)` read added to `BindingRepo`. Pin that source before
wiring to the scheduler.

## Out of scope (deliberately)

Notifying a human about dangling references is **out of scope** here. That is
an outbound action and must route through the existing draft-approval gate
(`ORGS_GOALS_CLAW.md`, "Human-in-the-loop drafts"). This claw's only output is
the returned/logged `IntegrityReport`. It performs no writes and sends no
messages.
