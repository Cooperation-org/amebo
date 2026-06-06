# State Decay + Per-Store GC

Implements the Amebo BOUNDARIES design decision (2026-06-06):

> Amebo holds as little state as it can. Its own working state decays fairly
> quickly unless Amebo judges there is a reason to keep something; that
> judgment is part of its job. Anything worth keeping is crystallized out to a
> system of record and the rest decays. Garbage collection is NOT a single
> mechanism: each system of record runs its own GC appropriate to it,
> INCLUDING Amebo's own Abra working-memory scope (distinct from the durable,
> human-authored `golda` scope). Do not assume one GC policy fits every store.

## Pieces

`backend/src/services/state_decay/`

- `policy.py` — the `GcPolicy` protocol (what every store implements: `name`,
  `ttl`, `is_durable`, `enumerate_expirable`, `expire`), the `GcReport` result
  type, and `StoreRegistry` (one policy per store). `default_registry` is the
  process-wide registry.
- `judgment.py` — the pluggable retention hook `should_keep(item, *, store)`.
  Default `default_should_keep` is a cheap, conservative heuristic (no LLM, no
  network) that leans toward decay but honors explicit keep markers. Swap in a
  richer (e.g. LLM-backed) judge at runtime with `set_retention_judge(...)`.
  A judge that raises is treated as a vote to KEEP (fail-safe).
- `stores.py` — the three concrete policies and `register_default_policies()`.
- `runner.py` — `run_gc(registry=None, only=None)`. One pass over registered
  stores. Interposes the retention judge between enumerate and expire. Failures
  are isolated per store. Returns a list of `GcReport`.

## The three stores

| Store | TTL (default) | Durable / kept | Expiry behavior |
|-------|---------------|----------------|-----------------|
| `threads` (conversation threads/turns) | 24h idle | `retained_until > NOW()` | DELETE thread (turns cascade) |
| `goal_events` (audit trail) | 365d | n/a (audit) | Archival: enumerates old events, **deletes nothing** unless built with `allow_delete=True` |
| `abra_working_memory` (Amebo's own abra scope/catcode) | 30d | judge-only | **DRY-RUN by default**: lists what it would delete, deletes nothing. Real deletion requires `dry_run=False` and refuses the durable `golda` scope |

The thread TTL mirrors the existing 24h opportunistic GC in
`conversation_manager`. This subsystem generalizes that one-off into the
registry; the existing `ThreadRepo.garbage_collect` is left untouched.

### Retention marker for threads

Migration `015_thread_retention.sql` (committed, **not applied**) adds a
nullable `threads.retained_until TIMESTAMPTZ`. When the retention judgment
decides a thread is worth keeping past its idle TTL, it stamps a future
timestamp there; the thread store treats `retained_until > NOW()` as durable
and will not expire it. NULL means "no explicit retention decision — normal
decay applies." A dedicated column was chosen over reusing `last_active_at`
(which drives the TTL window) or the compaction fields, so retention and
activity stay independent. The thread policy tolerates the column being absent
(pre-migration) by selecting it defensively.

### Abra working-memory scope

Amebo's transient working memory lives under abra scope `amebo`
(`AMEBO_WORKING_SCOPE`), explicitly NOT the durable human-authored `golda`
scope. The policy reads/writes through `AbraConnection` (the same read path
used elsewhere in the repo) and joins `content` to its `bindings` by
`(scope, catcode)` per the context-store contract. **It defaults to dry-run and
will never operate on the `golda` scope** — constructing it for `golda` raises.

## Calling it from the scheduler tick (integration note)

`run_gc` is synchronous and side-effect-isolated, designed to be called from
the existing 60s `GoalScheduler.tick` (`backend/src/services/goal_scheduler.py`).
It is NOT wired in by this change (additive only; scheduler edit left as a
note). To wire it, add one throttled call at the end of `tick`, e.g.:

```python
# in GoalScheduler.tick(), after the dispatch loop:
from src.services.state_decay import run_gc
# Throttle: GC is cheap but need not run every 60s tick.
if self._gc_due(now):           # e.g. once per hour
    try:
        run_gc()
    except Exception:
        logger.exception("state-decay GC pass failed")
```

`run_gc()` against `default_registry` runs the live policies in their safe
default posture (threads delete past 24h idle; goal_events archival/no-delete;
abra working memory dry-run). No new daemon, no new background task.

## Enabling real abra deletion (deliberate, opt-in)

Real deletion from the abra working scope is opt-in and must be explicit:

```python
from src.services.state_decay import default_registry
from src.services.state_decay.stores import AbraWorkingMemoryPolicy

default_registry.unregister("abra_working_memory")
default_registry.register(
    AbraWorkingMemoryPolicy(catcode="amebo/working", dry_run=False)
)
```

Constructing it with `scope="golda"` raises; the delete path re-checks and
refuses the durable scope. **Do not enable this against the live abra DB
without review.**

## Tests

`backend/tests/test_state_decay_gc.py` — pure-Python, no DB:
TTL expiry, kept-items survive, retention-judgment hook respected, per-store
policies independent, abra-scope dry-run lists-but-deletes-nothing,
goal_events archival posture, durable threads survive, fail-safe judge.

Run: `cd backend && python -m pytest tests/test_state_decay_gc.py -v`
