"""
Equity distribution: when Taiga fires a Done webhook for a /drop-task,
create a DropRun + DropLine in the GovKit DB so the equity appears in the Pie.

GovKit DB is on the same Postgres host (10.0.0.100) as amebo's DB, different
database name (govkit). Read access uses a read-only user; write access needs
credentials with INSERT permission on the drops tables.

Flow (all within one transaction):
  1. Find pending_equity_tasks row by (taiga_project, taiga_ref)
  2. Skip if already done/failed
  3. Find govkit Membership by taiga_username (org matches the task's org_id)
  4. Create DropRun (state=APPROVED, opened_by/approved_by set to the membership)
  5. Create DropLine (computed_value = equity, final_value = equity, no tasks)
  6. Update pending_equity_tasks: status=done, drop_run_id, drop_line_id
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

import psycopg2
from psycopg2 import pool

logger = logging.getLogger(__name__)

# GovKit DB connection — same host as amebo, different database name.
# Credentials are derived from environment; if not set we fall back to the
# govkit service account credentials (TAIGA_USERNAME / TAIGA_PASSWORD are
# earnkit-managed and shared with GovKit's DB for exactly this kind of S2S access).
_GOVKIT_DB_POOL: Optional[pool.SimpleConnectionPool] = None


def _govkit_pool() -> pool.SimpleConnectionPool:
    global _GOVKIT_DB_POOL
    if _GOVKIT_DB_POOL is None:
        host = os.getenv("GOVKIT_DB_HOST", "10.0.0.100")
        port = os.getenv("GOVKIT_DB_PORT", "5432")
        dbname = os.getenv("GOVKIT_DB_NAME", "govkit")
        user = os.getenv("GOVKIT_DB_USER", "govkit")
        password = os.getenv("GOVKIT_DB_PASSWORD", "govkit")
        _GOVKIT_DB_POOL = psycopg2.pool.SimpleConnectionPool(1, 5,
            host=host, port=port, dbname=dbname, user=user, password=password)
    return _GOVKIT_DB_POOL


def _govkit_conn():
    return _govkit_pool().getconn()


def _return_conn(conn):
    _govkit_pool().putconn(conn)


def distribute_equity_on_done(taiga_project: str, taiga_ref: int) -> str:
    """
    Find the pending equity task and, if still pending, distribute its equity
    to the Pie via a newly created approved DropRun + DropLine.

    Called from the Taiga webhook thread pool (synchronous; runs in a thread,
    not an async context).

    Returns a human-readable confirmation string.
    Raises RuntimeError on failure (caller logs and returns 500).
    """
    from src.db.repositories.pending_equity_task_repo import PendingEquityTaskRepo

    repo = PendingEquityTaskRepo()
    pending = repo.find_by_taiga_ref(taiga_project, taiga_ref)

    if not pending:
        raise RuntimeError(f"No pending task found for {taiga_project}#{taiga_ref}")

    if pending["status"] == "done":
        return f"Already processed: {taiga_project}#{taiga_ref} is done."

    if pending["status"] == "failed":
        raise RuntimeError(f"Previously failed: {taiga_project}#{taiga_ref}")

    equity = pending["equity"] or 0
    cash = pending["cash"] or 0
    assignee = pending["assignee"] or ""
    govkit_org_slug = pending["govkit_org_slug"]
    discord_username = pending["discord_username"] or pending["discord_user_id"]
    subject = pending["subject"]

    if equity == 0 and cash == 0:
        # Nothing to distribute — just mark done
        repo.mark_done(pending["id"])
        return f"No equity on {taiga_project}#{taiga_ref}; marked done."

    if not govkit_org_slug:
        raise RuntimeError(f"No govkit_org_slug for {taiga_project}#{taiga_ref} — cannot distribute equity.")

    # Resolve GovKit membership for the assignee (by taiga_username)
    govkit_membership_id, govkit_org_id = _find_govkit_membership(assignee, govkit_org_slug)

    conn = _govkit_conn()
    try:
        with conn.cursor() as cur:
            # Create DropRun (approved immediately — no review queue for auto-distributed equity)
            cur.execute(
                """
                INSERT INTO drops_droprun
                    (org_id, opened_by_id, opened_by_user_id, state, approved_by_id, approved_at)
                VALUES (%s, %s, NULL, 'approved', %s, NOW())
                RETURNING id
                """,
                (govkit_org_id, govkit_membership_id, govkit_membership_id),
            )
            drop_run_id = cur.fetchone()[0]

            # Create DropLine with the equity as computed_value
            cur.execute(
                """
                INSERT INTO drops_dropline
                    (run_id, membership_id, computed_value, final_value)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (drop_run_id, govkit_membership_id, equity, equity),
            )
            drop_line_id = cur.fetchone()[0]

            conn.commit()

        logger.info(
            "Equity distributed: %s#%s → DropRun %s / DropLine %s for membership %s (equity=%s, cash=%s)",
            taiga_project, taiga_ref, drop_run_id, drop_line_id,
            govkit_membership_id, equity, cash,
        )

    except Exception as exc:
        conn.rollback()
        logger.error("Failed to create DropRun/DropLine: %s", exc, exc_info=True)
        repo.mark_failed(pending["id"], str(exc))
        raise RuntimeError(f"GovKit DB error: {exc}") from exc

    finally:
        _return_conn(conn)

    # Mark pending task as done
    repo.mark_done(
        pending["id"],
        govkit_membership_id=govkit_membership_id,
        drop_run_id=drop_run_id,
        drop_line_id=drop_line_id,
    )

    equity_str = f"{equity} equity" if equity else ""
    cash_str = f"${cash} cash" if cash else ""
    parts = [p for p in [equity_str, cash_str] if p]
    reward = ", ".join(parts)

    return (
        f"Equity distributed: {discord_username} received {reward} "
        f"from [{taiga_project}#{taiga_ref}] {subject!r}."
    )


def _find_govkit_membership(taiga_username: str, govkit_org_slug: str) -> tuple:
    """
    Find the GovKit membership row for the given Taiga username in the org.
    Returns (membership_id, govkit_org_id).

    Raises RuntimeError if the membership or org is not found.
    """
    import psycopg2.extras

    conn = _govkit_conn()
    try:
        with conn.cursor() as cur:
            # Find the GovKit org by slug
            cur.execute(
                "SELECT id FROM orgs_organization WHERE slug = %s",
                (govkit_org_slug,),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"GovKit org not found for slug={govkit_org_slug!r}")
            govkit_org_id = row[0]

            if taiga_username:
                cur.execute(
                    """
                    SELECT id FROM orgs_membership
                    WHERE org_id = %s AND taiga_username = %s
                    LIMIT 1
                    """,
                    (govkit_org_id, taiga_username),
                )
                row = cur.fetchone()
                if row:
                    return row[0], govkit_org_id

            raise RuntimeError(
                f"GovKit membership not found for taiga_username={taiga_username!r} "
                f"in org {govkit_org_slug!r}. Assign the task to a Taiga user."
            )
    finally:
        _return_conn(conn)
