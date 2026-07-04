"""
Data access for venue/thread org-routing state used by OrgResolver (arch §4.2):
- channel_defaults: a venue's default-org hint (workspace+channel -> org).
- conversation_org_pins: the org pinned to a thread (transient).
"""

import logging
from typing import Optional
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class OrgRoutingRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    # --- channel defaults (venue -> org hint) ---------------------------------

    def channel_default(self, workspace_id: str, channel_id: str) -> Optional[int]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id FROM channel_defaults "
                    "WHERE workspace_id = %s AND channel_id = %s",
                    (workspace_id, channel_id),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def set_channel_default(self, workspace_id: str, channel_id: str,
                            org_id: int) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO channel_defaults (workspace_id, channel_id, org_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (workspace_id, channel_id) DO UPDATE
                        SET org_id = EXCLUDED.org_id
                    """,
                    (workspace_id, channel_id, org_id),
                )
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)

    def workspace_default(self, workspace_id: str) -> Optional[int]:
        """The workspace-level default org (arch §4.2 step 6 fallback), read from
        org_workspaces: the primary link if flagged, else the sole link. Returns
        None if the workspace maps to zero or several non-primary orgs."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id FROM org_workspaces WHERE workspace_id = %s "
                    "AND is_primary = true LIMIT 1",
                    (workspace_id,),
                )
                row = cur.fetchone()
                if row:
                    return row[0]
                cur.execute(
                    "SELECT org_id FROM org_workspaces WHERE workspace_id = %s",
                    (workspace_id,),
                )
                rows = cur.fetchall()
                return rows[0][0] if len(rows) == 1 else None
        finally:
            DatabaseConnection.return_connection(conn)

    # --- conversation pins (thread -> org, transient) -------------------------

    def thread_pin(self, thread_ref: str) -> Optional[int]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id FROM conversation_org_pins WHERE thread_ref = %s",
                    (thread_ref,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def pin_thread(self, thread_ref: str, org_id: int,
                   pinned_by: Optional[int] = None) -> None:
        """Pin (or re-pin, on explicit re-targeting) a thread to an org."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_org_pins (thread_ref, org_id, pinned_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (thread_ref) DO UPDATE
                        SET org_id = EXCLUDED.org_id,
                            pinned_by = EXCLUDED.pinned_by,
                            pinned_at = NOW()
                    """,
                    (thread_ref, org_id, pinned_by),
                )
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
