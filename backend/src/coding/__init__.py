"""
Coding-agent orchestration.

An additive layer that turns conversation messages (from any channel adapter)
into dispatched coding work running on a Claude Agent SDK worker. It reuses the
existing channel contract and the source-agnostic `threads` model, and adds:

- one coding session per intention thread (mapped to a Claude Agent SDK session),
- a Postgres-serialized per-session work queue,
- dispatch-time model routing,
- worktree-isolated workers (behind an interface; stubbed until SDK auth wiring).

Nothing here is wired into the live `src/channels/dispatch.py` path. The
orchestrator is a separate entry point. Design:
/opt/shared/projects/Active/amebo/coding-agent-orchestration.md
"""
